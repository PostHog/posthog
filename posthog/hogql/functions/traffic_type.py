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

from posthog.hogql import ast

# Bot/automation user agent patterns
AI_AGENT_PATTERNS = (
    "GPTBot|ChatGPT-User|Claude|anthropic-ai|PerplexityBot|Google-Extended|"
    "CCBot|Applebot-Extended|cohere-ai|meta-externalagent|Bytespider"
)
SEARCH_BOT_PATTERNS = "Googlebot|Bingbot|Yandex|Baiduspider|DuckDuckBot|Slurp"
SEO_BOT_PATTERNS = "AhrefsBot|SemrushBot|MJ12bot|DotBot|PetalBot"
SOCIAL_BOT_PATTERNS = "facebookexternalhit|Twitterbot|LinkedInBot|Pinterest|Slackbot|TelegramBot|WhatsApp"
MONITORING_PATTERNS = "Pingdom|UptimeRobot|Site24x7|StatusCake|Datadog"
HTTP_CLIENT_PATTERNS = (
    "curl/|wget/|python-requests/|axios/|node-fetch/|Go-http-client/|Java/|okhttp/|Apache-HttpClient|libwww-perl|Scrapy"
)
HEADLESS_PATTERNS = "PhantomJS|HeadlessChrome|Puppeteer|Playwright|Selenium"


def get_traffic_type(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: __preview_getTrafficType(user_agent)

    EXPERIMENTAL: This function may change without notice.

    Returns one of: 'AI Agent', 'Bot', 'Automation', 'Regular'
    """
    user_agent_expr = args[0]

    return ast.Call(
        name="multiIf",
        args=[
            # AI Agents (check first - most specific)
            ast.Call(name="match", args=[user_agent_expr, ast.Constant(value=AI_AGENT_PATTERNS)]),
            ast.Constant(value="AI Agent"),
            # Search Crawlers
            ast.Call(name="match", args=[user_agent_expr, ast.Constant(value=SEARCH_BOT_PATTERNS)]),
            ast.Constant(value="Bot"),
            # SEO Tools
            ast.Call(name="match", args=[user_agent_expr, ast.Constant(value=SEO_BOT_PATTERNS)]),
            ast.Constant(value="Bot"),
            # Social Crawlers
            ast.Call(name="match", args=[user_agent_expr, ast.Constant(value=SOCIAL_BOT_PATTERNS)]),
            ast.Constant(value="Bot"),
            # Monitoring
            ast.Call(name="match", args=[user_agent_expr, ast.Constant(value=MONITORING_PATTERNS)]),
            ast.Constant(value="Bot"),
            # HTTP Clients
            ast.Call(name="match", args=[user_agent_expr, ast.Constant(value=HTTP_CLIENT_PATTERNS)]),
            ast.Constant(value="Automation"),
            # Headless Browsers
            ast.Call(name="match", args=[user_agent_expr, ast.Constant(value=HEADLESS_PATTERNS)]),
            ast.Constant(value="Automation"),
            # Empty/Missing UA
            ast.Call(name="match", args=[user_agent_expr, ast.Constant(value="^$")]),
            ast.Constant(value="Automation"),
            # Default
            ast.Constant(value="Regular"),
        ],
    )


def get_traffic_category(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: __preview_getTrafficCategory(user_agent)

    EXPERIMENTAL: This function may change without notice.

    Returns subcategory: 'llm_crawler', 'search_crawler', 'seo_crawler', etc.
    For regular traffic, returns 'regular'.
    """
    user_agent_expr = args[0]

    return ast.Call(
        name="multiIf",
        args=[
            ast.Call(name="match", args=[user_agent_expr, ast.Constant(value=AI_AGENT_PATTERNS)]),
            ast.Constant(value="llm_crawler"),
            ast.Call(name="match", args=[user_agent_expr, ast.Constant(value=SEARCH_BOT_PATTERNS)]),
            ast.Constant(value="search_crawler"),
            ast.Call(name="match", args=[user_agent_expr, ast.Constant(value=SEO_BOT_PATTERNS)]),
            ast.Constant(value="seo_crawler"),
            ast.Call(name="match", args=[user_agent_expr, ast.Constant(value=SOCIAL_BOT_PATTERNS)]),
            ast.Constant(value="social_crawler"),
            ast.Call(name="match", args=[user_agent_expr, ast.Constant(value=MONITORING_PATTERNS)]),
            ast.Constant(value="monitoring"),
            ast.Call(name="match", args=[user_agent_expr, ast.Constant(value=HTTP_CLIENT_PATTERNS)]),
            ast.Constant(value="http_client"),
            ast.Call(name="match", args=[user_agent_expr, ast.Constant(value=HEADLESS_PATTERNS)]),
            ast.Constant(value="headless_browser"),
            ast.Call(name="match", args=[user_agent_expr, ast.Constant(value="^$")]),
            ast.Constant(value="no_user_agent"),
            ast.Constant(value="regular"),
        ],
    )


def is_bot(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: __preview_isBot(user_agent)

    EXPERIMENTAL: This function may change without notice.

    Returns true if the user agent matches bot/automation patterns, false otherwise.
    """
    user_agent_expr = args[0]

    # Creates 8 separate match() calls. For high-volume CDN logs, a single combined
    # pattern might be more efficient - profile before optimizing.
    return ast.Or(
        exprs=[
            ast.Call(name="match", args=[user_agent_expr, ast.Constant(value=AI_AGENT_PATTERNS)]),
            ast.Call(name="match", args=[user_agent_expr, ast.Constant(value=SEARCH_BOT_PATTERNS)]),
            ast.Call(name="match", args=[user_agent_expr, ast.Constant(value=SEO_BOT_PATTERNS)]),
            ast.Call(name="match", args=[user_agent_expr, ast.Constant(value=SOCIAL_BOT_PATTERNS)]),
            ast.Call(name="match", args=[user_agent_expr, ast.Constant(value=MONITORING_PATTERNS)]),
            ast.Call(name="match", args=[user_agent_expr, ast.Constant(value=HTTP_CLIENT_PATTERNS)]),
            ast.Call(name="match", args=[user_agent_expr, ast.Constant(value=HEADLESS_PATTERNS)]),
            ast.Call(name="match", args=[user_agent_expr, ast.Constant(value="^$")]),
        ]
    )


def get_bot_type(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: __preview_getBotType(user_agent)

    EXPERIMENTAL: This function may change without notice.

    Returns the bot category or empty string for regular traffic.
    Categories: 'llm_crawler', 'search_crawler', 'seo_crawler', 'social_crawler',
                'monitoring', 'http_client', 'headless_browser', 'no_user_agent', ''
    """
    user_agent_expr = args[0]

    return ast.Call(
        name="multiIf",
        args=[
            ast.Call(name="match", args=[user_agent_expr, ast.Constant(value=AI_AGENT_PATTERNS)]),
            ast.Constant(value="llm_crawler"),
            ast.Call(name="match", args=[user_agent_expr, ast.Constant(value=SEARCH_BOT_PATTERNS)]),
            ast.Constant(value="search_crawler"),
            ast.Call(name="match", args=[user_agent_expr, ast.Constant(value=SEO_BOT_PATTERNS)]),
            ast.Constant(value="seo_crawler"),
            ast.Call(name="match", args=[user_agent_expr, ast.Constant(value=SOCIAL_BOT_PATTERNS)]),
            ast.Constant(value="social_crawler"),
            ast.Call(name="match", args=[user_agent_expr, ast.Constant(value=MONITORING_PATTERNS)]),
            ast.Constant(value="monitoring"),
            ast.Call(name="match", args=[user_agent_expr, ast.Constant(value=HTTP_CLIENT_PATTERNS)]),
            ast.Constant(value="http_client"),
            ast.Call(name="match", args=[user_agent_expr, ast.Constant(value=HEADLESS_PATTERNS)]),
            ast.Constant(value="headless_browser"),
            ast.Call(name="match", args=[user_agent_expr, ast.Constant(value="^$")]),
            ast.Constant(value="no_user_agent"),
            # Regular traffic returns empty string
            ast.Constant(value=""),
        ],
    )
