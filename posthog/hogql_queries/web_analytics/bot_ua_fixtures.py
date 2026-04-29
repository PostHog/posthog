"""
Real-world bot and browser user agent strings for testing and demo data generation.

Organized by traffic category. Used by:
- posthog/hogql/functions/test/test_traffic_type_real_ua.py (test coverage)
- posthog/management/commands/generate_bot_demo_data.py (demo data)
"""

BOT_USER_AGENTS: dict[str, list[str]] = {
    "ai_crawler": [
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; GPTBot/1.2; +https://openai.com/gptbot",
        "Mozilla/5.0 (compatible; Google-CloudVertexBot/1.0; +https://developers.google.com/search/docs/crawling-indexing/google-cloud-vertex-bot)",
        "Mozilla/5.0 (compatible; Google-Extended; +https://developers.google.com/search/docs/crawling-indexing/google-extended)",
        "Mozilla/5.0 (compatible; GoogleOther; +https://developers.google.com/search/docs/crawling-indexing/googleother)",
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; ClaudeBot/1.0; +https://anthropic.com",
        "Claude-Web/1.0 (https://anthropic.com)",
        "anthropic-ai (https://anthropic.com)",
        "CCBot/2.0 (https://commoncrawl.org/faq/)",
        "meta-externalagent/1.1",
        "Bytespider",
        "Mozilla/5.0 (compatible; TikTokSpider; +https://www.tiktok.com)",
        "cohere-ai",
        "Diffbot/0.1 (+http://www.diffbot.com)",
        "omgili/0.5 +http://omgili.com",
        "Webzio-Extended/1.0 (+https://webz.io)",
        "Mozilla/5.0 (compatible; Timpibot/0.9; +https://www.timpi.io)",
        "Mozilla/5.0 (compatible; Amazonbot/0.1; +https://developer.amazon.com/support/amazonbot)",
        "Mozilla/5.0 (compatible; PetalBot; +https://webmaster.petalsearch.com/site/petalbot)",
        "Mozilla/5.0 (compatible; Brightbot/1.0; +https://brightdata.com)",
    ],
    "ai_search": [
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot",
        "Mozilla/5.0 (compatible; Claude-SearchBot/1.0; +https://anthropic.com/searchbot)",
        "Mozilla/5.0 (compatible; PerplexityBot/1.0; +https://perplexity.ai/bot)",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15 Applebot-Extended/0.1",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15 Applebot/0.1",
    ],
    "ai_assistant": [
        "Mozilla/5.0 (compatible; ChatGPT-User/1.0; +https://openai.com/bot)",
        "Mozilla/5.0 (compatible; Claude-User/1.0; +https://anthropic.com/claude-user)",
        "Mozilla/5.0 (compatible; Perplexity-User/1.0; +https://perplexity.ai/perplexity-user)",
        "Meta-ExternalFetcher/1.0 (+https://developers.facebook.com/docs/sharing/webmasters/crawler)",
        "meta-externalfetcher/1.1 (+https://developers.facebook.com/docs/sharing/webmasters/crawler)",
        "Mozilla/5.0 (compatible; DuckAssistBot/1.0; +https://duckduckgo.com/duckassistbot)",
        "Mozilla/5.0 (compatible; MistralAI-User/1.0; +https://mistral.ai/mistralai-user)",
        "Mozilla/5.0 (compatible; Manus-User/1.0; +https://manus.im/bot)",
        "Mozilla/5.0 (compatible; Google-NotebookLM/1.0; +https://notebooklm.google)",
    ],
    "search_crawler": [
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.7680.177 Mobile Safari/537.36 (compatible; AdsBot-Google-Mobile; +http://www.google.com/mobile/adsbot.html)",
        "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.224 Mobile Safari/537.36 (compatible; Google-InspectionTool/1.0)",
        "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Bingbot/2.0; +http://www.bing.com/Bingbot.htm) Chrome/116.0.0.0 Safari/537.36",
        "Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)",
        "Mozilla/5.0 (compatible; Baiduspider/2.0; +http://www.baidu.com/search/spider.html)",
        "DuckDuckBot/1.0; (+http://duckduckgo.com/duckduckbot.html)",
        "Mozilla/5.0 (compatible; Yahoo! Slurp; http://help.yahoo.com/help/us/ysearch/slurp)",
    ],
    "seo_crawler": [
        "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.5359.128 Mobile Safari/537.36 (compatible; AhrefsSiteAudit/6.1; +http://ahrefs.com/robot/site-audit)",
        "Mozilla/5.0 (compatible; AhrefsBot/7.0; +http://ahrefs.com/robot/)",
        "Mozilla/5.0 (compatible; Barkrowler/0.9; +https://babbar.tech/crawler)",
        "Mozilla/5.0 (compatible; SemrushBot/7~bl; +http://www.semrush.com/bot.html)",
        "Mozilla/5.0 (compatible; MJ12bot/v1.4.8; http://mj12bot.com/)",
        "Mozilla/5.0 (compatible; DotBot/1.2; +https://opensiteexplorer.org/dotbot)",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Chrome-Lighthouse",
    ],
    "social_crawler": [
        "Mozilla/5.0 (compatible; FacebookBot/1.0; +https://developers.facebook.com/docs/sharing/webmasters/crawler)",
        "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "Twitterbot/1.0",
        "LinkedInBot/1.0 (compatible; Mozilla/5.0; Apache-HttpClient +http://www.linkedin.com)",
        "Pinterest/0.2 (+http://www.pinterest.com/)",
        "Slackbot-LinkExpanding 1.0 (+https://api.slack.com/robots)",
        "Slack-ImgProxy (+https://api.slack.com/robots)",
        "TelegramBot (like TwitterBot)",
        "WhatsApp/2.23.2.79 A",
    ],
    "monitoring": [
        "Pingdom.com_bot_version_1.4_(http://www.pingdom.com/)",
        "Mozilla/5.0 (compatible; UptimeRobot/2.0; http://www.uptimerobot.com/)",
        "Site24x7 (https://www.site24x7.com)",
        "Mozilla/5.0 (compatible; StatusCake)",
        "Datadog/Synthetics",
    ],
    "http_client": [
        "Chrome Privacy Preserving Prefetch Proxy",
        "curl/7.88.1",
        "curl/8.1.2",
        "Wget/1.21.3",
        "python-requests/2.31.0",
        "axios/1.4.0",
        "node-fetch/3.3.1",
        "Go-http-client/1.1",
        # Java/17.0.1 intentionally excluded — no matching BOT_DEFINITIONS pattern.
        # If Java detection is added, move it here.
        "okhttp/4.10.0",
        "Apache-HttpClient/4.5.14 (Java/17.0.1)",
        "libwww-perl/6.67",
        "Scrapy/2.9.0 (+https://scrapy.org)",
    ],
    "headless_browser": [
        "Mozlila/5.0 (Linux; Android 7.0; SM-G892A Bulid/NRD90M; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/60.0.3112.107 Moblie Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/114.0.5735.198 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) PhantomJS/2.1.1 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36 Puppeteer",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36 Playwright",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36 Selenium",
    ],
    "regular_browser": [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    ],
}

# Category -> expected traffic_type mapping
CATEGORY_TO_TRAFFIC_TYPE: dict[str, str] = {
    "ai_crawler": "AI Agent",
    "ai_search": "AI Agent",
    "ai_assistant": "AI Agent",
    "search_crawler": "Bot",
    "seo_crawler": "Bot",
    "social_crawler": "Bot",
    "monitoring": "Bot",
    "http_client": "Automation",
    "headless_browser": "Automation",
    "regular_browser": "Regular",
}

# Category -> expected traffic_category mapping (the $virt_traffic_category value)
CATEGORY_TO_TRAFFIC_CATEGORY: dict[str, str] = {
    "ai_crawler": "ai_crawler",
    "ai_search": "ai_search",
    "ai_assistant": "ai_assistant",
    "search_crawler": "search_crawler",
    "seo_crawler": "seo_crawler",
    "social_crawler": "social_crawler",
    "monitoring": "monitoring",
    "http_client": "http_client",
    "headless_browser": "headless_browser",
    "regular_browser": "regular",
}
