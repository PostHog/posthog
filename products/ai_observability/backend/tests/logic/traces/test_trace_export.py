import io
import json
from datetime import UTC, datetime, timedelta

import pytest

from parameterized import parameterized

from products.ai_observability.backend.logic.traces.trace_export import (
    TRACE_EXPORT_STUCK_MESSAGE,
    InvalidTraceExportRequestError,
    TraceExportRequest,
    TraceExportState,
    TraceExportTooLargeError,
    TraceExportWriter,
)

T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


@parameterized.expand([("with a hint", T0), ("without a hint", None)])
def test_the_request_round_trips_through_the_export_context(_name: str, timestamp_hint: datetime | None) -> None:
    request = TraceExportRequest(trace_id="a/b c", timestamp_hint=timestamp_hint)

    assert TraceExportRequest.from_context(json.loads(json.dumps(request.to_context()))) == request
    assert request.to_context()["filename"] == "trace-a/b c"


@parameterized.expand(
    [
        ("another kind", {"kind": "dataset", "trace_id": "trace-1"}),
        ("no trace id", {"kind": "llm_trace"}),
        ("an empty trace id", {"kind": "llm_trace", "trace_id": ""}),
        ("a malformed hint", {"kind": "llm_trace", "trace_id": "trace-1", "timestamp_hint": "yesterday"}),
    ]
)
def test_a_context_that_is_not_a_trace_export_is_refused(_name: str, context: dict[str, object]) -> None:
    with pytest.raises(InvalidTraceExportRequestError):
        TraceExportRequest.from_context(context)


@parameterized.expand(
    [
        ("content", True, None, True, 1, ("complete", None)),
        ("a final failure", False, "Boom", True, 1, ("failed", "Boom")),
        ("a final failure with content", True, "Boom", True, 1, ("failed", "Boom")),
        ("a failure the workflow retries", False, "Boom", False, 1, ("pending", None)),
        ("a retried failure past the deadline", False, "Boom", False, 61, ("failed", "Boom")),
        ("no content yet", False, None, True, 1, ("pending", None)),
        ("no content past the deadline", False, None, True, 61, ("failed", TRACE_EXPORT_STUCK_MESSAGE)),
    ]
)
def test_export_state(
    _name: str,
    has_content: bool,
    exception: str | None,
    failure_is_final: bool,
    minutes_old: int,
    expected: tuple[str, str | None],
) -> None:
    state = TraceExportState.of(
        has_content=has_content,
        exception=exception,
        failure_is_final=failure_is_final,
        created_at=T0,
        now=T0 + timedelta(minutes=minutes_old),
        stuck_after=timedelta(minutes=60),
    )

    assert (state.status, state.exception) == expected


@parameterized.expand(
    [("nodes", ['{"id":"a"}', '{"id":"b"}'], False), ("no nodes", [], False), ("a truncated trace", [], True)]
)
def test_the_writer_streams_one_json_document(_name: str, nodes: list[str], truncated: bool) -> None:
    stream = io.BytesIO()
    writer = TraceExportWriter(stream, '{"id":"trace-1"}', truncated=truncated, max_bytes=1_000)
    for node in nodes:
        writer.add_node(node)
    writer.close()

    assert json.loads(stream.getvalue()) == {
        "trace": {"id": "trace-1"},
        "truncated": truncated,
        "nodes": [json.loads(node) for node in nodes],
    }


def test_the_writer_stops_at_the_byte_cap() -> None:
    writer = TraceExportWriter(io.BytesIO(), '{"id":"trace-1"}', truncated=False, max_bytes=60)

    with pytest.raises(TraceExportTooLargeError):
        writer.add_node(json.dumps({"content": "x" * 100}))
