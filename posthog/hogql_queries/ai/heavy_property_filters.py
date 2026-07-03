"""Route filters on heavy AI content properties to the dedicated ai_events table.

Ingestion strips the heavy AI properties ($ai_input, $ai_output_choices, ...) from the
events-table copy of AI events into dedicated columns on `posthog.ai_events`, so a filter
on them against `events.properties` never matches. These helpers rewrite such filters into
subqueries against ai_events, anchored on `uuid` (per-event) or `trace_id` (per-trace).
"""

from collections.abc import Sequence
from datetime import datetime
from typing import TypeVar

from posthog.schema import EventPropertyFilter, PropertyOperator

from posthog.hogql import ast
from posthog.hogql.property import property_to_expr

from posthog.hogql_queries.ai.ai_property_rewriter import AI_PROPERTY_TO_COLUMN, rewrite_expr_for_ai_events_table
from posthog.hogql_queries.ai.utils import HEAVY_COLUMN_TO_PROPERTY
from posthog.models.team.team import Team

HEAVY_AI_PROPERTY_KEYS: frozenset[str] = frozenset(HEAVY_COLUMN_TO_PROPERTY.values())

# Negated operators resolve as an anti-join against their positive counterpart
# (`anchor NOT IN <events matching the positive>`) instead of a semi-join on the negated
# predicate. ai_events has no row-level dedup, so one event can have several rows with the
# heavy column populated on some and empty on others; a semi-join on e.g. `NOT ILIKE` would
# match the empty duplicate of every event, whereas the anti-join excludes only events that
# have a matching row — the correct "does not contain" / "is not set" semantics.
_POSITIVE_COUNTERPART: dict[PropertyOperator, PropertyOperator] = {
    PropertyOperator.IS_NOT_SET: PropertyOperator.IS_SET,
    PropertyOperator.NOT_ICONTAINS: PropertyOperator.ICONTAINS,
    PropertyOperator.IS_NOT: PropertyOperator.EXACT,
    PropertyOperator.NOT_REGEX: PropertyOperator.REGEX,
}

_PropertyFilterT = TypeVar("_PropertyFilterT")


def split_heavy_ai_property_filters(
    properties: Sequence[_PropertyFilterT] | None,
) -> tuple[list[EventPropertyFilter], list[_PropertyFilterT]]:
    """Split property filters into (heavy AI content filters, everything else)."""
    heavy: list[EventPropertyFilter] = []
    regular: list[_PropertyFilterT] = []
    for prop in properties or []:
        if isinstance(prop, EventPropertyFilter) and prop.key in HEAVY_AI_PROPERTY_KEYS:
            heavy.append(prop)
        else:
            regular.append(prop)
    return heavy, regular


def _positive_predicate(prop: EventPropertyFilter, team: Team) -> ast.Expr:
    # Heavy columns are Nullable; property_to_expr compiles is_set to `!= NULL`, which never
    # matches a Nullable column, so use notEmpty() over the NULL-normalized column instead.
    if prop.operator == PropertyOperator.IS_SET:
        normalized = ast.Call(
            name="ifNull",
            args=[ast.Field(chain=[AI_PROPERTY_TO_COLUMN[prop.key]]), ast.Constant(value="")],
        )
        return ast.Call(name="notEmpty", args=[normalized])
    return rewrite_expr_for_ai_events_table(property_to_expr(prop, team))


def _scope_conditions(
    event_names: Sequence[str] | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> list[ast.Expr]:
    conditions: list[ast.Expr] = []
    if event_names:
        if len(event_names) == 1:
            conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["event"]),
                    right=ast.Constant(value=event_names[0]),
                )
            )
        else:
            conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["event"]),
                    right=ast.Tuple(exprs=[ast.Constant(value=name) for name in event_names]),
                )
            )
    if date_from is not None:
        conditions.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=date_from),
            )
        )
    if date_to is not None:
        conditions.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=date_to),
            )
        )
    return conditions


def _ai_events_subquery(select_column: str, conditions: list[ast.Expr], distinct: bool) -> ast.SelectQuery:
    return ast.SelectQuery(
        distinct=distinct or None,
        select=[ast.Field(chain=[select_column])],
        select_from=ast.JoinExpr(table=ast.Field(chain=["posthog", "ai_events"])),
        where=ast.And(exprs=conditions) if len(conditions) > 1 else conditions[0],
    )


def heavy_ai_properties_in_expr(
    *,
    anchor: ast.Expr,
    select_column: str,
    heavy_properties: Sequence[EventPropertyFilter],
    team: Team,
    event_names: Sequence[str] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    distinct: bool = False,
) -> ast.Expr:
    """Resolve heavy AI content filters against ai_events, returning a single expr.

    Positive filters become one semi-join `<anchor> IN (SELECT <select_column> ... WHERE ...)`
    (all positives must match the same ai_events row). Each negated filter becomes its own
    anti-join `<anchor> NOT IN (SELECT ... WHERE <positive counterpart>)`. `event_names` and
    the date bounds mirror the outer query's filters so each ai_events scan is pruned.
    """
    scope = _scope_conditions(event_names, date_from, date_to)

    positive = [prop for prop in heavy_properties if prop.operator not in _POSITIVE_COUNTERPART]
    negative = [prop for prop in heavy_properties if prop.operator in _POSITIVE_COUNTERPART]

    exprs: list[ast.Expr] = []
    if positive:
        conditions = [_positive_predicate(prop, team) for prop in positive] + scope
        exprs.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=anchor,
                right=_ai_events_subquery(select_column, conditions, distinct),
            )
        )
    for prop in negative:
        counterpart = prop.model_copy(update={"operator": _POSITIVE_COUNTERPART[prop.operator]})
        conditions = [_positive_predicate(counterpart, team), *scope]
        exprs.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.NotIn,
                left=anchor,
                right=_ai_events_subquery(select_column, conditions, distinct),
            )
        )

    return ast.And(exprs=exprs) if len(exprs) > 1 else exprs[0]
