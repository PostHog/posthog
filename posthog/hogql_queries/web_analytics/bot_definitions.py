from dataclasses import dataclass


@dataclass
class BotDefinition:
    name: str  # Display name: "Googlebot", "ChatGPT"
    category: str  # Category: "search_crawler", "ai_crawler", "ai_search", "ai_assistant"
    traffic_type: str  # Type: "Bot", "AI Agent", "Automation"
    operator: str  # Operator/company: "Google", "OpenAI", "Anthropic"


# Pattern -> BotDefinition mapping (ordered by specificity)
BOT_DEFINITIONS: dict[str, BotDefinition] = {
    # AI Crawlers (training data collection)
    "GPTBot": BotDefinition("GPTBot", "ai_crawler", "AI Agent", "OpenAI"),
    "Google-CloudVertexBot": BotDefinition("Google Cloud Vertex", "ai_crawler", "AI Agent", "Google"),
    "Google-Extended": BotDefinition("Google AI", "ai_crawler", "AI Agent", "Google"),
    "GoogleOther": BotDefinition("GoogleOther", "ai_crawler", "AI Agent", "Google"),
    "Claude-SearchBot": BotDefinition("Claude Search", "ai_search", "AI Agent", "Anthropic"),
    "Claude-User": BotDefinition("Claude User", "ai_assistant", "AI Agent", "Anthropic"),
    "ClaudeBot": BotDefinition("Claude", "ai_crawler", "AI Agent", "Anthropic"),
    "Claude-Web": BotDefinition("Claude Web", "ai_crawler", "AI Agent", "Anthropic"),
    "anthropic-ai": BotDefinition("Anthropic", "ai_crawler", "AI Agent", "Anthropic"),
    "Perplexity-User": BotDefinition("Perplexity User", "ai_assistant", "AI Agent", "Perplexity"),
    "PerplexityBot": BotDefinition("Perplexity", "ai_search", "AI Agent", "Perplexity"),
    "CCBot": BotDefinition("Common Crawl", "ai_crawler", "AI Agent", "Common Crawl"),
    "meta-externalagent": BotDefinition("Meta AI", "ai_crawler", "AI Agent", "Meta"),
    "Bytespider": BotDefinition("ByteDance", "ai_crawler", "AI Agent", "ByteDance"),
    "TikTokSpider": BotDefinition("TikTok AI", "ai_crawler", "AI Agent", "ByteDance"),
    "cohere-ai": BotDefinition("Cohere", "ai_crawler", "AI Agent", "Cohere"),
    "Diffbot": BotDefinition("Diffbot", "ai_crawler", "AI Agent", "Diffbot"),
    "omgili": BotDefinition("Webz.io", "ai_crawler", "AI Agent", "Webz.io"),
    "Webzio-Extended": BotDefinition("Webz.io Extended", "ai_crawler", "AI Agent", "Webz.io"),
    "Timpibot": BotDefinition("Timpi", "ai_crawler", "AI Agent", "Timpi"),
    "Amazonbot": BotDefinition("Amazon", "ai_crawler", "AI Agent", "Amazon"),
    "PetalBot": BotDefinition("Petal", "ai_crawler", "AI Agent", "Huawei"),
    "Brightbot": BotDefinition("Brightbot", "ai_crawler", "AI Agent", "Bright Data"),
    # AI Search (search result generation)
    "OAI-SearchBot": BotDefinition("OpenAI Search", "ai_search", "AI Agent", "OpenAI"),
    "Applebot-Extended": BotDefinition("Apple AI", "ai_search", "AI Agent", "Apple"),
    # AI Assistants (real-time user-facing fetching)
    "ChatGPT-User": BotDefinition("ChatGPT", "ai_assistant", "AI Agent", "OpenAI"),
    "Meta-ExternalFetcher": BotDefinition("Meta Fetcher", "ai_assistant", "AI Agent", "Meta"),
    "DuckAssistBot": BotDefinition("DuckDuckGo AI", "ai_assistant", "AI Agent", "DuckDuckGo"),
    "MistralAI-User": BotDefinition("Mistral AI", "ai_assistant", "AI Agent", "Mistral"),
    "Manus-User": BotDefinition("Manus", "ai_assistant", "AI Agent", "Manus"),
    "Google-NotebookLM": BotDefinition("NotebookLM", "ai_assistant", "AI Agent", "Google"),
    # Search Crawlers (Applebot/ avoids matching Applebot-Extended)
    "Applebot/": BotDefinition("Applebot", "ai_search", "AI Agent", "Apple"),
    "Googlebot": BotDefinition("Googlebot", "search_crawler", "Bot", "Google"),
    "bingbot": BotDefinition("Bingbot", "search_crawler", "Bot", "Microsoft"),
    "Bingbot": BotDefinition("Bingbot", "search_crawler", "Bot", "Microsoft"),
    "YandexBot": BotDefinition("Yandex", "search_crawler", "Bot", "Yandex"),
    "Baiduspider": BotDefinition("Baidu", "search_crawler", "Bot", "Baidu"),
    "DuckDuckBot": BotDefinition("DuckDuckGo", "search_crawler", "Bot", "DuckDuckGo"),
    "Slurp": BotDefinition("Yahoo", "search_crawler", "Bot", "Yahoo"),
    # Search Crawlers (Google variants)
    "AdsBot-Google": BotDefinition("Google Ads", "search_crawler", "Bot", "Google"),
    "Google-InspectionTool": BotDefinition("Google Inspection", "search_crawler", "Bot", "Google"),
    # SEO Tools
    "AhrefsSiteAudit": BotDefinition("Ahrefs Site Audit", "seo_crawler", "Bot", "Ahrefs"),
    "AhrefsBot": BotDefinition("Ahrefs", "seo_crawler", "Bot", "Ahrefs"),
    "Barkrowler": BotDefinition("Barkrowler", "seo_crawler", "Bot", "Babbar"),
    "SemrushBot": BotDefinition("Semrush", "seo_crawler", "Bot", "Semrush"),
    "MJ12bot": BotDefinition("Majestic", "seo_crawler", "Bot", "Majestic"),
    "DotBot": BotDefinition("Moz", "seo_crawler", "Bot", "Moz"),
    "Lighthouse": BotDefinition("Lighthouse", "seo_crawler", "Bot", "Google"),
    # Social Crawlers
    "FacebookBot": BotDefinition("Facebook Bot", "social_crawler", "Bot", "Meta"),
    "facebookexternalhit": BotDefinition("Facebook", "social_crawler", "Bot", "Meta"),
    "Twitterbot": BotDefinition("Twitter", "social_crawler", "Bot", "X"),
    "LinkedInBot": BotDefinition("LinkedIn", "social_crawler", "Bot", "LinkedIn"),
    "Pinterest": BotDefinition("Pinterest", "social_crawler", "Bot", "Pinterest"),
    "Slackbot": BotDefinition("Slack", "social_crawler", "Bot", "Salesforce"),
    "Slack-ImgProxy": BotDefinition("Slack Image Proxy", "social_crawler", "Bot", "Salesforce"),
    "TelegramBot": BotDefinition("Telegram", "social_crawler", "Bot", "Telegram"),
    "WhatsApp": BotDefinition("WhatsApp", "social_crawler", "Bot", "Meta"),
    # Monitoring
    "Pingdom": BotDefinition("Pingdom", "monitoring", "Bot", "SolarWinds"),
    "UptimeRobot": BotDefinition("UptimeRobot", "monitoring", "Bot", "UptimeRobot"),
    "Site24x7": BotDefinition("Site24x7", "monitoring", "Bot", "Zoho"),
    "StatusCake": BotDefinition("StatusCake", "monitoring", "Bot", "StatusCake"),
    "Datadog": BotDefinition("Datadog", "monitoring", "Bot", "Datadog"),
    # HTTP Clients
    "curl/": BotDefinition("curl", "http_client", "Automation", "curl"),
    "Wget": BotDefinition("Wget", "http_client", "Automation", "GNU"),
    "python-requests": BotDefinition("Python Requests", "http_client", "Automation", "Python"),
    "axios": BotDefinition("Axios", "http_client", "Automation", "axios"),
    "node-fetch": BotDefinition("Node Fetch", "http_client", "Automation", "Node.js"),
    "Go-http-client": BotDefinition("Go HTTP", "http_client", "Automation", "Go"),
    "okhttp": BotDefinition("OkHttp", "http_client", "Automation", "Square"),
    "Apache-HttpClient": BotDefinition("Apache HTTP", "http_client", "Automation", "Apache"),
    "libwww-perl": BotDefinition("LWP", "http_client", "Automation", "Perl"),
    "Scrapy": BotDefinition("Scrapy", "http_client", "Automation", "Scrapy"),
    # Prefetch/Proxy
    "Chrome Privacy Preserving Prefetch Proxy": BotDefinition(
        "Chrome Prefetch Proxy", "http_client", "Automation", "Google"
    ),
    # Headless Browsers
    "Mozlila/": BotDefinition("Mozlila Typo Bot", "headless_browser", "Automation", "Unknown"),
    "HeadlessChrome": BotDefinition("Headless Chrome", "headless_browser", "Automation", "Google"),
    "PhantomJS": BotDefinition("PhantomJS", "headless_browser", "Automation", "PhantomJS"),
    "Puppeteer": BotDefinition("Puppeteer", "headless_browser", "Automation", "Google"),
    "Playwright": BotDefinition("Playwright", "headless_browser", "Automation", "Microsoft"),
    "Selenium": BotDefinition("Selenium", "headless_browser", "Automation", "Selenium"),
}
