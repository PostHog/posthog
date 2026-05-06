from dataclasses import dataclass


@dataclass
class BotDefinition:
    name: str  # Display name: "Googlebot", "ChatGPT"
    category: str  # Category: "search_crawler", "ai_crawler", "ai_search", "ai_assistant"
    traffic_type: str  # Type: "Bot", "AI Agent", "Automation"
    operator: str  # Operator/company: "Google", "OpenAI", "Anthropic"
    documentation_url: str | None = None  # Operator- or directory-published page describing the bot
    description: str | None = None  # Optional 1-line summary; None until populated case-by-case


# Pattern -> BotDefinition mapping (ordered by specificity)
BOT_DEFINITIONS: dict[str, BotDefinition] = {
    # AI Crawlers (training data collection)
    "GPTBot": BotDefinition(
        "GPTBot", "ai_crawler", "AI Agent", "OpenAI", documentation_url="https://bots.fyi/d/gptbot"
    ),
    "Google-CloudVertexBot": BotDefinition(
        "Google Cloud Vertex",
        "ai_crawler",
        "AI Agent",
        "Google",
        documentation_url="https://bots.fyi/d/google-cloudvertexbot",
    ),
    "Google-Extended": BotDefinition(
        "Google AI", "ai_crawler", "AI Agent", "Google", documentation_url="https://bots.fyi/d/google-extended"
    ),
    "GoogleOther": BotDefinition(
        "GoogleOther", "ai_crawler", "AI Agent", "Google", documentation_url="https://bots.fyi/d/googleother"
    ),
    "Claude-SearchBot": BotDefinition(
        "Claude Search",
        "ai_search",
        "AI Agent",
        "Anthropic",
        documentation_url="https://bots.fyi/d/claude-searchbot",
    ),
    "Claude-User": BotDefinition(
        "Claude User", "ai_assistant", "AI Agent", "Anthropic", documentation_url="https://bots.fyi/d/claude-user"
    ),
    "ClaudeBot": BotDefinition(
        "Claude", "ai_crawler", "AI Agent", "Anthropic", documentation_url="https://bots.fyi/d/claudebot"
    ),
    "Claude-Web": BotDefinition(
        "Claude Web", "ai_crawler", "AI Agent", "Anthropic", documentation_url="https://bots.fyi/d/claudebot"
    ),
    "anthropic-ai": BotDefinition(
        "Anthropic", "ai_crawler", "AI Agent", "Anthropic", documentation_url="https://bots.fyi/d/claudebot"
    ),
    "Perplexity-User": BotDefinition(
        "Perplexity User",
        "ai_assistant",
        "AI Agent",
        "Perplexity",
        documentation_url="https://bots.fyi/d/perplexity-user",
    ),
    "PerplexityBot": BotDefinition(
        "Perplexity", "ai_search", "AI Agent", "Perplexity", documentation_url="https://bots.fyi/d/perplexitybot"
    ),
    "CCBot": BotDefinition(
        "Common Crawl", "ai_crawler", "AI Agent", "Common Crawl", documentation_url="https://bots.fyi/d/ccbot"
    ),
    "meta-externalagent": BotDefinition(
        "Meta AI", "ai_crawler", "AI Agent", "Meta", documentation_url="https://bots.fyi/d/meta-externalagent"
    ),
    "Bytespider": BotDefinition(
        "ByteDance", "ai_crawler", "AI Agent", "ByteDance", documentation_url="https://bots.fyi/d/bytespider"
    ),
    "TikTokSpider": BotDefinition(
        "TikTok AI", "ai_crawler", "AI Agent", "ByteDance", documentation_url="https://bots.fyi/d/tiktokspider"
    ),
    "cohere-ai": BotDefinition(
        "Cohere", "ai_crawler", "AI Agent", "Cohere", documentation_url="https://docs.cohere.com/"
    ),
    "Diffbot": BotDefinition(
        "Diffbot",
        "ai_crawler",
        "AI Agent",
        "Diffbot",
        documentation_url="https://www.diffbot.com/products/automatic/",
    ),
    "omgili": BotDefinition(
        "Webz.io",
        "ai_crawler",
        "AI Agent",
        "Webz.io",
        documentation_url="https://webz.io/blog/web-data/what-is-our-crawler/",
    ),
    "Webzio-Extended": BotDefinition(
        "Webz.io Extended",
        "ai_crawler",
        "AI Agent",
        "Webz.io",
        documentation_url="https://webz.io/blog/web-data/what-is-our-crawler/",
    ),
    "Timpibot": BotDefinition("Timpi", "ai_crawler", "AI Agent", "Timpi", documentation_url="https://www.timpi.io/"),
    "Amazonbot": BotDefinition(
        "Amazon", "ai_crawler", "AI Agent", "Amazon", documentation_url="https://bots.fyi/d/amazonbot"
    ),
    "PetalBot": BotDefinition(
        "Petal", "ai_crawler", "AI Agent", "Huawei", documentation_url="https://bots.fyi/d/petalbot"
    ),
    "Brightbot": BotDefinition(
        "Brightbot", "ai_crawler", "AI Agent", "Bright Data", documentation_url="https://bots.fyi/d/brightbot"
    ),
    # AI Search (search result generation)
    "OAI-SearchBot": BotDefinition(
        "OpenAI Search", "ai_search", "AI Agent", "OpenAI", documentation_url="https://bots.fyi/d/oai-searchbot"
    ),
    "Applebot-Extended": BotDefinition(
        "Apple AI", "ai_search", "AI Agent", "Apple", documentation_url="https://bots.fyi/d/applebot"
    ),
    # AI Assistants (real-time user-facing fetching)
    "ChatGPT-User": BotDefinition(
        "ChatGPT", "ai_assistant", "AI Agent", "OpenAI", documentation_url="https://bots.fyi/d/chatgpt-user"
    ),
    # Lowercase variant first — Meta emits this casing in the wild (matches the bingbot/Bingbot
    # precedent). Both forms map to the same BotDefinition. Removable once we switch to
    # multiMatchAnyIndexCaseInsensitive in the HogQL bot detection function.
    "meta-externalfetcher": BotDefinition(
        "Meta Fetcher",
        "ai_assistant",
        "AI Agent",
        "Meta",
        documentation_url="https://bots.fyi/d/meta-externalfetcher",
    ),
    "Meta-ExternalFetcher": BotDefinition(
        "Meta Fetcher",
        "ai_assistant",
        "AI Agent",
        "Meta",
        documentation_url="https://bots.fyi/d/meta-externalfetcher",
    ),
    "DuckAssistBot": BotDefinition(
        "DuckDuckGo AI",
        "ai_assistant",
        "AI Agent",
        "DuckDuckGo",
        documentation_url="https://bots.fyi/d/duckassistbot",
    ),
    "MistralAI-User": BotDefinition(
        "Mistral AI", "ai_assistant", "AI Agent", "Mistral", documentation_url="https://docs.mistral.ai/"
    ),
    "Manus-User": BotDefinition("Manus", "ai_assistant", "AI Agent", "Manus", documentation_url="https://manus.im/"),
    "Google-NotebookLM": BotDefinition(
        "NotebookLM", "ai_assistant", "AI Agent", "Google", documentation_url="https://notebooklm.google.com/"
    ),
    # PostHog Code clients (Electron desktop, React Native mobile, agent CLI, cloud agent server).
    # Dots are escaped because keys are evaluated as re2 regex by ClickHouse multiMatchAnyIndex.
    r"desktop\.hog\.dev": BotDefinition(
        "PostHog Code Desktop",
        "ai_assistant",
        "AI Agent",
        "PostHog",
        documentation_url="https://posthog.com/code",
    ),
    r"mobile\.hog\.dev": BotDefinition(
        "PostHog Code Mobile",
        "ai_assistant",
        "AI Agent",
        "PostHog",
        documentation_url="https://posthog.com/code",
    ),
    r"agent\.hog\.dev": BotDefinition(
        "PostHog Code Agent",
        "ai_assistant",
        "AI Agent",
        "PostHog",
        documentation_url="https://posthog.com/code",
    ),
    r"cloud\.hog\.dev": BotDefinition(
        "PostHog Code Cloud",
        "ai_assistant",
        "AI Agent",
        "PostHog",
        documentation_url="https://posthog.com/code",
    ),
    # Search Crawlers (Applebot/ avoids matching Applebot-Extended)
    "Applebot/": BotDefinition(
        "Applebot", "ai_search", "AI Agent", "Apple", documentation_url="https://bots.fyi/d/applebot"
    ),
    "Googlebot": BotDefinition(
        "Googlebot", "search_crawler", "Bot", "Google", documentation_url="https://bots.fyi/d/googlebot"
    ),
    "bingbot": BotDefinition(
        "Bingbot", "search_crawler", "Bot", "Microsoft", documentation_url="https://bots.fyi/d/bingbot"
    ),
    "Bingbot": BotDefinition(
        "Bingbot", "search_crawler", "Bot", "Microsoft", documentation_url="https://bots.fyi/d/bingbot"
    ),
    "YandexBot": BotDefinition(
        "Yandex", "search_crawler", "Bot", "Yandex", documentation_url="https://bots.fyi/d/yandexbot"
    ),
    "Baiduspider": BotDefinition(
        "Baidu", "search_crawler", "Bot", "Baidu", documentation_url="https://bots.fyi/d/baiduspider"
    ),
    "DuckDuckBot": BotDefinition(
        "DuckDuckGo", "search_crawler", "Bot", "DuckDuckGo", documentation_url="https://bots.fyi/d/duckduckbot"
    ),
    "Slurp": BotDefinition(
        "Yahoo", "search_crawler", "Bot", "Yahoo", documentation_url="https://bots.fyi/d/yahoo-slurp"
    ),
    "Yeti/": BotDefinition("Naver", "search_crawler", "Bot", "Naver", documentation_url="https://bots.fyi/d/naverbot"),
    # Search Crawlers (Google variants)
    "AdsBot-Google": BotDefinition(
        "Google Ads", "search_crawler", "Bot", "Google", documentation_url="https://bots.fyi/d/google-adsbot"
    ),
    "Google-InspectionTool": BotDefinition(
        "Google Inspection",
        "search_crawler",
        "Bot",
        "Google",
        documentation_url="https://bots.fyi/d/google-inspectiontool",
    ),
    # SEO Tools
    "AhrefsSiteAudit": BotDefinition(
        "Ahrefs Site Audit", "seo_crawler", "Bot", "Ahrefs", documentation_url="https://bots.fyi/d/ahrefssiteaudit"
    ),
    "AhrefsBot": BotDefinition(
        "Ahrefs", "seo_crawler", "Bot", "Ahrefs", documentation_url="https://bots.fyi/d/ahrefsbot"
    ),
    "Barkrowler": BotDefinition(
        "Barkrowler", "seo_crawler", "Bot", "Babbar", documentation_url="https://bots.fyi/d/barkrowler"
    ),
    "SemrushBot": BotDefinition(
        "Semrush", "seo_crawler", "Bot", "Semrush", documentation_url="https://bots.fyi/d/semrush"
    ),
    "SERankingBacklinksBot": BotDefinition(
        "SE Ranking",
        "seo_crawler",
        "Bot",
        "SE Ranking",
        documentation_url="https://bots.fyi/d/seranking-backlinks",
    ),
    "MJ12bot": BotDefinition(
        "Majestic", "seo_crawler", "Bot", "Majestic", documentation_url="https://bots.fyi/d/mj12bot"
    ),
    "DotBot": BotDefinition("Moz", "seo_crawler", "Bot", "Moz", documentation_url="https://bots.fyi/d/dotbot"),
    "Lighthouse": BotDefinition(
        "Lighthouse", "seo_crawler", "Bot", "Google", documentation_url="https://bots.fyi/d/chrome-lighthouse"
    ),
    # Social Crawlers
    "FacebookBot": BotDefinition(
        "Facebook Bot",
        "social_crawler",
        "Bot",
        "Meta",
        documentation_url="https://bots.fyi/d/facebookexternalhit",
    ),
    "facebookexternalhit": BotDefinition(
        "Facebook", "social_crawler", "Bot", "Meta", documentation_url="https://bots.fyi/d/facebookexternalhit"
    ),
    "Twitterbot": BotDefinition(
        "Twitter", "social_crawler", "Bot", "X", documentation_url="https://bots.fyi/d/twitterbot"
    ),
    "LinkedInBot": BotDefinition(
        "LinkedIn", "social_crawler", "Bot", "LinkedIn", documentation_url="https://bots.fyi/d/linkedinbot"
    ),
    "Pinterest": BotDefinition(
        "Pinterest", "social_crawler", "Bot", "Pinterest", documentation_url="https://bots.fyi/d/pinterest-bot"
    ),
    "Slackbot": BotDefinition(
        "Slack", "social_crawler", "Bot", "Salesforce", documentation_url="https://bots.fyi/d/slackbot"
    ),
    "Slack-ImgProxy": BotDefinition(
        "Slack Image Proxy",
        "social_crawler",
        "Bot",
        "Salesforce",
        documentation_url="https://bots.fyi/d/slack-imgproxy",
    ),
    "TelegramBot": BotDefinition(
        "Telegram",
        "social_crawler",
        "Bot",
        "Telegram",
        documentation_url="https://core.telegram.org/bots",
    ),
    "WhatsApp": BotDefinition(
        "WhatsApp",
        "social_crawler",
        "Bot",
        "Meta",
        documentation_url="https://developers.facebook.com/docs/sharing/webmasters/web-crawlers",
    ),
    "GoogleImageProxy": BotDefinition(
        "Google Image Proxy",
        "social_crawler",
        "Bot",
        "Google",
        documentation_url="https://bots.fyi/d/google-image-proxy",
    ),
    "Iframely": BotDefinition(
        "Iframely", "social_crawler", "Bot", "Iframely", documentation_url="https://bots.fyi/d/iframely"
    ),
    # Monitoring
    "Pingdom": BotDefinition(
        "Pingdom", "monitoring", "Bot", "SolarWinds", documentation_url="https://bots.fyi/d/pingdom-bot"
    ),
    "UptimeRobot": BotDefinition(
        "UptimeRobot", "monitoring", "Bot", "UptimeRobot", documentation_url="https://bots.fyi/d/uptime-robot"
    ),
    "Site24x7": BotDefinition("Site24x7", "monitoring", "Bot", "Zoho", documentation_url="https://bots.fyi/d/site24x7"),
    "StatusCake": BotDefinition(
        "StatusCake",
        "monitoring",
        "Bot",
        "StatusCake",
        documentation_url="https://bots.fyi/d/statuscake-uptime",
    ),
    "Datadog": BotDefinition(
        "Datadog",
        "monitoring",
        "Bot",
        "Datadog",
        documentation_url="https://bots.fyi/d/datadog-synthetic-monitoring-robot",
    ),
    # HTTP Clients
    "curl/": BotDefinition("curl", "http_client", "Automation", "curl", documentation_url="https://curl.se/"),
    "Wget": BotDefinition(
        "Wget", "http_client", "Automation", "GNU", documentation_url="https://www.gnu.org/software/wget/"
    ),
    "python-requests": BotDefinition(
        "Python Requests",
        "http_client",
        "Automation",
        "Python",
        documentation_url="https://requests.readthedocs.io/",
    ),
    "axios": BotDefinition("Axios", "http_client", "Automation", "axios", documentation_url="https://axios-http.com/"),
    "node-fetch": BotDefinition(
        "Node Fetch",
        "http_client",
        "Automation",
        "Node.js",
        documentation_url="https://github.com/node-fetch/node-fetch",
    ),
    "Go-http-client": BotDefinition(
        "Go HTTP", "http_client", "Automation", "Go", documentation_url="https://pkg.go.dev/net/http"
    ),
    "okhttp": BotDefinition(
        "OkHttp", "http_client", "Automation", "Square", documentation_url="https://square.github.io/okhttp/"
    ),
    "Apache-HttpClient": BotDefinition(
        "Apache HTTP",
        "http_client",
        "Automation",
        "Apache",
        documentation_url="https://hc.apache.org/httpcomponents-client-5.5.x/",
    ),
    "libwww-perl": BotDefinition(
        "LWP", "http_client", "Automation", "Perl", documentation_url="https://metacpan.org/pod/LWP"
    ),
    "Scrapy": BotDefinition("Scrapy", "http_client", "Automation", "Scrapy", documentation_url="https://scrapy.org/"),
    # Prefetch/Proxy
    "Chrome Privacy Preserving Prefetch Proxy": BotDefinition(
        "Chrome Prefetch Proxy",
        "http_client",
        "Automation",
        "Google",
        documentation_url="https://bots.fyi/d/chrome-privacy-preserving-prefetch-proxy",
    ),
    # Headless Browsers
    "Mozlila/": BotDefinition("Mozlila Typo Bot", "headless_browser", "Automation", "Unknown"),
    "HeadlessChrome": BotDefinition(
        "Headless Chrome",
        "headless_browser",
        "Automation",
        "Google",
        documentation_url="https://developer.chrome.com/blog/headless-chrome",
    ),
    "PhantomJS": BotDefinition(
        "PhantomJS",
        "headless_browser",
        "Automation",
        "PhantomJS",
        documentation_url="https://phantomjs.org/",
    ),
    "Puppeteer": BotDefinition(
        "Puppeteer", "headless_browser", "Automation", "Google", documentation_url="https://pptr.dev/"
    ),
    "Playwright": BotDefinition(
        "Playwright",
        "headless_browser",
        "Automation",
        "Microsoft",
        documentation_url="https://playwright.dev/",
    ),
    "Selenium": BotDefinition(
        "Selenium",
        "headless_browser",
        "Automation",
        "Selenium",
        documentation_url="https://www.selenium.dev/",
    ),
}
