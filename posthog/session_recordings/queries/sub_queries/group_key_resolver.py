"""Turn a group property filter into the set of group keys it matches, so events queries can filter
on the `$group_N` column instead of joining the groups table.

The join reads every group row's `group_properties` JSON, and ClickHouse pushes it into the per-shard
events subquery, so each shard pays that scan independently. Resolving the keys once and filtering on
a column instead is measurably cheaper and returns the same sessions.
"""

import json
import hashlib
from typing import Any

from django.core.cache import cache

import structlog

from posthog.schema import EventPropertyFilter, GroupPropertyFilter, PropertyOperator

from posthog.hogql import ast
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team

logger = structlog.get_logger(__name__)

GROUP_KEY_RESOLUTION_QUERY_TYPE = "GroupKeyResolutionQuery"

# Group membership changes on a human timescale, while a scanner sweeps every few minutes.
GROUP_KEY_CACHE_TTL_SECONDS = 3600

# Past this the key list stops being cheaper than the join, and it starts crowding `max_query_size`.
MAX_RESOLVED_GROUP_KEYS = 10_000

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

_FALLBACK = "fallback"


def resolved_group_key_expr(team: Team, prop: GroupPropertyFilter) -> ast.Expr | None:
    """`$group_N IN (keys)` for this filter, or None when the caller should keep the join."""
    if prop.operator not in _RESOLVABLE_OPERATORS or prop.group_type_index is None:
        return None

    keys = _group_keys(team, prop)
    if keys is None:
        return None

    return ast.CompareOperation(
        op=ast.CompareOperationOp.In,
        left=ast.Field(chain=["events", f"$group_{prop.group_type_index}"]),
        right=ast.Constant(value=keys),
    )


def _group_keys(team: Team, prop: GroupPropertyFilter) -> list[str] | None:
    cache_key = _cache_key(team, prop)
    cached = cache.get(cache_key)
    if cached == _FALLBACK:
        return None
    if cached is not None:
        return _cast_keys(cached)

    try:
        keys = _query_group_keys(team, prop)
    except Exception:
        # The join still produces the right answer, so a resolution failure costs reads, not results.
        logger.exception("group_key_resolution_failed", team_id=team.pk, property_key=prop.key)
        return None

    resolved: list[str] | None = None if len(keys) > MAX_RESOLVED_GROUP_KEYS else keys
    cache.set(cache_key, _FALLBACK if resolved is None else resolved, GROUP_KEY_CACHE_TTL_SECONDS)
    return resolved


def _query_group_keys(team: Team, prop: GroupPropertyFilter) -> list[str]:
    # Reuse the event-property expression so operator handling stays in one place; inside a select
    # over `groups` the `properties` chain resolves to that table's latest properties.
    predicate = property_to_expr(
        EventPropertyFilter(key=prop.key, value=prop.value, operator=prop.operator),
        team=team,
        scope="event",
    )
    query = ast.SelectQuery(
        select=[ast.Field(chain=["key"])],
        select_from=ast.JoinExpr(table=ast.Field(chain=["groups"])),
        where=ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["index"]),
                    right=ast.Constant(value=prop.group_type_index),
                ),
                predicate,
            ]
        ),
        # One over the ceiling, so an over-broad filter is recognised without materialising the rest.
        limit=ast.Constant(value=MAX_RESOLVED_GROUP_KEYS + 1),
    )
    response = execute_hogql_query(query=query, team=team, query_type=GROUP_KEY_RESOLUTION_QUERY_TYPE)
    return [row[0] for row in (response.results or []) if row[0]]


def _cast_keys(cached: Any) -> list[str]:
    return [str(key) for key in cached]


def _cache_key(team: Team, prop: GroupPropertyFilter) -> str:
    payload = json.dumps(
        [prop.group_type_index, prop.key, prop.operator, prop.value],
        sort_keys=True,
        default=str,
    )
    return f"group-keys:{team.pk}:{hashlib.sha256(payload.encode()).hexdigest()}"
