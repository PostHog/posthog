from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import IO, Self

from posthog.dataclasses import frozen

from ...facade.contracts import TraceExportStatus

TRACE_EXPORT_KIND = "llm_trace"
TRACE_EXPORT_FORMAT = "application/json"
TRACE_EXPORT_TTL = timedelta(days=7)
TRACE_EXPORT_NODE_BATCH_SIZE = 20
MAX_TRACE_EXPORT_MEGABYTES = 250
MAX_TRACE_EXPORT_BYTES = MAX_TRACE_EXPORT_MEGABYTES * 1_000_000
# The largest file the export row may hold when object storage is off or fails.
TRACE_EXPORT_DATABASE_FALLBACK_BYTES = 50_000_000
TRACE_EXPORT_STUCK_MESSAGE = "This export took too long to finish. Try again."


class InvalidTraceExportRequestError(ValueError):
    pass


class TraceExportTooLargeError(Exception):
    pass


@frozen
class TraceExportRequest:
    trace_id: str
    timestamp_hint: datetime | None

    @classmethod
    def from_context(cls, context: Mapping[str, object]) -> Self:
        trace_id = context.get("trace_id")
        if context.get("kind") != TRACE_EXPORT_KIND or not isinstance(trace_id, str) or not trace_id:
            raise InvalidTraceExportRequestError("The export context does not name a trace.")
        hint = context.get("timestamp_hint")
        if hint is None:
            return cls(trace_id=trace_id, timestamp_hint=None)
        if not isinstance(hint, str):
            raise InvalidTraceExportRequestError("The export context has a malformed timestamp hint.")
        try:
            return cls(trace_id=trace_id, timestamp_hint=datetime.fromisoformat(hint))
        except ValueError as error:
            raise InvalidTraceExportRequestError("The export context has a malformed timestamp hint.") from error

    def to_context(self) -> dict[str, object]:
        return {
            "kind": TRACE_EXPORT_KIND,
            "trace_id": self.trace_id,
            "timestamp_hint": self.timestamp_hint.isoformat() if self.timestamp_hint is not None else None,
            "filename": f"trace-{self.trace_id[:64]}",
        }


@frozen
class TraceExportState:
    status: TraceExportStatus
    exception: str | None

    @classmethod
    def of(
        cls,
        *,
        has_content: bool,
        exception: str | None,
        failure_is_final: bool,
        created_at: datetime,
        now: datetime,
        stuck_after: timedelta,
    ) -> Self:
        past_deadline = now > created_at + stuck_after
        # The workflow retries a failure that is not final, and a later attempt clears the exception.
        if exception and (failure_is_final or past_deadline):
            return cls(status="failed", exception=exception)
        if has_content:
            return cls(status="complete", exception=None)
        # Nothing records a failure when the workflow dies, so an export without content past its deadline has failed.
        if past_deadline:
            return cls(status="failed", exception=TRACE_EXPORT_STUCK_MESSAGE)
        return cls(status="pending", exception=None)


class TraceExportWriter:
    """Writes `{"trace": ..., "nodes": [...]}` to a stream one node at a time, so the document never sits in memory."""

    def __init__(self, stream: IO[bytes], trace_json: str, *, truncated: bool, max_bytes: int) -> None:
        self._stream = stream
        self._max_bytes = max_bytes
        self._written = 0
        self._has_nodes = False
        self._write('{"trace":' + trace_json + ',"truncated":' + ("true" if truncated else "false") + ',"nodes":[')

    def add_node(self, node_json: str) -> None:
        self._write(("," if self._has_nodes else "") + node_json)
        self._has_nodes = True

    def close(self) -> None:
        self._write("]}")

    def _write(self, text: str) -> None:
        chunk = text.encode()
        if self._written + len(chunk) > self._max_bytes:
            raise TraceExportTooLargeError(self._max_bytes)
        self._stream.write(chunk)
        self._written += len(chunk)
