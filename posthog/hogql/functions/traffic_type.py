"""
Traffic type classification functions for HogQL.

Implemented as HogQL functions (rather than hardcoded in specific query runners) so they
can be used anywhere HogQL runs:
- SQL editor for ad-hoc analysis and exploration
- HogQLQuery runner for custom dashboards and insights
- Trends and other query runners when filtering/grouping by traffic type

Each function takes the user agent plus optional client IP and Signature-Agent values.
Both extra signals exist for agents that send real browser user agents with no bot token:
the IP ranges catch operator-published crawler infrastructure (e.g. Google's mobile
rendering service), and the Signature-Agent header (Web Bot Auth, RFC 9421) catches
agents that cryptographically self-identify (e.g. ChatGPT agent). Signal precedence is
user agent, then signature agent, then IP.

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
from products.web_analytics.backend.hogql_queries.bot_signature_agents import SIGNATURE_AGENT_DEFINITIONS


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


def _ip_label_lookup(ip_expr: ast.Expr, attr: str, fallback: ast.Expr) -> ast.Expr:
    index_call = _build_ip_definition_index_expr(ip_expr)
    labels_array = ast.Array(
        exprs=[ast.Constant(value=getattr(ip_def, attr)) for ip_def in BOT_IP_DEFINITIONS.values()]
    )
    return ast.Call(
        name="if",
        args=[
            ast.CompareOperation(op=ast.CompareOperationOp.Eq, left=index_call, right=ast.Constant(value=0)),
            fallback,
            ast.ArrayAccess(array=labels_array, property=index_call, nullish=False),
        ],
    )


def _normalized_signature_agent_expr(signature_agent_expr: ast.Expr) -> ast.Expr:
    """Normalize a Signature-Agent value to its host.

    The header is an RFC 8941 string item, so the raw value carries literal quotes
    (`"https://chatgpt.com"`) — and JSON property extraction leaves those escaped
    (`\\"https://chatgpt.com\\"`). Forwarders may also send it bare or as just the domain.
    Stripping backslashes and quotes then domain() accepts all forms; NULL/unparsable
    values become '' and match nothing.
    """
    lowered = ast.Call(
        name="lower", args=[ast.Call(name="ifNull", args=[signature_agent_expr, ast.Constant(value="")])]
    )
    without_backslashes = ast.Call(name="replaceAll", args=[lowered, ast.Constant(value="\\"), ast.Constant(value="")])
    stripped = ast.Call(name="replaceAll", args=[without_backslashes, ast.Constant(value='"'), ast.Constant(value="")])
    return ast.Call(name="domain", args=[stripped])


def _build_signature_agent_index_expr(signature_agent_expr: ast.Expr) -> ast.Expr:
    """1-based index of the matching SIGNATURE_AGENT_DEFINITIONS entry, 0 when none matches."""
    hosts_array = ast.Array(exprs=[ast.Constant(value=host) for host in SIGNATURE_AGENT_DEFINITIONS])
    return ast.Call(name="indexOf", args=[hosts_array, _normalized_signature_agent_expr(signature_agent_expr)])


def _signature_agent_label_lookup(signature_agent_expr: ast.Expr, attr: str, fallback: ast.Expr) -> ast.Expr:
    index_call = _build_signature_agent_index_expr(signature_agent_expr)
    labels_array = ast.Array(
        exprs=[ast.Constant(value=getattr(sig_def, attr)) for sig_def in SIGNATURE_AGENT_DEFINITIONS.values()]
    )
    return ast.Call(
        name="if",
        args=[
            ast.CompareOperation(op=ast.CompareOperationOp.Eq, left=index_call, right=ast.Constant(value=0)),
            fallback,
            ast.ArrayAccess(array=labels_array, property=index_call, nullish=False),
        ],
    )


def _build_bot_array_lookup(
    user_agent_expr: ast.Expr,
    attr: str,  # "name", "operator", "category", or "traffic_type"
    default: str = "",
    empty_ua_value: str = "",
    ip_expr: Optional[ast.Expr] = None,
    signature_agent_expr: Optional[ast.Expr] = None,
) -> ast.Expr:
    """Build a multiMatchAnyIndex + array lookup expression for efficient bot detection.

    Uses multiMatchAnyIndex which evaluates the user_agent expression once and checks
    all patterns, then uses array indexing to get the corresponding label.

    NULL user agents are coalesced to empty string so they match the ^$ pattern
    and get classified as empty_ua_value instead of falling through to default.

    When signature_agent_expr / ip_expr are given, user agents that match no pattern fall
    back to the Signature-Agent lookup, then the IP-range lookup, before defaulting.
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
        fallback = _ip_label_lookup(ip_expr, attr, fallback)
    if signature_agent_expr is not None:
        fallback = _signature_agent_label_lookup(signature_agent_expr, attr, fallback)

    # if(index = 0, fallback, labels[index])
    return ast.Call(
        name="if",
        args=[
            ast.CompareOperation(op=ast.CompareOperationOp.Eq, left=index_call, right=ast.Constant(value=0)),
            fallback,
            label_lookup,
        ],
    )


def _optional_arg(args: list[ast.Expr], index: int) -> Optional[ast.Expr]:
    return args[index] if len(args) > index else None


def get_bot_name(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: getBotName(user_agent[, ip[, signature_agent]])

    Returns bot name: "Googlebot", "ChatGPT", etc. Empty string for regular traffic.
    """
    return _build_bot_array_lookup(
        args[0],
        "name",
        default="",
        empty_ua_value="",
        ip_expr=_optional_arg(args, 1),
        signature_agent_expr=_optional_arg(args, 2),
    )


def get_bot_operator(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: getBotOperator(user_agent[, ip[, signature_agent]])

    Returns operator/company name: "Google", "OpenAI", "Anthropic", etc. Empty string for regular traffic.
    """
    return _build_bot_array_lookup(
        args[0],
        "operator",
        default="",
        empty_ua_value="",
        ip_expr=_optional_arg(args, 1),
        signature_agent_expr=_optional_arg(args, 2),
    )


def get_traffic_type(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: getTrafficType(user_agent[, ip[, signature_agent]])

    Returns one of: 'AI Agent', 'Bot', 'Automation', 'Regular'
    """
    return _build_bot_array_lookup(
        args[0],
        "traffic_type",
        default="Regular",
        empty_ua_value="Automation",
        ip_expr=_optional_arg(args, 1),
        signature_agent_expr=_optional_arg(args, 2),
    )


def get_traffic_category(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: getTrafficCategory(user_agent[, ip[, signature_agent]])

    Returns subcategory: 'ai_crawler', 'ai_search', 'ai_assistant', 'search_crawler', 'seo_crawler', etc.
    For regular traffic, returns 'regular'.
    """
    return _build_bot_array_lookup(
        args[0],
        "category",
        default="regular",
        empty_ua_value="no_user_agent",
        ip_expr=_optional_arg(args, 1),
        signature_agent_expr=_optional_arg(args, 2),
    )


def is_bot(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: isLikelyBot(user_agent[, ip[, signature_agent]])

    Returns true if the user agent matches bot/automation patterns, or (when given) the
    Signature-Agent value names a known signed agent, or the client IP falls in a known
    bot IP range. NULL user agents are treated as bots (empty UA is considered automation).

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
    branches: list[ast.Expr] = [matched]
    signature_agent_expr = _optional_arg(args, 2)
    if signature_agent_expr is not None:
        branches.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.NotEq,
                left=_build_signature_agent_index_expr(signature_agent_expr),
                right=ast.Constant(value=0),
            )
        )
    ip_expr = _optional_arg(args, 1)
    if ip_expr is not None:
        branches.append(_build_ip_match_expr(ip_expr))
    if len(branches) > 1:
        matched = ast.Or(exprs=branches)

    # Cast to Bool so results render as true/false (not 0/1) in insights breakdowns.
    return ast.Call(name="toBool", args=[matched])


def get_bot_type(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    HogQL function: getBotType(user_agent[, ip[, signature_agent]])

    Returns the bot category or empty string for regular traffic.
    Categories: 'ai_crawler', 'ai_search', 'ai_assistant', 'search_crawler', 'seo_crawler',
                'social_crawler', 'monitoring', 'http_client', 'headless_browser', 'no_user_agent', ''
    """
    return _build_bot_array_lookup(
        args[0],
        "category",
        default="",
        empty_ua_value="no_user_agent",
        ip_expr=_optional_arg(args, 1),
        signature_agent_expr=_optional_arg(args, 2),
    )
