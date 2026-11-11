"""Turn a group property filter into the set of group keys it matches, so events queries can filter
on the `$group_N` column instead of joining the groups table.

The join reads every group row's `group_properties` JSON, and ClickHouse pushes it into the per-shard
events subquery, so each shard pays that scan independently. Resolving the keys once and filtering on
a column instead is measurably cheaper and returns the same sessions.
"""

import json
import time
import hashlib
from collections.abc import Callable
from typing import Any, cast

from django.core.cache import cache

import structlog

from posthog.schema import EventPropertyFilter, GroupPropertyFilter, HogQLPropertyFilter, PropertyOperator

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.models import Team, User

logger = structlog.get_logger(__name__)

GROUP_KEY_RESOLUTION_QUERY_TYPE = "GroupKeyResolutionQuery"

# Group membership changes on a human timescale, while a scanner sweeps every few minutes.
GROUP_KEY_CACHE_TTL_SECONDS = 3600

# Past this the key list stops being cheaper than the join, and it starts crowding `max_query_size`.
MAX_RESOLVED_GROUP_KEYS = 10_000

# The key queries run before the listing query, so all of one listing's lookups share this much time.
GROUP_KEY_RESOLUTION_MAX_SECONDS = 5
# A listing with more uncached group filters than this keeps the join for the rest.
MAX_GROUP_KEY_LOOKUPS = 5
# A failed resolution is remembered for a while, so a slow groups table is not queried again on every listing.
GROUP_KEY_FAILURE_TTL_SECONDS = 600

# A negated filter has to distinguish "this group does not match" from "this event has no group at
# all", which an IN list over matching keys cannot express. Those keep the join.
_RESOLVABLE_OPERATORS = {
    PropertyOperator.EXACT,
    PropertyOperator.IN_,
    PropertyOperator.ICONTAINS,
    PropertyOperator.REGEX,
    PropertyOperator.GT,
    PropertyOperator.GTE,
    PropertyOperator.LT,
    PropertyOperator.LTE,
    PropertyOperator.IS_SET,
}

# Numeric comparisons need the cast the group-join path gets from its typed field.
_NUMERIC_OPERATORS = {
    PropertyOperator.GT: ast.CompareOperationOp.Gt,
    PropertyOperator.GTE: ast.CompareOperationOp.GtEq,
    PropertyOperator.LT: ast.CompareOperationOp.Lt,
    PropertyOperator.LTE: ast.CompareOperationOp.LtEq,
}

_FALLBACK = "fallback"


class GroupKeyLookupBudget:
    """The time and lookup count one listing may spend resolving keys, so many group filters cannot multiply it."""

    def __init__(self) -> None:
        self._deadline = time.monotonic() + GROUP_KEY_RESOLUTION_MAX_SECONDS
        self._lookups_left = MAX_GROUP_KEY_LOOKUPS

    def take(self) -> int | None:
        """Seconds for the next lookup, or None when the budget is spent and the filter should keep the join."""
        seconds_left = int(self._deadline - time.monotonic())
        if self._lookups_left <= 0 or seconds_left < 1:
            return None
        self._lookups_left -= 1
        return seconds_left


def resolved_group_key_expr(
    team: Team,
    prop: GroupPropertyFilter,
    ch_user: ClickHouseUser,
    user: User | None = None,
    budget: GroupKeyLookupBudget | None = None,
) -> ast.Expr | None:
    """`$group_N IN (keys)` for this filter, or None when the caller should keep the join."""
    if prop.operator not in _RESOLVABLE_OPERATORS or prop.group_type_index is None:
        return None

    return _resolved_key_in(
        team,
        prop.key,
        prop.group_type_index,
        [prop.group_type_index, prop.key, prop.operator, prop.value],
        lambda: _resolution_predicate(team, prop),
        ch_user,
        user,
        budget or GroupKeyLookupBudget(),
    )


def resolved_hogql_group_key_expr(
    team: Team,
    prop: HogQLPropertyFilter,
    ch_user: ClickHouseUser,
    user: User | None = None,
    budget: GroupKeyLookupBudget | None = None,
) -> ast.Expr | None:
    """`$group_N IN (keys)` for a HogQL filter that only reads one group type's properties, or None to keep the join.

    A HogQL filter like `group_0.properties.plan = 'pro' OR group_0.properties.mrr > 100` compiles to the same
    events-to-groups join as a group property filter, so it pays the same per-shard scan of every group row.
    """
    # Most HogQL filters read only event properties, so skip the parse for those.
    if "group_" not in prop.key:
        return None
    try:
        expr = parse_expr(prop.key)
    except Exception:
        return None
    group_type_index = _single_group_property_reader(expr)
    if group_type_index is None:
        return None

    return _resolved_key_in(
        team,
        # The expression can carry literal values, so only its group type reaches the logs.
        f"hogql:group_{group_type_index}",
        group_type_index,
        ["hogql", group_type_index, prop.key],
        lambda: _GroupPrefixStripper().visit(expr),
        ch_user,
        user,
        budget or GroupKeyLookupBudget(),
    )


def _resolved_key_in(
    team: Team,
    property_key: str,
    group_type_index: int,
    cache_parts: list[Any],
    predicate: Callable[[], ast.Expr],
    ch_user: ClickHouseUser,
    user: User | None,
    budget: GroupKeyLookupBudget,
) -> ast.Expr | None:
    keys = _group_keys(
        team,
        property_key,
        # Per user, because the lookup applies that user's property restrictions as the join would.
        _cache_key(team, [*cache_parts, user.pk if user is not None else None]),
        budget,
        lambda seconds: _query_group_keys(team, group_type_index, predicate(), ch_user, user, seconds),
    )
    return None if keys is None else _group_key_in(group_type_index, keys)


def _group_key_in(group_type_index: int, keys: list[str]) -> ast.Expr:
    return ast.CompareOperation(
        op=ast.CompareOperationOp.In,
        left=ast.Field(chain=["events", f"$group_{group_type_index}"]),
        right=ast.Constant(value=keys),
    )


# A key list can only express "the event's group matches". These ops and calls can also be true for an event with
# no group at all, which the join keeps and the key list would drop, so expressions using them keep the join.
_KEY_SAFE_COMPARE_OPS = {
    ast.CompareOperationOp.Eq,
    ast.CompareOperationOp.Gt,
    ast.CompareOperationOp.GtEq,
    ast.CompareOperationOp.Lt,
    ast.CompareOperationOp.LtEq,
    ast.CompareOperationOp.Like,
    ast.CompareOperationOp.ILike,
    ast.CompareOperationOp.Regex,
    ast.CompareOperationOp.IRegex,
    ast.CompareOperationOp.In,
}
_KEY_SAFE_CALLS = {"toFloat", "toInt", "toString", "toBool", "lower", "upper", "trim", "toDate", "toDateTime"}


class _GroupPropertyReaderCheck(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.group_type_indexes: set[int] = set()
        self.unsafe = False

    def visit_field(self, node: ast.Field) -> None:
        chain = [str(part) for part in node.chain]
        if len(chain) >= 3 and chain[1] == "properties" and chain[0].startswith("group_") and chain[0][6:].isdigit():
            self.group_type_indexes.add(int(chain[0][6:]))
        else:
            self.unsafe = True

    def visit_compare_operation(self, node: ast.CompareOperation) -> None:
        if node.op not in _KEY_SAFE_COMPARE_OPS:
            self.unsafe = True
        super().visit_compare_operation(node)

    def visit_call(self, node: ast.Call) -> None:
        if node.name not in _KEY_SAFE_CALLS:
            self.unsafe = True
        super().visit_call(node)

    def visit_constant(self, node: ast.Constant) -> None:
        # Comparing with null or an empty string can match an event whose group is missing.
        if node.value is None or node.value == "":
            self.unsafe = True

    def visit_not(self, node: ast.Not) -> None:
        self.unsafe = True

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self.unsafe = True

    def visit_placeholder(self, node: ast.Placeholder) -> None:
        self.unsafe = True


def _single_group_property_reader(expr: ast.Expr) -> int | None:
    """The group type index when `expr` is a key-safe predicate over that one group type's properties, else None."""
    if not isinstance(expr, ast.And | ast.Or | ast.CompareOperation):
        return None
    check = _GroupPropertyReaderCheck()
    check.visit(expr)
    if check.unsafe or len(check.group_type_indexes) != 1 or not _false_without_group(expr):
        return None
    return next(iter(check.group_type_indexes))


def _false_without_group(expr: ast.Expr) -> bool:
    """Whether `expr` is false for an event with no group, the only events a key list drops.

    Every comparison must test a group property against a value. `OR 1 = 1` or a comparison of two group
    properties can be true with no group, because HogQL treats null as equal to null.
    """
    if isinstance(expr, ast.And):
        return any(_false_without_group(operand) for operand in expr.exprs)
    if isinstance(expr, ast.Or):
        return all(_false_without_group(operand) for operand in expr.exprs)
    if isinstance(expr, ast.CompareOperation):
        # A nested comparison such as `(group_0.properties.plan = 'pro') = false` is true when the group is missing.
        if _has_nested_logic(expr.left) or _has_nested_logic(expr.right):
            return False
        # The side without fields must be a literal: a call such as `toInt('invalid')` can be null, and null equals null.
        if _reads_fields(expr.left):
            return _is_literal(expr.right)
        return _reads_fields(expr.right) and _is_literal(expr.left)
    return False


def _is_literal(expr: ast.Expr) -> bool:
    if isinstance(expr, ast.Constant):
        return expr.value is not None
    if isinstance(expr, ast.Tuple | ast.Array):
        return bool(expr.exprs) and all(_is_literal(item) for item in expr.exprs)
    return False


def _reads_fields(expr: ast.Expr) -> bool:
    finder = _FieldFinder()
    finder.visit(expr)
    return finder.found


def _has_nested_logic(expr: ast.Expr) -> bool:
    finder = _LogicFinder()
    finder.visit(expr)
    return finder.found


class _LogicFinder(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.found = False

    def visit_compare_operation(self, node: ast.CompareOperation) -> None:
        self.found = True

    def visit_and(self, node: ast.And) -> None:
        self.found = True

    def visit_or(self, node: ast.Or) -> None:
        self.found = True


class _FieldFinder(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.found = False

    def visit_field(self, node: ast.Field) -> None:
        self.found = True


class _GroupPrefixStripper(CloningVisitor):
    """`group_N.properties.x` to `properties.x`, the form that reads the property in a select over `groups`."""

    def visit_field(self, node: ast.Field) -> ast.Field:
        return ast.Field(chain=node.chain[1:])


def _group_keys(
    team: Team,
    property_key: str,
    cache_key: str,
    budget: GroupKeyLookupBudget,
    resolve: Callable[[int], list[str]],
) -> list[str] | None:
    cached = _swallowing_failure("group_key_cache_read_failed", team, property_key, lambda: cache.get(cache_key))
    if cached == _FALLBACK:
        return None
    if cached is not None:
        return _cast_keys(cached)

    seconds = budget.take()
    if seconds is None:
        # Not cached as a failure: a later listing with budget left can still resolve this filter.
        return None
    keys = _swallowing_failure("group_key_resolution_failed", team, property_key, lambda: resolve(seconds))
    if keys is None:
        _swallowing_failure(
            "group_key_cache_write_failed",
            team,
            property_key,
            lambda: cache.set(cache_key, _FALLBACK, GROUP_KEY_FAILURE_TTL_SECONDS),
        )
        return None

    resolved: list[str] | None = None if len(keys) > MAX_RESOLVED_GROUP_KEYS else keys
    _swallowing_failure(
        "group_key_cache_write_failed",
        team,
        property_key,
        lambda: cache.set(cache_key, _FALLBACK if resolved is None else resolved, GROUP_KEY_CACHE_TTL_SECONDS),
    )
    return resolved


def _swallowing_failure(event: str, team: Team, property_key: str, work: Callable[[], Any]) -> Any:
    # Everything here is an optimisation over a join that already returns the right answer, so a
    # broken cache or an unavailable ClickHouse costs reads rather than failing the caller's query.
    try:
        return work()
    except Exception:
        logger.exception(event, team_id=team.pk, property_key=property_key)
        return None


def _resolution_predicate(team: Team, prop: GroupPropertyFilter) -> ast.Expr:
    """The filter's predicate, expressed against the `properties` of a select over `groups`."""
    numeric_op = _NUMERIC_OPERATORS.get(prop.operator)
    if numeric_op is not None:
        # A group property is stored as a JSON string, and the group-join path reaches it through a
        # typed field that carries the cast. Comparing the raw string to a number instead fails on
        # "no supertype for types String, Float64", so the cast has to be explicit here.
        return ast.CompareOperation(
            op=numeric_op,
            left=ast.Call(name="toFloat", args=[ast.Field(chain=["properties", prop.key])]),
            right=ast.Constant(value=float(cast(float | str, prop.value))),
        )
    # String operators need no cast, so reuse the event-property expression and keep their handling
    # in one place. Inside a select over `groups`, `properties` resolves to that table's latest values.
    return property_to_expr(
        EventPropertyFilter(key=prop.key, value=prop.value, operator=prop.operator),
        team=team,
        scope="event",
    )


def _query_group_keys(
    team: Team,
    group_type_index: int,
    predicate: ast.Expr,
    ch_user: ClickHouseUser,
    user: User | None,
    max_seconds: int,
) -> list[str]:
    query = ast.SelectQuery(
        select=[ast.Field(chain=["key"])],
        select_from=ast.JoinExpr(table=ast.Field(chain=["groups"])),
        where=ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["index"]),
                    right=ast.Constant(value=group_type_index),
                ),
                predicate,
            ]
        ),
        # One over the ceiling, so an over-broad filter is recognised without materialising the rest.
        limit=ast.Constant(value=MAX_RESOLVED_GROUP_KEYS + 1),
    )
    response = execute_hogql_query(
        query=query,
        team=team,
        query_type=GROUP_KEY_RESOLUTION_QUERY_TYPE,
        ch_user=ch_user,
        user=user,
        # Types `properties.x` from this group type's property definitions, as the join path types `group_N.properties.x`.
        context=HogQLContext(team_id=team.pk, user=user, globals={"group_id": group_type_index}),
        # Throw rather than break, so a lookup that runs out of time falls back instead of caching a partial key list.
        settings=HogQLGlobalSettings(max_execution_time=max_seconds, timeout_overflow_mode="throw"),
    )
    return [row[0] for row in (response.results or []) if row[0]]


def _cast_keys(cached: Any) -> list[str]:
    return [str(key) for key in cached]


def _cache_key(team: Team, parts: list[Any]) -> str:
    payload = json.dumps(parts, sort_keys=True, default=str)
    return f"group-keys:{team.pk}:{hashlib.sha256(payload.encode()).hexdigest()}"
