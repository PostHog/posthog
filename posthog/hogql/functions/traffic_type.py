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

Bot definitions (patterns, categories, names) live in
posthog.hogql_queries.web_analytics.bot_definitions so that changes to
bot data do not require a HogQL review.
"""

from posthog.hogql import ast

from posthog.hogql_queries.web_analytics.bot_definitions import BOT_DEFINITIONS


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


def get_bot_operator(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: __preview_getBotOperator(user_agent)

    EXPERIMENTAL: This function may change without notice.

    Returns operator/company name: "Google", "OpenAI", "Anthropic", etc. Empty string for regular traffic.
    """
    return _build_bot_array_lookup(args[0], "operator", default="", empty_ua_value="")


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
