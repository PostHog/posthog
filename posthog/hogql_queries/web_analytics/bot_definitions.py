from dataclasses import dataclass


@dataclass
class BotDefinition:
    name: str  # Display name: "Googlebot", "ChatGPT"
    category: str  # Category: "search_crawler", "llm_crawler"
    traffic_type: str  # Type: "Bot", "AI Agent", "Automation"


# Pattern -> BotDefinition mapping (ordered by specificity)
BOT_DEFINITIONS: dict[str, BotDefinition] = {
    # AI Agents
    "GPTBot": BotDefinition("GPTBot", "llm_crawler", "AI Agent"),
    "OAI-SearchBot": BotDefinition("OpenAI Search", "llm_crawler", "AI Agent"),
    "ChatGPT-User": BotDefinition("ChatGPT", "llm_crawler", "AI Agent"),
    "ClaudeBot": BotDefinition("Claude", "llm_crawler", "AI Agent"),
    "Claude-Web": BotDefinition("Claude Web", "llm_crawler", "AI Agent"),
    "anthropic-ai": BotDefinition("Anthropic", "llm_crawler", "AI Agent"),
    "PerplexityBot": BotDefinition("Perplexity", "llm_crawler", "AI Agent"),
    "Google-Extended": BotDefinition("Google AI", "llm_crawler", "AI Agent"),
    "CCBot": BotDefinition("Common Crawl", "llm_crawler", "AI Agent"),
    "Applebot-Extended": BotDefinition("Apple AI", "llm_crawler", "AI Agent"),
    "cohere-ai": BotDefinition("Cohere", "llm_crawler", "AI Agent"),
    "meta-externalagent": BotDefinition("Meta AI", "llm_crawler", "AI Agent"),
    "Meta-ExternalFetcher": BotDefinition("Meta Fetcher", "llm_crawler", "AI Agent"),
    "Bytespider": BotDefinition("ByteDance", "llm_crawler", "AI Agent"),
    "Diffbot": BotDefinition("Diffbot", "llm_crawler", "AI Agent"),
    "omgili": BotDefinition("Webz.io", "llm_crawler", "AI Agent"),
    "Webzio-Extended": BotDefinition("Webz.io Extended", "llm_crawler", "AI Agent"),
    "Timpibot": BotDefinition("Timpi", "llm_crawler", "AI Agent"),
    # Search Crawlers (Applebot must come after Applebot-Extended above)
    "Applebot": BotDefinition("Applebot", "search_crawler", "Bot"),
    "Amazonbot": BotDefinition("Amazon", "search_crawler", "Bot"),
    "Googlebot": BotDefinition("Googlebot", "search_crawler", "Bot"),
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
    "PetalBot": BotDefinition("Petal", "seo_crawler", "Bot"),
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
