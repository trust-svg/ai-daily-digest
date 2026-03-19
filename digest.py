"""AI Daily Digest — 毎朝AIニュースを収集・要約・Telegram送信."""

import os
import re
import asyncio
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path
from html import unescape

import anthropic
from telegram import Bot
from dotenv import load_dotenv

load_dotenv()

JST = timezone(timedelta(hours=9))
TODAY = datetime.now(JST).strftime("%Y-%m-%d")

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

OUTPUT_DIR = Path(__file__).parent / "digests"
OUTPUT_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


# --- 1. ニュース収集 (Google News RSS) ---

SEARCH_QUERIES = [
    "Claude Anthropic AI",
    "Google Gemini AI",
    "ChatGPT OpenAI",
    "AI monetization business tools 2026",
    "AI 最新ニュース",
    "生成AI ビジネス活用",
]


def _strip_html(text: str) -> str:
    """HTMLタグを除去."""
    return unescape(re.sub(r"<[^>]+>", "", text))


def fetch_google_news_rss(query: str, num: int = 8) -> list[dict]:
    """Google News RSSから検索結果を取得."""
    encoded = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=en&gl=US&ceid=US:en"

    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml_data = resp.read()
    except Exception as e:
        print(f"    RSS取得失敗 ({query}): {e}")
        return []

    root = ET.fromstring(xml_data)
    items = []
    for item in root.findall(".//item")[:num]:
        title = item.findtext("title", "")
        link = item.findtext("link", "")
        desc = _strip_html(item.findtext("description", ""))
        pub_date = item.findtext("pubDate", "")
        items.append({
            "title": title,
            "link": link,
            "description": desc[:300],
            "date": pub_date,
        })
    return items


def fetch_google_news_rss_ja(query: str, num: int = 8) -> list[dict]:
    """日本語Google News RSSから検索結果を取得."""
    encoded = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=ja&gl=JP&ceid=JP:ja"

    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml_data = resp.read()
    except Exception as e:
        print(f"    RSS取得失敗 ({query}): {e}")
        return []

    root = ET.fromstring(xml_data)
    items = []
    for item in root.findall(".//item")[:num]:
        title = item.findtext("title", "")
        link = item.findtext("link", "")
        desc = _strip_html(item.findtext("description", ""))
        pub_date = item.findtext("pubDate", "")
        items.append({
            "title": title,
            "link": link,
            "description": desc[:300],
            "date": pub_date,
        })
    return items


def search_news() -> str:
    """全クエリのニュースを収集してテキストにまとめる."""
    all_results = []

    for query in SEARCH_QUERIES[:4]:  # 英語クエリ
        print(f"    検索: {query}")
        items = fetch_google_news_rss(query)
        section = f"### {query}\n"
        for item in items:
            section += (
                f"- **{item['title']}** ({item['date']})\n"
                f"  {item['description']}\n"
                f"  URL: {item['link']}\n"
            )
        all_results.append(section)

    for query in SEARCH_QUERIES[4:]:  # 日本語クエリ
        print(f"    検索: {query}")
        items = fetch_google_news_rss_ja(query)
        section = f"### {query}\n"
        for item in items:
            section += (
                f"- **{item['title']}** ({item['date']})\n"
                f"  {item['description']}\n"
                f"  URL: {item['link']}\n"
            )
        all_results.append(section)

    return "\n\n".join(all_results)


# --- 2. Claude APIでダイジェスト生成 ---

SYSTEM_PROMPT_PUBLIC = """\
あなたはAI業界専門のニュースキュレーターです。
提供された検索結果を元に、日本語でAIデイリーダイジェストを作成してください。

## 出力フォーマット（Markdown）

# AIデイリーダイジェスト — {date}

## 今日のハイライト
（3行で全体要約）

---

## 1. Claude / Anthropic
（最新ニュース2-4件。日付・内容・意義を簡潔に）

## 2. Google AI / Gemini
（同上）

## 3. ChatGPT / OpenAI
（同上）

## 4. 日本のAI動向
（国内ニュース2-3件）

## 5. AIマネタイズ最前線
（ビジネス活用・収益化の最新トレンド2-3件）

---
Sources:
（使用した情報源のURLリスト）

## ルール
- 検索結果に含まれない情報は書かない
- 各ニュースは日付を明記
- NotebookLMに貼って音声化することを想定し、見出しと要約を明確にする
- 新しいニュースがない場合は正直に「本日の新着情報はありませんでした」と記載
"""


def generate_digest(raw_news: str) -> str:
    """Claude APIで公開用ダイジェストを生成（活用ポイントなし）."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=SYSTEM_PROMPT_PUBLIC.replace("{date}", TODAY),
        messages=[
            {
                "role": "user",
                "content": f"以下の検索結果を元にダイジェストを作成してください:\n\n{raw_news}",
            }
        ],
    )

    return message.content[0].text


# --- 3. Telegram送信 ---

def make_telegram_summary(digest: str) -> str:
    """ニュース要約 + 自分のビジネスへの活用ポイントをTelegram用に生成."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=3000,
        messages=[
            {
                "role": "user",
                "content": (
                    "以下のAIダイジェストを元に、Telegramメッセージを作成してください。\n\n"
                    "## 構成\n"
                    "1. ニュース要約（各セクション要点1-2行）\n"
                    "2. 🎯 ビジネス活用ポイント（以下の事業ごとに具体的アクション提案）:\n"
                    "   - eBay輸出（日本→海外の越境EC）\n"
                    "   - ZINQ（マッチングアプリAIコーチ、LINE Bot、月額¥4,980）\n"
                    "   - Sion（AI占いサロン、霊視鑑定ビジネス）\n"
                    "   - 全般（個人事業全体の戦略）\n\n"
                    "## ルール\n"
                    "- 最大3500文字以内\n"
                    "- 絵文字を使って読みやすく\n"
                    "- 活用ポイントは具体的に（「〜を検討」ではなく「〜をやってみる」レベル）\n"
                    "- 最後に「📄 NotebookLM用の詳細版はGitHubリポジトリのdigestsフォルダへ」と追記\n\n"
                    f"{digest}"
                ),
            }
        ],
    )

    return message.content[0].text


async def send_telegram(text: str) -> None:
    """Telegramにメッセージ送信（4000文字ずつ分割）."""
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    chunks = [text[i : i + 4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=chunk)


# --- 4. メイン処理 ---

def main():
    print(f"[{TODAY}] AI Daily Digest 生成開始...")

    # Step 1: ニュース収集
    print("  検索中...")
    raw_news = search_news()
    print(f"  検索完了: {len(raw_news)} chars")

    if len(raw_news) < 200:
        print("  WARNING: 検索結果が少なすぎます。処理を続行しますが品質に影響する可能性があります。")

    # Step 2: ダイジェスト生成
    print("  ダイジェスト生成中...")
    digest = generate_digest(raw_news)
    print(f"  生成完了: {len(digest)} chars")

    # Step 3: ファイル保存
    output_path = OUTPUT_DIR / f"ai-daily-{TODAY}.md"
    frontmatter = (
        f'---\ndate: "{TODAY}"\ntype: ai-daily-digest\n'
        f'purpose: NotebookLM動画用ソース\n---\n\n'
    )
    output_path.write_text(frontmatter + digest, encoding="utf-8")
    print(f"  保存: {output_path}")

    # Step 4: Telegram送信
    print("  Telegram要約作成中...")
    summary = make_telegram_summary(digest)
    print("  Telegram送信中...")
    asyncio.run(send_telegram(summary))
    print("  送信完了!")

    print(f"[{TODAY}] 完了!")


if __name__ == "__main__":
    main()
