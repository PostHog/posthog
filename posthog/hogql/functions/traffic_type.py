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

A project can extend the built-in list with its own rules, which arrive as query modifiers. Each
rule matches one event property, so the rules are checked as an ordered chain ahead of the
built-ins rather than merged into the built-in pattern array. A project's own rule wins when both
match.
"""

from typing import TYPE_CHECKING, Optional

from posthog.hogql import ast

from posthog.dataclasses import frozen

from products.web_analytics.backend.hogql_queries.bot_definitions import BOT_DEFINITIONS
from products.web_analytics.backend.hogql_queries.bot_ip_definitions import (
    BOT_IP_DEFINITIONS,
    bot_ip_prefix_groups_by_definition,
    merged_bot_ip_prefix_groups,
)
from products.web_analytics.backend.hogql_queries.custom_bot_definitions import (
    IP_FIELD,
    USER_AGENT_FIELD,
    CidrGroup,
    CustomBotGroup,
    compile_definitions,
)

if TYPE_CHECKING:
    from posthog.schema import HogQLQueryModifiers


def _custom_groups(modifiers: Optional["HogQLQueryModifiers"]) -> list[CustomBotGroup]:
    if modifiers is None:
        return []
    return compile_definitions(modifiers.customBotDefinitions)


def has_user_agent_rule(modifiers: Optional["HogQLQueryModifiers"]) -> bool:
    """Whether the project has a rule on the user agent — the only rule kind that makes the one-arg
    isLikelyBot expansion reference its argument twice (see the resolver's re-entrancy guard)."""
    if modifiers is None or not modifiers.customBotDefinitions:
        return False
    return any(definition.key == USER_AGENT_FIELD for definition in modifiers.customBotDefinitions)


def _string_array(values: list[str]) -> ast.Array:
    return ast.Array(exprs=[ast.Constant(value=value) for value in values])


def _matched(index_call: ast.Expr) -> ast.Expr:
    return ast.CompareOperation(op=ast.CompareOperationOp.NotEq, left=index_call, right=ast.Constant(value=0))


def _property_expr(key: str, args: list[ast.Expr]) -> Optional[ast.Expr]:
    """The expression a project rule on `key` matches against, or None when this call cannot reach it.

    The user agent and the client IP arrive as arguments. Any other property hangs off the same
    properties object the user agent was read from, which only works when the caller passed a plain
    property reference — a hand-written `isLikelyBot(concat(...))` has no properties object to
    reach into, so rules on those properties are skipped rather than guessed at.
    """
    if key == USER_AGENT_FIELD:
        return args[0]
    ip_expr = _optional_ip_arg(args)
    if key == IP_FIELD and ip_expr is not None:
        return ip_expr
    user_agent_expr = args[0]
    # Only a user agent read straight from a properties object (properties.$raw_user_agent) has a
    # sibling to reach for. Replacing the last segment of any other chain would invent a column, e.g.
    # getBotName(foo.ua) -> foo.$host, and fail the whole query, so skip the rule instead.
    if (
        isinstance(user_agent_expr, ast.Field)
        and len(user_agent_expr.chain) > 1
        and user_agent_expr.chain[-1] == USER_AGENT_FIELD
        and user_agent_expr.chain[-2] == "properties"
    ):
        return ast.Field(chain=[*user_agent_expr.chain[:-1], key])
    return None


@frozen
class CustomRuleBranch:
    """One group of a project's rules, compiled: whether it matched and which label it reports."""

    matched: ast.Expr
    label: ast.Expr


def _custom_group_branch(group: CustomBotGroup, args: list[ast.Expr], attr: str) -> Optional[CustomRuleBranch]:
    property_expr = _property_expr(group.key, args)
    if property_expr is None:
        return None

    if isinstance(group, CidrGroup):
        safe_ip = _safe_ip_expr(property_expr)
        multi_if_args: list[ast.Expr] = []
        for index, (prefixlen, address) in enumerate(group.networks, start=1):
            multi_if_args.append(_ip_group_match(safe_ip, prefixlen, (address,)))
            multi_if_args.append(ast.Constant(value=index))
        multi_if_args.append(ast.Constant(value=0))
        index_call: ast.Expr = ast.Call(name="multiIf", args=multi_if_args)
    else:
        safe_property = ast.Call(name="ifNull", args=[property_expr, ast.Constant(value="")])
        # arrayMin over ALL matching patterns, not multiMatchAnyIndex: when two of a project's own
        # rules match the same value, the one listed first wins. multiMatchAnyIndex would report
        # whichever pattern matches earliest in the string, so a specific rule listed above a broad
        # one could never take the label. Still a single hyperscan pass; an empty match list
        # arrayMins to 0, the same no-match sentinel.
        index_call = ast.Call(
            name="arrayMin",
            args=[ast.Call(name="multiMatchAllIndices", args=[safe_property, _string_array(group.patterns)])],
        )

    labels = _string_array([getattr(definition, attr) for definition in group.definitions])
    return CustomRuleBranch(
        matched=_matched(index_call),
        label=ast.ArrayAccess(array=labels, property=index_call, nullish=False),
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
    args: list[ast.Expr],
    attr: str,  # "name", "operator", "category", or "traffic_type"
    default: str = "",
    empty_ua_value: str = "",
    modifiers: Optional["HogQLQueryModifiers"] = None,
) -> ast.Expr:
    """Build the expression that resolves one classification label.

    Uses multiMatchAnyIndex, which evaluates the user agent once and checks all patterns, then
    indexes the matching label out of a parallel array.

    NULL user agents are coalesced to empty string so a missing user agent classifies as
    empty_ua_value instead of falling through to default.

    When the client IP is given, anything the patterns miss falls back to the IP-range lookup
    before defaulting.
    """
    user_agent_expr = args[0]
    ip_expr = _optional_ip_arg(args)
    # Coalesce NULL to empty string so NULL user agents are matchable
    safe_user_agent = ast.Call(name="ifNull", args=[user_agent_expr, ast.Constant(value="")])

    fallback: ast.Expr = ast.Constant(value=default)
    if ip_expr is not None:
        fallback = _ip_label_lookup(ip_expr, attr, default)

    builtin_labels = [getattr(bot_def, attr) for bot_def in BOT_DEFINITIONS.values()]
    groups = _custom_groups(modifiers)

    if not groups:
        # No project rules: one pass over the built-in patterns plus the empty-user-agent sentinel.
        patterns_array = _string_array([*BOT_DEFINITIONS.keys(), "^$"])
        labels_array = _string_array([*builtin_labels, empty_ua_value])
        index_call = ast.Call(name="multiMatchAnyIndex", args=[safe_user_agent, patterns_array])
        return ast.Call(
            name="if",
            args=[
                ast.CompareOperation(op=ast.CompareOperationOp.Eq, left=index_call, right=ast.Constant(value=0)),
                fallback,
                ast.ArrayAccess(array=labels_array, property=index_call, nullish=False),
            ],
        )

    # With project rules the checks become an ordered chain, in this order: the project's own
    # rules, then the built-ins, then the empty user agent, then the built-in IP ranges. A rule
    # someone wrote by hand says more about what they want counted than a default we shipped, so
    # it wins — that also makes the setting predictable, since a rule that matches always names
    # the event.
    #
    # It has to be a branch per group rather than one shared pattern array: multiMatchAnyIndex
    # reports whichever pattern matches earliest in the string rather than earliest in the array,
    # so merging the arrays would leave precedence up to the user agent being classified.
    branches: list[ast.Expr] = []
    for group in groups:
        branch = _custom_group_branch(group, args, attr)
        if branch is not None:
            branches.extend([branch.matched, branch.label])
    builtin_index = ast.Call(
        name="multiMatchAnyIndex", args=[safe_user_agent, _string_array(list(BOT_DEFINITIONS.keys()))]
    )
    branches.extend(
        [
            _matched(builtin_index),
            ast.ArrayAccess(array=_string_array(builtin_labels), property=builtin_index, nullish=False),
        ]
    )
    branches.extend(
        [
            ast.CompareOperation(op=ast.CompareOperationOp.Eq, left=safe_user_agent, right=ast.Constant(value="")),
            ast.Constant(value=empty_ua_value),
        ]
    )
    branches.append(fallback)
    return ast.Call(name="multiIf", args=branches)


def _optional_ip_arg(args: list[ast.Expr]) -> Optional[ast.Expr]:
    return args[1] if len(args) > 1 else None


def get_bot_name(node: ast.Call, args: list[ast.Expr], modifiers: Optional["HogQLQueryModifiers"] = None) -> ast.Expr:
    """
    HogQL function: getBotName(user_agent[, ip])

    Returns bot name: "Googlebot", "ChatGPT", etc. Empty string for regular traffic.
    """
    return _build_bot_array_lookup(args, "name", default="", empty_ua_value="", modifiers=modifiers)


def get_bot_operator(
    node: ast.Call, args: list[ast.Expr], modifiers: Optional["HogQLQueryModifiers"] = None
) -> ast.Expr:
    """
    HogQL function: getBotOperator(user_agent[, ip])

    Returns operator/company name: "Google", "OpenAI", "Anthropic", etc. Empty string for regular traffic.
    """
    return _build_bot_array_lookup(args, "operator", default="", empty_ua_value="", modifiers=modifiers)


def get_traffic_type(
    node: ast.Call, args: list[ast.Expr], modifiers: Optional["HogQLQueryModifiers"] = None
) -> ast.Expr:
    """
    HogQL function: getTrafficType(user_agent[, ip])

    Returns one of: 'AI Agent', 'Bot', 'Automation', 'Regular'
    """
    return _build_bot_array_lookup(
        args, "traffic_type", default="Regular", empty_ua_value="Automation", modifiers=modifiers
    )


def get_traffic_category(
    node: ast.Call, args: list[ast.Expr], modifiers: Optional["HogQLQueryModifiers"] = None
) -> ast.Expr:
    """
    HogQL function: getTrafficCategory(user_agent[, ip])

    Returns subcategory: 'ai_crawler', 'ai_search', 'ai_assistant', 'search_crawler', 'seo_crawler', etc.
    For regular traffic, returns 'regular'.
    """
    return _build_bot_array_lookup(
        args, "category", default="regular", empty_ua_value="no_user_agent", modifiers=modifiers
    )


def is_bot(node: ast.Call, args: list[ast.Expr], modifiers: Optional["HogQLQueryModifiers"] = None) -> ast.Expr:
    """
    HogQL function: isLikelyBot(user_agent[, ip])

    Returns true if the user agent matches bot/automation patterns, or (when given) the
    client IP falls in a known bot IP range. NULL user agents are treated as bots
    (empty UA is considered automation).

    Uses multiMatchAnyIndex for efficient single-pass matching (same as get_traffic_type etc.);
    the IP check is a handful of hash-set lookups and only evaluates for rows the UA check
    didn't already match (or() short-circuits).

    Unlike the label lookups this only answers yes or no, so a project's rules can be OR'd in
    rather than ordered against the built-ins — no rule can change the answer another one gave.
    """
    user_agent_expr = args[0]

    safe_user_agent = ast.Call(name="ifNull", args=[user_agent_expr, ast.Constant(value="")])

    patterns_array = _string_array([*BOT_DEFINITIONS.keys(), "^$"])
    index_call = ast.Call(name="multiMatchAnyIndex", args=[safe_user_agent, patterns_array])

    conditions: list[ast.Expr] = [_matched(index_call)]
    for group in _custom_groups(modifiers):
        branch = _custom_group_branch(group, args, "name")
        if branch is not None:
            conditions.append(branch.matched)
    ip_expr = _optional_ip_arg(args)
    if ip_expr is not None:
        conditions.append(_build_ip_match_expr(ip_expr))

    matched: ast.Expr = conditions[0] if len(conditions) == 1 else ast.Or(exprs=conditions)

    # Cast to Bool so results render as true/false (not 0/1) in insights breakdowns.
    return ast.Call(name="toBool", args=[matched])


def get_bot_type(node: ast.Call, args: list[ast.Expr], modifiers: Optional["HogQLQueryModifiers"] = None) -> ast.Expr:
    """
    HogQL function: getBotType(user_agent[, ip])

    Returns the bot category or empty string for regular traffic.
    Categories: 'ai_crawler', 'ai_search', 'ai_assistant', 'search_crawler', 'seo_crawler',
                'social_crawler', 'monitoring', 'http_client', 'headless_browser', 'no_user_agent',
                a project's own category, or ''
    """
    return _build_bot_array_lookup(args, "category", default="", empty_ua_value="no_user_agent", modifiers=modifiers)
