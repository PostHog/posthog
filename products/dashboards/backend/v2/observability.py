"""Spans and metrics for the `dashboard-v2` query batch.

The request span ends when the view returns the streaming response, before most of the work runs, so the stream gets
a span of its own, parented to the request's trace, and each target a span under it. A target's span is current while
it runs, so the ClickHouse and Snuffle spans the query makes nest under it, and the httpx instrumentation sends its
`traceparent` on to Snuffle.
"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from time import monotonic, time_ns
from typing import Any, Optional

from opentelemetry import (
    context as otel_context,
    trace,
)
from opentelemetry.trace import Span, StatusCode
from prometheus_client import Counter, Histogram

from posthog.dataclasses import frozen

from products.dashboards.backend.facade.contracts import QueryBatchInput
from products.dashboards.backend.facade.enums import QueryBatchLanguage

tracer = trace.get_tracer(__name__)

_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 60.0, 120.0, 300.0, 600.0, float("inf"))

TARGET_SECONDS = Histogram(
    "dashboard_v2_query_batch_target_seconds",
    "Time to answer one target of a dashboard-v2 query batch, from the start of its run or cache read",
    labelnames=["language", "query_kind", "cache", "outcome"],
    buckets=_BUCKETS,
)
STREAM_SECONDS = Histogram(
    "dashboard_v2_query_batch_stream_seconds",
    "Time a dashboard-v2 query batch spends streaming, from its first line to its last",
    labelnames=["outcome"],
    buckets=_BUCKETS,
)
TARGETS_TOTAL = Counter(
    "dashboard_v2_query_batch_targets_total",
    "Targets a dashboard-v2 query batch answered",
    labelnames=["language", "outcome"],
)

# Label values stay within these, so a client cannot mint series by sending new kinds.
_QUERY_KINDS = frozenset(
    {
        "TrendsQuery",
        "FunnelsQuery",
        "RetentionQuery",
        "PathsQuery",
        "StickinessQuery",
        "LifecycleQuery",
        "HogQLQuery",
        "EventsQuery",
        "ActorsQuery",
        "MetricsQuery",
        "LogsQuery",
        "TracesQuery",
        "WebOverviewQuery",
        "WebStatsTableQuery",
        "ErrorTrackingQuery",
    }
)
_WRAPPER_KINDS = frozenset({"InsightVizNode", "DataVisualizationNode", "DataTableNode", "BIVisualizationNode"})
_ERROR_PREFIX = b'"error":'


def language_label(language: QueryBatchLanguage) -> str:
    return QueryBatchLanguage.QUERY.value if language == QueryBatchLanguage.INSIGHT else language.value


def query_kind(query: Optional[dict[str, Any]], language: QueryBatchLanguage) -> str:
    if language == QueryBatchLanguage.LOGQL or not query:
        return "none"
    kind = query.get("kind")
    source = query.get("source")
    if kind in _WRAPPER_KINDS and isinstance(source, dict):
        kind = source.get("kind")
    return kind if kind in _QUERY_KINDS else "other"


def _target_attributes(item: QueryBatchInput, query_id: Optional[str]) -> dict[str, Any]:
    attributes: dict[str, Any] = {
        "dashboard_v2.language": language_label(item.target.language),
        "dashboard_v2.ref_id": item.target.ref_id,
    }
    if item.tile is not None:
        attributes["dashboard_v2.tile"] = item.tile
    if query_id is not None:
        attributes["dashboard_v2.client_query_id"] = query_id
    return attributes


@frozen
class _Answer:
    cache: str
    outcome: str


def _describe(span: Span, line: dict[str, Any]) -> _Answer:
    """Sets what a target's line says on its span, and returns its labels. An error's text is left off: it can quote
    the query, and `note_error` has already named its type."""
    if "error" in line:
        span.set_status(StatusCode.ERROR)
        return _Answer(cache="miss", outcome="error")
    result = line.get("result") or {}
    cache = result.get("cache") or {}
    hit, stale = bool(cache.get("hit")), bool(cache.get("stale"))
    span.set_attribute("cache.hit", hit)
    span.set_attribute("cache.stale", stale)
    span.set_attribute("dashboard_v2.truncated", bool(line.get("truncated")))
    frames = result.get("frames")
    if isinstance(frames, list):
        span.set_attribute("dashboard_v2.frames", len(frames))
        span.set_attribute(
            "dashboard_v2.points",
            sum(
                len(field.get("values") or ())
                for frame in frames
                if isinstance(frame, dict)
                for field in frame.get("fields") or ()
                if isinstance(field, dict) and field.get("type") != "time"
            ),
        )
    rows = (result.get("result") or {}).get("results") if isinstance(result.get("result"), dict) else None
    if isinstance(rows, list):
        span.set_attribute("dashboard_v2.rows", len(rows))
    if result.get("result") is None and "frames" not in result:
        return _Answer(cache="miss", outcome="ok")
    return _Answer(cache=("stale" if stale else "hit") if hit else "miss", outcome="ok")


def _observe(language: str, kind: str, cache: str, outcome: str, seconds: float) -> None:
    TARGET_SECONDS.labels(language=language, query_kind=kind, cache=cache, outcome=outcome).observe(seconds)
    TARGETS_TOTAL.labels(language=language, outcome=outcome).inc()


def count_answer(language: str, *, error: bool) -> None:
    """Counts a target answered without running or reading the cache itself: a miss on a cache-only read, a panel
    sharing another's entry, a target that failed validation, or one turned away as the batch was busy."""
    TARGETS_TOTAL.labels(language=language, outcome="error" if error else "ok").inc()


class TargetRun:
    """A target being run in a worker thread. `finish` records the line it answered with."""

    def __init__(self, span: Span, language: str, kind: str) -> None:
        self.span = span
        self._language = language
        self._kind = kind
        self._started = monotonic()
        self._answer: Optional[_Answer] = None

    def finish(self, line: dict[str, Any], *, cancelled: bool) -> None:
        """Takes the line as sent, after any size limit has replaced it."""
        answer = _describe(self.span, line)
        if cancelled and answer.outcome == "error":
            answer = _Answer(cache=answer.cache, outcome="cancelled")
        self._answer = answer

    def _end(self) -> None:
        answer = self._answer or _Answer(cache="miss", outcome="cancelled")
        self.span.set_attribute("dashboard_v2.outcome", answer.outcome)
        _observe(self._language, self._kind, answer.cache, answer.outcome, monotonic() - self._started)


class StreamTrace:
    """The span of one batch's stream. Workers run their targets under it with `target`."""

    def __init__(self, *, team_id: int, dashboard_id: Optional[int]) -> None:
        # Built while the request's span is current. The stream runs after the request has reset its context, and
        # worker threads and the event loop never had it.
        self._parent = otel_context.get_current()
        self._team_id = team_id
        self._dashboard_id = dashboard_id
        self._span: Optional[Span] = None
        self._context: Optional[otel_context.Context] = None
        self._started = 0.0
        self.lines_ok = 0
        self.lines_error = 0

    def start(self, *, targets: int, admission_wait_ms: float) -> None:
        attributes: dict[str, Any] = {
            "team_id": self._team_id,
            "dashboard_v2.targets": targets,
            "dashboard_v2.admission_wait_ms": round(admission_wait_ms, 1),
        }
        if self._dashboard_id is not None:
            attributes["dashboard_id"] = self._dashboard_id
        self._span = tracer.start_span("dashboard_v2.query_batch.stream", context=self._parent, attributes=attributes)
        self._context = trace.set_span_in_context(self._span, self._parent)
        self._started = monotonic()

    def line(self, chunk: bytes, heads: Sequence[bytes]) -> None:
        """Counts a line the stream wrote. Heartbeats are skipped. A line is `{"i":N,<head>,<body>` and an error
        body starts with `"error":`, so the error check reads only the bytes after the head."""
        if not chunk.startswith(b'{"i":'):
            return
        end = chunk.find(b",", 5)
        try:
            index = int(chunk[5:end])
            offset = end + 1 + len(heads[index]) + 1
        except (ValueError, IndexError):
            return
        if chunk[offset : offset + len(_ERROR_PREFIX)] == _ERROR_PREFIX:
            self.lines_error += 1
        else:
            self.lines_ok += 1

    def end(self, *, complete: bool) -> None:
        span, self._span = self._span, None
        if span is None:
            return
        outcome = "cancelled" if not complete else ("error" if self.lines_error else "ok")
        span.set_attribute("dashboard_v2.lines_ok", self.lines_ok)
        span.set_attribute("dashboard_v2.lines_error", self.lines_error)
        span.set_attribute("dashboard_v2.cancelled", not complete)
        span.end()
        STREAM_SECONDS.labels(outcome=outcome).observe(monotonic() - self._started)

    def queue_wait_ms(self) -> float:
        return (monotonic() - self._started) * 1000 if self._started else 0.0

    @contextmanager
    def target(self, item: QueryBatchInput, query_id: str, query: Optional[dict[str, Any]]) -> Iterator[TargetRun]:
        """A target's span, current for the block, so the work inside nests under it in this thread."""
        language = language_label(item.target.language)
        kind = query_kind(query, item.target.language)
        attributes = _target_attributes(item, query_id)
        attributes["dashboard_v2.query_kind"] = kind
        attributes["dashboard_v2.queue_wait_ms"] = round(self.queue_wait_ms(), 1)
        with tracer.start_as_current_span(
            "dashboard_v2.query_batch.target",
            context=self._context or self._parent,
            attributes=attributes,
            record_exception=False,
        ) as span:
            run = TargetRun(span, language, kind)
            try:
                yield run
            finally:
                run._end()


@contextmanager
def phase(name: str, **attributes: Any) -> Iterator[None]:
    """A phase of the current target: `plan`, `cache_read`, `execute` or `frames`."""
    # Exceptions are not recorded: their messages can quote the query. The target's span names the type instead.
    with tracer.start_as_current_span(
        f"dashboard_v2.query_batch.{name}",
        attributes=attributes or None,
        record_exception=False,
        set_status_on_exception=False,
    ):
        yield


def record_cache_hit(
    item: QueryBatchInput, query: Optional[dict[str, Any]], line: dict[str, Any], started: float
) -> None:
    """A target answered from the cache while the request was planning, as a span from `started` (monotonic) until
    now under the request's span. `line` is the one sent, after any size limit has replaced it."""
    elapsed = monotonic() - started
    language = language_label(item.target.language)
    kind = query_kind(query, item.target.language)
    attributes = _target_attributes(item, None)
    attributes["dashboard_v2.query_kind"] = kind
    span = tracer.start_span(
        "dashboard_v2.query_batch.target", attributes=attributes, start_time=time_ns() - int(elapsed * 1e9)
    )
    answer = _describe(span, line)
    span.set_attribute("dashboard_v2.outcome", answer.outcome)
    span.end()
    _observe(language, kind, answer.cache, answer.outcome, elapsed)


def note_error(error: BaseException) -> None:
    """Names the error a target failed with on the current span, without its message."""
    span = trace.get_current_span()
    if span.is_recording():
        span.set_attribute("error.type", type(error).__name__)
