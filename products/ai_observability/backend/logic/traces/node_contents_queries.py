from collections.abc import Sequence
from datetime import datetime

from posthog.hogql import ast

from posthog.clickhouse.client.connection import Workload
from posthog.models import Team, User

from .trace_queries import (
    _NODE_COLUMNS,
    NODE_EVENT_NAMES,
    TraceNodeRow,
    _ai_events,
    _event_in,
    _filter_conditions,
    _read_trace,
    _trace_node_row,
    canonical_uuid,
)


def _nodes_query(event_uuids: Sequence[str]) -> ast.SelectQuery:
    return ast.SelectQuery(
        select=[ast.Field(chain=[column]) for column in _NODE_COLUMNS],
        select_from=_ai_events(),
        where=ast.And(
            exprs=[
                _event_in(NODE_EVENT_NAMES),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["uuid"]),
                    right=ast.Tuple(exprs=[ast.Constant(value=event_uuid) for event_uuid in event_uuids]),
                ),
                _filter_conditions(),
            ]
        ),
        limit_by=ast.LimitByExpr(n=ast.Constant(value=1), exprs=[ast.Field(chain=["uuid"])]),
        limit=ast.Constant(value=len(event_uuids)),
    )


def load_trace_nodes(
    team: Team,
    user: User | None,
    trace_id: str,
    node_ids: Sequence[str],
    timestamp_hint: datetime | None,
    *,
    workload: Workload = Workload.DEFAULT,
) -> list[TraceNodeRow]:
    """The content of each node of this trace in `node_ids`, in that order, skipping ids it does not hold.

    One read per call, so callers batch the ids. Like the single node read, it never widens to the unhinted
    events scan.
    """
    event_uuids = list(dict.fromkeys(uuid for node_id in node_ids if (uuid := canonical_uuid(node_id)) is not None))
    if not event_uuids:
        return []
    results = _read_trace(
        "ai_trace_nodes",
        lambda: _nodes_query(event_uuids),
        team,
        user,
        trace_id,
        timestamp_hint,
        widen_unhinted=False,
        workload=workload,
    )
    rows = {row.uuid: row for row in map(_trace_node_row, results)}
    return [rows[event_uuid] for event_uuid in event_uuids if event_uuid in rows]
