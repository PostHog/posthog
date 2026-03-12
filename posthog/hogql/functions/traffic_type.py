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
    category: str  # Category: "search_crawler", "llm_crawler"
    traffic_type: str  # Type: "Bot", "AI Agent", "Automation"


# Pattern -> BotDefinition mapping (ordered by specificity)
BOT_DEFINITIONS: dict[str, BotDefinition] = {
    # AI Agents
    "GPTBot": BotDefinition("GPTBot", "llm_crawler", "AI Agent"),
    "ChatGPT-User": BotDefinition("ChatGPT", "llm_crawler", "AI Agent"),
    "ClaudeBot": BotDefinition("Claude", "llm_crawler", "AI Agent"),
    "anthropic-ai": BotDefinition("Anthropic", "llm_crawler", "AI Agent"),
    "PerplexityBot": BotDefinition("Perplexity", "llm_crawler", "AI Agent"),
    "Google-Extended": BotDefinition("Google AI", "llm_crawler", "AI Agent"),
    "CCBot": BotDefinition("Common Crawl", "llm_crawler", "AI Agent"),
    "Applebot-Extended": BotDefinition("Apple AI", "llm_crawler", "AI Agent"),
    "cohere-ai": BotDefinition("Cohere", "llm_crawler", "AI Agent"),
    "meta-externalagent": BotDefinition("Meta AI", "llm_crawler", "AI Agent"),
    "Bytespider": BotDefinition("ByteDance", "llm_crawler", "AI Agent"),
    # Search Crawlers
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

    Returns subcategory: 'llm_crawler', 'search_crawler', 'seo_crawler', etc.
    For regular traffic, returns 'regular'.
    """
    return _build_bot_array_lookup(args[0], "category", default="regular", empty_ua_value="no_user_agent")


def is_bot(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: __preview_isBot(user_agent)

    EXPERIMENTAL: This function may change without notice.

    Returns true if the user agent matches bot/automation patterns, false otherwise.
    NULL user agents are treated as bots (empty UA is considered automation).
    """
    user_agent_expr = args[0]

    # Coalesce NULL to empty string so NULL user agents match the ^$ pattern
    safe_user_agent = ast.Call(name="ifNull", args=[user_agent_expr, ast.Constant(value="")])

    # Build OR expression from all patterns
    match_exprs: list[ast.Expr] = []
    for pattern in BOT_DEFINITIONS.keys():
        match_exprs.append(ast.Call(name="match", args=[safe_user_agent, ast.Constant(value=pattern)]))

    # Empty user agent (also matches NULL after coalescing)
    match_exprs.append(ast.Call(name="match", args=[safe_user_agent, ast.Constant(value="^$")]))

    return ast.Or(exprs=match_exprs)


def get_bot_type(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: __preview_getBotType(user_agent)

    EXPERIMENTAL: This function may change without notice.

    Returns the bot category or empty string for regular traffic.
    Categories: 'llm_crawler', 'search_crawler', 'seo_crawler', 'social_crawler',
                'monitoring', 'http_client', 'headless_browser', 'no_user_agent', ''
    """
    return _build_bot_array_lookup(args[0], "category", default="", empty_ua_value="no_user_agent")
