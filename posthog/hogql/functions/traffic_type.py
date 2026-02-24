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


def _build_bot_multiif(
    user_agent_expr: ast.Expr,
    attr: str,  # "name", "category", or "traffic_type"
    default: str = "",
) -> ast.Expr:
    """Build a multiIf expression that looks up bot data by pattern match."""
    args: list[ast.Expr] = []

    for pattern, bot_def in BOT_DEFINITIONS.items():
        args.append(ast.Call(name="match", args=[user_agent_expr, ast.Constant(value=pattern)]))
        args.append(ast.Constant(value=getattr(bot_def, attr)))

    # Empty user agent
    args.append(ast.Call(name="match", args=[user_agent_expr, ast.Constant(value="^$")]))
    if attr == "category":
        args.append(ast.Constant(value="no_user_agent"))
    elif attr == "traffic_type":
        args.append(ast.Constant(value="Automation"))
    else:
        args.append(ast.Constant(value=default))

    # Default
    args.append(ast.Constant(value=default))

    return ast.Call(name="multiIf", args=args)


def get_bot_name(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: __preview_getBotName(user_agent)

    EXPERIMENTAL: This function may change without notice.

    Returns bot name: "Googlebot", "ChatGPT", etc. Empty string for regular traffic.
    """
    return _build_bot_multiif(args[0], "name", default="")


def get_traffic_type(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: __preview_getTrafficType(user_agent)

    EXPERIMENTAL: This function may change without notice.

    Returns one of: 'AI Agent', 'Bot', 'Automation', 'Regular'
    """
    return _build_bot_multiif(args[0], "traffic_type", default="Regular")


def get_traffic_category(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: __preview_getTrafficCategory(user_agent)

    EXPERIMENTAL: This function may change without notice.

    Returns subcategory: 'llm_crawler', 'search_crawler', 'seo_crawler', etc.
    For regular traffic, returns 'regular'.
    """
    return _build_bot_multiif(args[0], "category", default="regular")


def is_bot(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: __preview_isBot(user_agent)

    EXPERIMENTAL: This function may change without notice.

    Returns true if the user agent matches bot/automation patterns, false otherwise.
    """
    user_agent_expr = args[0]

    # Build OR expression from all patterns
    match_exprs: list[ast.Expr] = []
    for pattern in BOT_DEFINITIONS.keys():
        match_exprs.append(ast.Call(name="match", args=[user_agent_expr, ast.Constant(value=pattern)]))

    # Empty user agent
    match_exprs.append(ast.Call(name="match", args=[user_agent_expr, ast.Constant(value="^$")]))

    return ast.Or(exprs=match_exprs)


def get_bot_type(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: __preview_getBotType(user_agent)

    EXPERIMENTAL: This function may change without notice.

    Returns the bot category or empty string for regular traffic.
    Categories: 'llm_crawler', 'search_crawler', 'seo_crawler', 'social_crawler',
                'monitoring', 'http_client', 'headless_browser', 'no_user_agent', ''
    """
    return _build_bot_multiif(args[0], "category", default="")
