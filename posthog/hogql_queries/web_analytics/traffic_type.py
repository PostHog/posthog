from posthog.hogql import ast

# Re-export patterns from the HogQL functions module (single source of truth)
from posthog.hogql.functions.traffic_type import (
    AI_AGENT_PATTERNS,
    HEADLESS_PATTERNS,
    HTTP_CLIENT_PATTERNS,
    MONITORING_PATTERNS,
    SEARCH_BOT_PATTERNS,
    SEO_BOT_PATTERNS,
    SOCIAL_BOT_PATTERNS,
    get_traffic_category as _get_traffic_category,
    get_traffic_type as _get_traffic_type,
)

__all__ = [
    "AI_AGENT_PATTERNS",
    "SEARCH_BOT_PATTERNS",
    "SEO_BOT_PATTERNS",
    "SOCIAL_BOT_PATTERNS",
    "MONITORING_PATTERNS",
    "HTTP_CLIENT_PATTERNS",
    "HEADLESS_PATTERNS",
    "get_traffic_type_expr",
    "get_traffic_category_expr",
]


def get_traffic_type_expr(user_agent_expr: ast.Expr) -> ast.Expr:
    """
    Classifies user agent into traffic type using multiIf() with match().

    Returns an expression that evaluates to one of:
    - "AI Agent" - LLM crawlers (GPTBot, ClaudeBot, etc.)
    - "Bot" - Search engines, SEO tools, social crawlers, monitoring
    - "Automation" - HTTP clients, headless browsers, empty UA
    - "Human" - Default for unmatched user agents
    """
    node = ast.Call(name="getTrafficType", args=[user_agent_expr])
    return _get_traffic_type(node=node, args=[user_agent_expr])


def get_traffic_category_expr(user_agent_expr: ast.Expr) -> ast.Expr:
    """
    Returns subcategory expression for more granular classification.

    Categories:
    - llm_crawler: AI training/assistant bots
    - search_crawler: Search engine bots
    - seo_crawler: SEO tool bots
    - social_crawler: Social media crawlers
    - monitoring: Uptime/monitoring bots
    - http_client: CLI tools and libraries
    - headless_browser: Automation frameworks
    - no_user_agent: Empty or missing UA
    - human: Default for real users
    """
    node = ast.Call(name="getTrafficCategory", args=[user_agent_expr])
    return _get_traffic_category(node=node, args=[user_agent_expr])
