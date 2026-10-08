from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .trace_queries import TraceEventRow


def trace_distinct_id(rows: Sequence["TraceEventRow"]) -> str | None:
    identified = sorted(
        (row for row in rows if row.distinct_id),
        key=lambda row: (row.event != "$ai_trace", row.timestamp),
    )
    return identified[0].distinct_id if identified else None
