"""
Traffic type classification functions for HogQL.

Implemented as HogQL functions (rather than hardcoded in specific query runners) so they
can be used anywhere HogQL runs:
- SQL editor for ad-hoc analysis and exploration
- HogQLQuery runner for custom dashboards and insights
- Trends and other query runners when filtering/grouping by traffic type

Each function takes the user agent and an optional client IP. The IP signal exists for
crawlers that send real browser user agents with no bot token (e.g. Google's mobile
rendering service) and only match via the operator-published IP ranges.

The legacy __preview_* names still resolve as deprecated aliases.

Bot definitions (patterns, categories, names, IP ranges) live in
products.web_analytics.backend.hogql_queries so that changes to bot data do not require
a HogQL review.
"""

from typing import Optional

from posthog.hogql import ast

from products.web_analytics.backend.hogql_queries.bot_definitions import BOT_DEFINITIONS
from products.web_analytics.backend.hogql_queries.bot_ip_definitions import (
    BOT_IP_DEFINITIONS,
    bot_ip_prefix_groups_by_definition,
    merged_bot_ip_prefix_groups,
)


def _safe_ip_expr(ip_expr: ast.Expr) -> ast.Expr:
    """Normalize the client IP to IPv6 (IPv4 maps to ::ffff:a.b.c.d).

    NULL, empty, and unparsable values become :: which matches no range.
    """
    return ast.Call(
        name="toIPv6OrDefault",
        args=[ast.Call(name="ifNull", args=[ip_expr, ast.Constant(value="")])],
    )


def _ip_group_match(safe_ip: ast.Expr, prefixlen: int, addresses: tuple[str, ...]) -> ast.Expr:
    """Match one prefix-length group: zero the host bits, then a hash-set membership check.

    IPv6CIDRToRange(ip, N).1 is the network address of the ip's /N, so equality against the
    group's network addresses replaces per-CIDR range comparisons with a single IN lookup.
    """
    network_address = ast.Call(
        name="tupleElement",
        args=[
            ast.Call(name="IPv6CIDRToRange", args=[safe_ip, ast.Constant(value=prefixlen)]),
            ast.Constant(value=1),
        ],
    )
    return ast.CompareOperation(
        op=ast.CompareOperationOp.In,
        left=network_address,
        right=ast.Array(exprs=[ast.Call(name="toIPv6", args=[ast.Constant(value=a)]) for a in addresses]),
    )


def _build_ip_match_expr(ip_expr: ast.Expr) -> ast.Expr:
    """True when the IP falls in any known bot range (merged across all definitions)."""
    safe_ip = _safe_ip_expr(ip_expr)
    return ast.Or(
        exprs=[_ip_group_match(safe_ip, prefixlen, nets) for prefixlen, nets in merged_bot_ip_prefix_groups()]
    )


def _build_ip_definition_index_expr(ip_expr: ast.Expr) -> ast.Expr:
    """1-based index of the matching BOT_IP_DEFINITIONS entry, 0 when no range matches."""
    safe_ip = _safe_ip_expr(ip_expr)
    multi_if_args: list[ast.Expr] = []
    for index, (_key, groups) in enumerate(bot_ip_prefix_groups_by_definition(), start=1):
        multi_if_args.append(ast.Or(exprs=[_ip_group_match(safe_ip, prefixlen, nets) for prefixlen, nets in groups]))
        multi_if_args.append(ast.Constant(value=index))
    multi_if_args.append(ast.Constant(value=0))
    return ast.Call(name="multiIf", args=multi_if_args)


def _ip_label_lookup(ip_expr: ast.Expr, attr: str, default: str) -> ast.Expr:
    index_call = _build_ip_definition_index_expr(ip_expr)
    labels_array = ast.Array(
        exprs=[ast.Constant(value=getattr(ip_def, attr)) for ip_def in BOT_IP_DEFINITIONS.values()]
    )
    return ast.Call(
        name="if",
        args=[
            ast.CompareOperation(op=ast.CompareOperationOp.Eq, left=index_call, right=ast.Constant(value=0)),
            ast.Constant(value=default),
            ast.ArrayAccess(array=labels_array, property=index_call, nullish=False),
        ],
    )


def _build_bot_array_lookup(
    user_agent_expr: ast.Expr,
    attr: str,  # "name", "operator", "category", or "traffic_type"
    default: str = "",
    empty_ua_value: str = "",
    ip_expr: Optional[ast.Expr] = None,
) -> ast.Expr:
    """Build a multiMatchAnyIndex + array lookup expression for efficient bot detection.

    Uses multiMatchAnyIndex which evaluates the user_agent expression once and checks
    all patterns, then uses array indexing to get the corresponding label.

    NULL user agents are coalesced to empty string so they match the ^$ pattern
    and get classified as empty_ua_value instead of falling through to default.

    When ip_expr is given, user agents that match no pattern fall back to the IP-range
    lookup before defaulting.
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

    fallback: ast.Expr = ast.Constant(value=default)
    if ip_expr is not None:
        fallback = _ip_label_lookup(ip_expr, attr, default)

    # if(index = 0, fallback, labels[index])
    return ast.Call(
        name="if",
        args=[
            ast.CompareOperation(op=ast.CompareOperationOp.Eq, left=index_call, right=ast.Constant(value=0)),
            fallback,
            label_lookup,
        ],
    )


def _optional_ip_arg(args: list[ast.Expr]) -> Optional[ast.Expr]:
    return args[1] if len(args) > 1 else None


def get_bot_name(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: getBotName(user_agent[, ip])

    Returns bot name: "Googlebot", "ChatGPT", etc. Empty string for regular traffic.
    """
    return _build_bot_array_lookup(args[0], "name", default="", empty_ua_value="", ip_expr=_optional_ip_arg(args))


def get_bot_operator(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: getBotOperator(user_agent[, ip])

    Returns operator/company name: "Google", "OpenAI", "Anthropic", etc. Empty string for regular traffic.
    """
    return _build_bot_array_lookup(args[0], "operator", default="", empty_ua_value="", ip_expr=_optional_ip_arg(args))


def get_traffic_type(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: getTrafficType(user_agent[, ip])

    Returns one of: 'AI Agent', 'Bot', 'Automation', 'Regular'
    """
    return _build_bot_array_lookup(
        args[0], "traffic_type", default="Regular", empty_ua_value="Automation", ip_expr=_optional_ip_arg(args)
    )


def get_traffic_category(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: getTrafficCategory(user_agent[, ip])

    Returns subcategory: 'ai_crawler', 'ai_search', 'ai_assistant', 'search_crawler', 'seo_crawler', etc.
    For regular traffic, returns 'regular'.
    """
    return _build_bot_array_lookup(
        args[0], "category", default="regular", empty_ua_value="no_user_agent", ip_expr=_optional_ip_arg(args)
    )


def is_bot(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: isLikelyBot(user_agent[, ip])

    Returns true if the user agent matches bot/automation patterns, or (when given) the
    client IP falls in a known bot IP range. NULL user agents are treated as bots
    (empty UA is considered automation).

    Uses multiMatchAnyIndex for efficient single-pass matching (same as get_traffic_type etc.);
    the IP check is a handful of hash-set lookups and only evaluates for rows the UA check
    didn't already match (or() short-circuits).
    """
    user_agent_expr = args[0]

    safe_user_agent = ast.Call(name="ifNull", args=[user_agent_expr, ast.Constant(value="")])

    patterns = [*BOT_DEFINITIONS.keys(), "^$"]
    patterns_array = ast.Array(exprs=[ast.Constant(value=p) for p in patterns])

    index_call = ast.Call(name="multiMatchAnyIndex", args=[safe_user_agent, patterns_array])

    matched: ast.Expr = ast.CompareOperation(
        op=ast.CompareOperationOp.NotEq,
        left=index_call,
        right=ast.Constant(value=0),
    )
    ip_expr = _optional_ip_arg(args)
    if ip_expr is not None:
        matched = ast.Or(exprs=[matched, _build_ip_match_expr(ip_expr)])

    # Cast to Bool so results render as true/false (not 0/1) in insights breakdowns.
    return ast.Call(name="toBool", args=[matched])


def get_bot_type(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: getBotType(user_agent[, ip])

    Returns the bot category or empty string for regular traffic.
    Categories: 'ai_crawler', 'ai_search', 'ai_assistant', 'search_crawler', 'seo_crawler',
                'social_crawler', 'monitoring', 'http_client', 'headless_browser', 'no_user_agent', ''
    """
    return _build_bot_array_lookup(
        args[0], "category", default="", empty_ua_value="no_user_agent", ip_expr=_optional_ip_arg(args)
    )
