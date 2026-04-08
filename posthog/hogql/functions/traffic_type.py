"""
Traffic type classification functions for HogQL.

EXPERIMENTAL: These functions are prefixed with __preview_ to indicate they are
experimental and may change without notice. The patterns and return values may
be adjusted as we gather more data on real-world traffic classification accuracy.

These are implemented as HogQL functions (rather than hardcoded in specific query
runners) to provide maximum flexibility during development. This allows usage in:
- SQL editor for ad-hoc analysis and exploration
- HogQLQuery runner for custom dashboards and insights
- Trends and other query runners when filtering/grouping by traffic type
- Any future features that leverage HogQL expressions
"""

from dataclasses import dataclass

from posthog.hogql import ast


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
    # Search Crawlers (Applebot/ avoids matching Applebot-Extended)
    "Applebot/": BotDefinition("Applebot", "ai_search", "AI Agent", "Apple"),
    "Googlebot": BotDefinition("Googlebot", "search_crawler", "Bot", "Google"),
    "bingbot": BotDefinition("Bingbot", "search_crawler", "Bot", "Microsoft"),
    "Bingbot": BotDefinition("Bingbot", "search_crawler", "Bot", "Microsoft"),
    "YandexBot": BotDefinition("Yandex", "search_crawler", "Bot", "Yandex"),
    "Baiduspider": BotDefinition("Baidu", "search_crawler", "Bot", "Baidu"),
    "DuckDuckBot": BotDefinition("DuckDuckGo", "search_crawler", "Bot", "DuckDuckGo"),
    "Slurp": BotDefinition("Yahoo", "search_crawler", "Bot", "Yahoo"),
    # SEO Tools
    "AhrefsBot": BotDefinition("Ahrefs", "seo_crawler", "Bot", "Ahrefs"),
    "SemrushBot": BotDefinition("Semrush", "seo_crawler", "Bot", "Semrush"),
    "MJ12bot": BotDefinition("Majestic", "seo_crawler", "Bot", "Majestic"),
    "DotBot": BotDefinition("Moz", "seo_crawler", "Bot", "Moz"),
    # Social Crawlers
    "FacebookBot": BotDefinition("Facebook Bot", "social_crawler", "Bot", "Meta"),
    "facebookexternalhit": BotDefinition("Facebook", "social_crawler", "Bot", "Meta"),
    "Twitterbot": BotDefinition("Twitter", "social_crawler", "Bot", "X"),
    "LinkedInBot": BotDefinition("LinkedIn", "social_crawler", "Bot", "LinkedIn"),
    "Pinterest": BotDefinition("Pinterest", "social_crawler", "Bot", "Pinterest"),
    "Slackbot": BotDefinition("Slack", "social_crawler", "Bot", "Salesforce"),
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
    # Headless Browsers
    "HeadlessChrome": BotDefinition("Headless Chrome", "headless_browser", "Automation", "Google"),
    "PhantomJS": BotDefinition("PhantomJS", "headless_browser", "Automation", "PhantomJS"),
    "Puppeteer": BotDefinition("Puppeteer", "headless_browser", "Automation", "Google"),
    "Playwright": BotDefinition("Playwright", "headless_browser", "Automation", "Microsoft"),
    "Selenium": BotDefinition("Selenium", "headless_browser", "Automation", "Selenium"),
}


def _build_bot_array_lookup(
    user_agent_expr: ast.Expr,
    attr: str,  # "name", "category", or "traffic_type"
    default: str = "",
    empty_ua_value: str = "",
) -> ast.Expr:
    """Build a multiMatchAnyIndex + array lookup expression for efficient bot detection.

    Uses multiMatchAnyIndex which evaluates the user_agent expression once and checks
    all patterns, then uses array indexing to get the corresponding label.

    NULL user agents are coalesced to empty string so they match the ^$ pattern
    and get classified as empty_ua_value instead of falling through to default.
    """
    # Coalesce NULL to empty string so NULL user agents match the ^$ pattern
    safe_user_agent = ast.Call(name="ifNull", args=[user_agent_expr, ast.Constant(value="")])

    # Build patterns array (all bot patterns + empty UA pattern)
    patterns = [*BOT_DEFINITIONS.keys(), "^$"]
    patterns_array = ast.Array(exprs=[ast.Constant(value=p) for p in patterns])

    # Build labels array (corresponding labels + empty UA label)
    labels = [getattr(bot_def, attr) for bot_def in BOT_DEFINITIONS.values()]
    labels.append(empty_ua_value)
    labels_array = ast.Array(exprs=[ast.Constant(value=label) for label in labels])

    # multiMatchAnyIndex(user_agent, patterns) -> returns 0 if no match, else 1-based index
    index_call = ast.Call(name="multiMatchAnyIndex", args=[safe_user_agent, patterns_array])

    # labels[index] - array access (1-based in ClickHouse)
    label_lookup = ast.ArrayAccess(array=labels_array, property=index_call, nullish=False)

    # if(index = 0, default, labels[index])
    return ast.Call(
        name="if",
        args=[
            ast.CompareOperation(op=ast.CompareOperationOp.Eq, left=index_call, right=ast.Constant(value=0)),
            ast.Constant(value=default),
            label_lookup,
        ],
    )


def get_bot_name(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: __preview_getBotName(user_agent)

    EXPERIMENTAL: This function may change without notice.

    Returns bot name: "Googlebot", "ChatGPT", etc. Empty string for regular traffic.
    """
    return _build_bot_array_lookup(args[0], "name", default="", empty_ua_value="")


def get_traffic_type(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: __preview_getTrafficType(user_agent)

    EXPERIMENTAL: This function may change without notice.

    Returns one of: 'AI Agent', 'Bot', 'Automation', 'Regular'
    """
    return _build_bot_array_lookup(args[0], "traffic_type", default="Regular", empty_ua_value="Automation")


def get_traffic_category(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: __preview_getTrafficCategory(user_agent)

    EXPERIMENTAL: This function may change without notice.

    Returns subcategory: 'ai_crawler', 'ai_search', 'ai_assistant', 'search_crawler', 'seo_crawler', etc.
    For regular traffic, returns 'regular'.
    """
    return _build_bot_array_lookup(args[0], "category", default="regular", empty_ua_value="no_user_agent")


def is_bot(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: __preview_isBot(user_agent)

    EXPERIMENTAL: This function may change without notice.

    Returns true if the user agent matches bot/automation patterns, false otherwise.
    NULL user agents are treated as bots (empty UA is considered automation).

    Uses multiMatchAnyIndex for efficient single-pass matching (same as get_traffic_type etc.).
    """
    user_agent_expr = args[0]

    safe_user_agent = ast.Call(name="ifNull", args=[user_agent_expr, ast.Constant(value="")])

    patterns = [*BOT_DEFINITIONS.keys(), "^$"]
    patterns_array = ast.Array(exprs=[ast.Constant(value=p) for p in patterns])

    index_call = ast.Call(name="multiMatchAnyIndex", args=[safe_user_agent, patterns_array])

    return ast.CompareOperation(
        op=ast.CompareOperationOp.NotEq,
        left=index_call,
        right=ast.Constant(value=0),
    )


def get_bot_type(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: __preview_getBotType(user_agent)

    EXPERIMENTAL: This function may change without notice.

    Returns the bot category or empty string for regular traffic.
    Categories: 'ai_crawler', 'ai_search', 'ai_assistant', 'search_crawler', 'seo_crawler',
                'social_crawler', 'monitoring', 'http_client', 'headless_browser', 'no_user_agent', ''
    """
    return _build_bot_array_lookup(args[0], "category", default="", empty_ua_value="no_user_agent")
