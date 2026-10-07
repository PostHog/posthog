from datetime import timedelta
from typing import Any

from parameterized import parameterized

from products.ai_observability.backend.logic.traces.person import trace_distinct_id

from .rows import T0, make_row


@parameterized.expand(
    [
        (
            "the trace event wins over earlier events",
            [
                {"distinct_id": "span-user"},
                {"event": "$ai_trace", "distinct_id": "trace-user", "timestamp": T0 + timedelta(seconds=1)},
            ],
            "trace-user",
        ),
        (
            "otherwise the earliest event",
            [{"distinct_id": "late", "timestamp": T0 + timedelta(seconds=1)}, {"distinct_id": "early"}],
            "early",
        ),
        (
            "empty distinct ids are skipped",
            [
                {"event": "$ai_trace", "distinct_id": ""},
                {"distinct_id": "span-user", "timestamp": T0 + timedelta(seconds=1)},
            ],
            "span-user",
        ),
        ("no distinct id", [{"distinct_id": ""}], None),
    ]
)
def test_trace_distinct_id(_name: str, rows: list[dict[str, Any]], expected: str | None) -> None:
    assert trace_distinct_id([make_row(**row) for row in rows]) == expected
