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
    HogQL function: getTrafficType(user_agent)

    Returns one of: 'AI Agent', 'Bot', 'Automation', 'Human'
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
            ast.Constant(value="Human"),
        ],
    )


def get_traffic_category(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: getTrafficCategory(user_agent)

    Returns subcategory: 'llm_crawler', 'search_crawler', 'seo_crawler', etc.
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
            ast.Constant(value="human"),
        ],
    )
