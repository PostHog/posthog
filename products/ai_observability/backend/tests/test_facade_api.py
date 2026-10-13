from datetime import UTC, datetime

import pytest
from unittest.mock import patch

from products.ai_observability.backend.facade import api
from products.ai_observability.backend.logic.traces.trace_queries import LoadedTrace

from .logic.traces.rows import make_row

T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


def test_root_node_is_the_trace_and_nodes_keep_event_uuids() -> None:
    rows = (
        make_row(uuid="span-uuid", span_id="span", timestamp=T0),
        make_row(uuid="gen-uuid", event="$ai_generation", parent_id="span", timestamp=T0),
    )
    with patch.object(api, "load_trace", return_value=LoadedTrace(rows=rows, person=None)):
        trace = api.get_trace(team=None, user=None, trace_id="trace-1", timestamp_hint=None)  # type: ignore[arg-type]

    root = trace.tree[0]
    assert (root.id, root.kind, root.name) == ("trace-1", "trace", "Trace")
    assert [(node.id, [child.id for child in node.children]) for node in root.children] == [("span-uuid", ["gen-uuid"])]
    assert [row.id for row in trace.timeline] == ["span-uuid", "gen-uuid"]


def test_missing_trace_raises_not_found() -> None:
    with patch.object(api, "load_trace", return_value=LoadedTrace(rows=(), person=None)):
        with pytest.raises(api.TraceNotFoundError):
            api.get_trace(team=None, user=None, trace_id="missing", timestamp_hint=None)  # type: ignore[arg-type]
