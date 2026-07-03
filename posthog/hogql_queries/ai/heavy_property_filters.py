"""Route property filters on heavy AI properties to the dedicated ai_events table.

Ingestion strips the heavy AI content properties ($ai_input, $ai_output_choices, ...)
from the events-table copy of AI events and stores them as dedicated columns on
`posthog.ai_events` (see nodejs/src/ingestion/common/steps/event-processing/
split-ai-events-step.ts). A property filter like `$ai_output_choices icontains "x"`
evaluated against `events.properties` can therefore never match.

The helpers here rewrite such filters into an IN subquery against ai_events, anchored
on `uuid` (per-event lists, e.g. the generations tab) or `trace_id` (trace-level
lists). All heavy filters land in a single subquery so they must match on the same
ai_events row, mirroring how ANDed property filters behave against a single events row.

ai_events rows expire after their retention TTL, so content filters only match events
still inside that window — older events are excluded from filtered results entirely.
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


def _heavy_property_condition(prop: EventPropertyFilter, team: Team) -> ast.Expr:
    # Heavy columns are Nullable(String); absent content is NULL. property_to_expr compiles
    # is_set/is_not_set to `!= NULL` / `= NULL`, which never matches once rewritten onto the
    # column, so map those to notEmpty()/empty() over the NULL-normalized column instead.
    if prop.operator in (PropertyOperator.IS_SET, PropertyOperator.IS_NOT_SET):
        normalized = ast.Call(
            name="ifNull",
            args=[ast.Field(chain=[AI_PROPERTY_TO_COLUMN[prop.key]]), ast.Constant(value="")],
        )
        return ast.Call(name="notEmpty" if prop.operator == PropertyOperator.IS_SET else "empty", args=[normalized])
    return rewrite_expr_for_ai_events_table(property_to_expr(prop, team))


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
    """Build `<anchor> IN (SELECT <select_column> FROM posthog.ai_events WHERE ...)`.

    `event_names` and the date bounds should mirror the outer query's filters so the
    ai_events scan is pruned to the same window.
    """
    conditions: list[ast.Expr] = [_heavy_property_condition(prop, team) for prop in heavy_properties]
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

    subquery = ast.SelectQuery(
        distinct=distinct or None,
        select=[ast.Field(chain=[select_column])],
        select_from=ast.JoinExpr(table=ast.Field(chain=["posthog", "ai_events"])),
        where=ast.And(exprs=conditions) if len(conditions) > 1 else conditions[0],
    )
    return ast.CompareOperation(op=ast.CompareOperationOp.In, left=anchor, right=subquery)
