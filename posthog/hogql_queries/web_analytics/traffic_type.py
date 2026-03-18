"""
Traffic type classification helper functions for web analytics.

EXPERIMENTAL: These functions use __preview_ prefixed HogQL functions to indicate
they are experimental and may change without notice. The patterns and return values
may be adjusted as we gather more data on real-world traffic classification accuracy.

The underlying HogQL functions provide maximum flexibility during development:
- SQL editor: Direct usage for ad-hoc analysis (e.g., SELECT __preview_isBot(properties.$raw_user_agent))
- HogQLQuery: Custom dashboards and insights with traffic type filtering
- Trends: Group or filter by traffic type when analyzing patterns
- Web analytics: These helper functions wrap the HogQL functions for use in query runners
"""

from posthog.hogql import ast

# Re-export BOT_DEFINITIONS from the HogQL functions module (single source of truth)
from posthog.hogql.functions.traffic_type import (
    BOT_DEFINITIONS,
    get_bot_name as _get_bot_name,
    get_bot_type as _get_bot_type,
    get_traffic_category as _get_traffic_category,
    get_traffic_type as _get_traffic_type,
    is_bot as _is_bot,
)

__all__ = [
    "BOT_DEFINITIONS",
    "get_traffic_type_expr",
    "get_traffic_category_expr",
    "is_bot_expr",
    "get_bot_type_expr",
    "get_bot_name_expr",
]


def get_traffic_type_expr(user_agent_expr: ast.Expr) -> ast.Expr:
    """
    Classifies user agent into traffic type.

    EXPERIMENTAL: This function may change without notice.

    Returns an expression that evaluates to one of:
    - "AI Agent" - LLM crawlers (GPTBot, ClaudeBot, etc.)
    - "Bot" - Search engines, SEO tools, social crawlers, monitoring
    - "Automation" - HTTP clients, headless browsers, empty UA
    - "Regular" - Default for unmatched user agents
    """
    return _get_traffic_type(node=ast.Call(name="__preview_getTrafficType", args=[]), args=[user_agent_expr])


def get_traffic_category_expr(user_agent_expr: ast.Expr) -> ast.Expr:
    """
    Returns subcategory expression for more granular classification.

    EXPERIMENTAL: This function may change without notice.

    Categories: llm_crawler, search_crawler, seo_crawler, social_crawler,
    monitoring, http_client, headless_browser, no_user_agent, regular
    """
    return _get_traffic_category(node=ast.Call(name="__preview_getTrafficCategory", args=[]), args=[user_agent_expr])


def is_bot_expr(user_agent_expr: ast.Expr) -> ast.Expr:
    """
    Returns a boolean expression: true if bot/automation, false for regular traffic.

    EXPERIMENTAL: This function may change without notice.
    """
    return _is_bot(node=ast.Call(name="__preview_isBot", args=[]), args=[user_agent_expr])


def get_bot_type_expr(user_agent_expr: ast.Expr) -> ast.Expr:
    """
    Returns the bot category or empty string for regular traffic.

    EXPERIMENTAL: This function may change without notice.

    Categories: llm_crawler, search_crawler, seo_crawler, social_crawler,
    monitoring, http_client, headless_browser, no_user_agent, "" (regular)
    """
    return _get_bot_type(node=ast.Call(name="__preview_getBotType", args=[]), args=[user_agent_expr])


def get_bot_name_expr(user_agent_expr: ast.Expr) -> ast.Expr:
    """
    Returns the bot name or empty string for regular traffic.

    EXPERIMENTAL: This function may change without notice.

    Examples: "Googlebot", "ChatGPT", "Claude", "curl", ""
    """
    return _get_bot_name(node=ast.Call(name="__preview_getBotName", args=[]), args=[user_agent_expr])
