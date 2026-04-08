from dataclasses import dataclass


@dataclass
class BotDefinition:
    name: str  # Display name: "Googlebot", "ChatGPT"
    category: str  # Category: "search_crawler", "ai_crawler", "ai_search", "ai_assistant"
    traffic_type: str  # Type: "Bot", "AI Agent", "Automation"


# Pattern -> BotDefinition mapping (ordered by specificity)
BOT_DEFINITIONS: dict[str, BotDefinition] = {
    # AI Crawlers (training/indexing)
    "GPTBot": BotDefinition("GPTBot", "ai_crawler", "AI Agent"),
    "ClaudeBot": BotDefinition("Claude", "ai_crawler", "AI Agent"),
    "anthropic-ai": BotDefinition("Anthropic", "ai_crawler", "AI Agent"),
    "Google-Extended": BotDefinition("Google AI", "ai_crawler", "AI Agent"),
    "GoogleOther": BotDefinition("GoogleOther", "ai_crawler", "AI Agent"),
    "CCBot": BotDefinition("Common Crawl", "ai_crawler", "AI Agent"),
    "cohere-ai": BotDefinition("Cohere", "ai_crawler", "AI Agent"),
    "meta-externalagent": BotDefinition("Meta AI", "ai_crawler", "AI Agent"),
    "Meta-ExternalFetcher": BotDefinition("Meta Fetcher", "ai_crawler", "AI Agent"),
    "Bytespider": BotDefinition("ByteDance", "ai_crawler", "AI Agent"),
    "TikTokSpider": BotDefinition("TikTok AI", "ai_crawler", "AI Agent"),
    "Diffbot": BotDefinition("Diffbot", "ai_crawler", "AI Agent"),
    "omgili": BotDefinition("Webz.io", "ai_crawler", "AI Agent"),
    "Webzio-Extended": BotDefinition("Webz.io Extended", "ai_crawler", "AI Agent"),
    "Timpibot": BotDefinition("Timpi", "ai_crawler", "AI Agent"),
    "PetalBot": BotDefinition("Petal", "ai_crawler", "AI Agent"),
    "Brightbot": BotDefinition("Brightbot", "ai_crawler", "AI Agent"),
    # AI Search (real-time search augmentation)
    "OAI-SearchBot": BotDefinition("OpenAI Search", "ai_search", "AI Agent"),
    "PerplexityBot": BotDefinition("Perplexity", "ai_search", "AI Agent"),
    "Applebot-Extended": BotDefinition("Apple AI", "ai_search", "AI Agent"),
    # AI Assistants (live user browsing sessions)
    "ChatGPT-User": BotDefinition("ChatGPT", "ai_assistant", "AI Agent"),
    "Claude-User": BotDefinition("Claude User", "ai_assistant", "AI Agent"),
    "Claude-Web": BotDefinition("Claude Web", "ai_assistant", "AI Agent"),
    # Search Crawlers (Applebot/ avoids matching Applebot-Extended)
    "Applebot/": BotDefinition("Applebot", "search_crawler", "Bot"),
    "Amazonbot": BotDefinition("Amazon", "search_crawler", "Bot"),
    "Googlebot": BotDefinition("Googlebot", "search_crawler", "Bot"),
    "bingbot": BotDefinition("Bingbot", "search_crawler", "Bot"),
    "Bingbot": BotDefinition("Bingbot", "search_crawler", "Bot"),
    "YandexBot": BotDefinition("Yandex", "search_crawler", "Bot"),
    "Baiduspider": BotDefinition("Baidu", "search_crawler", "Bot"),
    "DuckDuckBot": BotDefinition("DuckDuckGo", "search_crawler", "Bot"),
    "Slurp": BotDefinition("Yahoo", "search_crawler", "Bot"),
    # SEO Tools
    "AhrefsBot": BotDefinition("Ahrefs", "seo_crawler", "Bot"),
    "SemrushBot": BotDefinition("Semrush", "seo_crawler", "Bot"),
    "MJ12bot": BotDefinition("Majestic", "seo_crawler", "Bot"),
    "DotBot": BotDefinition("Moz", "seo_crawler", "Bot"),
    # Social Crawlers
    "FacebookBot": BotDefinition("Facebook Bot", "social_crawler", "Bot"),
    "facebookexternalhit": BotDefinition("Facebook", "social_crawler", "Bot"),
    "Twitterbot": BotDefinition("Twitter", "social_crawler", "Bot"),
    "LinkedInBot": BotDefinition("LinkedIn", "social_crawler", "Bot"),
    "Pinterest": BotDefinition("Pinterest", "social_crawler", "Bot"),
    "Slackbot": BotDefinition("Slack", "social_crawler", "Bot"),
    "TelegramBot": BotDefinition("Telegram", "social_crawler", "Bot"),
    "WhatsApp": BotDefinition("WhatsApp", "social_crawler", "Bot"),
    # Monitoring
    "Pingdom": BotDefinition("Pingdom", "monitoring", "Bot"),
    "UptimeRobot": BotDefinition("UptimeRobot", "monitoring", "Bot"),
    "Site24x7": BotDefinition("Site24x7", "monitoring", "Bot"),
    "StatusCake": BotDefinition("StatusCake", "monitoring", "Bot"),
    "Datadog": BotDefinition("Datadog", "monitoring", "Bot"),
    # HTTP Clients
    "curl/": BotDefinition("curl", "http_client", "Automation"),
    "Wget": BotDefinition("Wget", "http_client", "Automation"),
    "python-requests": BotDefinition("Python Requests", "http_client", "Automation"),
    "axios": BotDefinition("Axios", "http_client", "Automation"),
    "node-fetch": BotDefinition("Node Fetch", "http_client", "Automation"),
    "Go-http-client": BotDefinition("Go HTTP", "http_client", "Automation"),
    "okhttp": BotDefinition("OkHttp", "http_client", "Automation"),
    "Apache-HttpClient": BotDefinition("Apache HTTP", "http_client", "Automation"),
    "libwww-perl": BotDefinition("LWP", "http_client", "Automation"),
    "Scrapy": BotDefinition("Scrapy", "http_client", "Automation"),
    # Headless Browsers
    "HeadlessChrome": BotDefinition("Headless Chrome", "headless_browser", "Automation"),
    "PhantomJS": BotDefinition("PhantomJS", "headless_browser", "Automation"),
    "Puppeteer": BotDefinition("Puppeteer", "headless_browser", "Automation"),
    "Playwright": BotDefinition("Playwright", "headless_browser", "Automation"),
    "Selenium": BotDefinition("Selenium", "headless_browser", "Automation"),
}
