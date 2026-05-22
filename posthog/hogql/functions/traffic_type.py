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

Bot patterns live in a ClickHouse REGEXP_TREE dictionary (web_bot_definition_dict)
backed by the web_bot_definition table. This allows the pattern list to scale beyond
what can be inlined in SQL, and lets patterns be updated without code deploys.

The source of truth for initial data is
products.web_analytics.backend.hogql_queries.bot_definitions. Changes there require a
new ClickHouse migration to update the web_bot_definition table and reload the dict.
"""

from django.conf import settings

from posthog.hogql import ast
from posthog.models.bot_definition.sql import BOT_DEFINITION_DICTIONARY_NAME


def _bot_dict() -> str:
    """Fully-qualified dictionary name, evaluated at call time for test-DB compatibility."""
    return f"{settings.CLICKHOUSE_DATABASE}.{BOT_DEFINITION_DICTIONARY_NAME}"


def _safe_ua(user_agent_expr: ast.Expr) -> ast.Expr:
    """Wrap expression in ifNull(..., '') so NULL user agents match the ^$ pattern."""
    return ast.Call(name="ifNull", args=[user_agent_expr, ast.Constant(value="")])


def _dict_get(user_agent_expr: ast.Expr, attribute: str, default: str) -> ast.Expr:
    """Build dictGetOrDefault(<dict>, <attribute>, ifNull(ua, ''), <default>) AST."""
    return ast.Call(
        name="dictGetOrDefault",
        args=[
            ast.Constant(value=_bot_dict()),
            ast.Constant(value=attribute),
            _safe_ua(user_agent_expr),
            ast.Constant(value=default),
        ],
    )


def get_bot_name(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: __preview_getBotName(user_agent)

    EXPERIMENTAL: This function may change without notice.

    Returns bot name: "Googlebot", "ChatGPT", etc. Empty string for regular traffic.
    """
    return _dict_get(args[0], "name", "")


def get_bot_operator(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: __preview_getBotOperator(user_agent)

    EXPERIMENTAL: This function may change without notice.

    Returns operator/company name: "Google", "OpenAI", "Anthropic", etc. Empty string for regular traffic.
    """
    return _dict_get(args[0], "operator", "")


def get_traffic_type(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: __preview_getTrafficType(user_agent)

    EXPERIMENTAL: This function may change without notice.

    Returns one of: 'AI Agent', 'Bot', 'Automation', 'Regular'
    """
    return _dict_get(args[0], "traffic_type", "Regular")


def get_traffic_category(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: __preview_getTrafficCategory(user_agent)

    EXPERIMENTAL: This function may change without notice.

    Returns subcategory: 'ai_crawler', 'ai_search', 'ai_assistant', 'search_crawler', 'seo_crawler', etc.
    For regular traffic, returns 'regular'.
    """
    return _dict_get(args[0], "category", "regular")


def is_bot(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: __preview_isBot(user_agent)

    EXPERIMENTAL: This function may change without notice.

    Returns true if the user agent matches bot/automation patterns, false otherwise.
    NULL user agents are treated as bots (empty UA is classified as Automation via the ^$ pattern).
    """
    return ast.CompareOperation(
        op=ast.CompareOperationOp.NotEq,
        left=_dict_get(args[0], "traffic_type", "Regular"),
        right=ast.Constant(value="Regular"),
    )


def get_bot_type(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: __preview_getBotType(user_agent)

    EXPERIMENTAL: This function may change without notice.

    Returns the bot category or empty string for regular traffic.
    Categories: 'ai_crawler', 'ai_search', 'ai_assistant', 'search_crawler', 'seo_crawler',
                'social_crawler', 'monitoring', 'http_client', 'headless_browser', 'no_user_agent', ''
    """
    return _dict_get(args[0], "category", "")
