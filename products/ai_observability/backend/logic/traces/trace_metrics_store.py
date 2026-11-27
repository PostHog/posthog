import hashlib
from dataclasses import replace
from typing import Any, Literal, cast

from django.core.cache import cache

from pydantic import TypeAdapter, ValidationError

from posthog.models import Team, User

from . import trace_metrics_queries, trace_selection_queries
from .summary_store import requester_fingerprint
from .trace_metrics import BucketSize
from .trace_metrics_queries import TraceMetricsRows, TraceMetricsTooHeavyError
from .trace_selection import TraceSelection, TraceWindow

TRACE_METRICS_CACHE_SECONDS = 300

_TOO_HEAVY: Literal["too_heavy"] = "too_heavy"
_Entry = TraceMetricsRows | Literal["too_heavy"]
_ENTRY = TypeAdapter[_Entry](cast(Any, _Entry))


def _cache_key(name: str, team: Team, user: User, selection: TraceSelection, *details: str) -> str:
    # A relative range ends at now, so refreshes within a minute share one read. Keying on the bucket instead would
    # serve a window that ended up to a bucket earlier than the one asked for.
    window = selection.window
    by_minute = replace(
        selection,
        window=TraceWindow(
            start=window.start.replace(second=0, microsecond=0), end=window.end.replace(second=0, microsecond=0)
        ),
    )
    selection_hash = hashlib.sha256(repr(by_minute).encode()).hexdigest()
    # A test account filter can read a warehouse table that only some people may read, and a cache hit skips that
    # access check, so each person reads only the entries their own reads wrote.
    requester = f"{user.pk}:{requester_fingerprint(team.pk, user)}"
    return ":".join(["ai_observability", name, str(team.pk), selection_hash, *details, requester])


def metrics_cache_key(team: Team, user: User, selection: TraceSelection, size: BucketSize) -> str:
    # Two windows within the same minutes can straddle the span that switches hourly buckets to daily ones.
    return _cache_key("trace_metrics", team, user, selection, size.value)


def _read(key: str) -> _Entry | None:
    value = cache.get(key)
    if not isinstance(value, str | bytes):
        return None
    try:
        return _ENTRY.validate_json(value)
    except ValidationError:
        return None


def _write(key: str, entry: _Entry) -> None:
    cache.set(key, _ENTRY.dump_json(entry).decode(), TRACE_METRICS_CACHE_SECONDS)


def cached_trace_metrics(team: Team, user: User, selection: TraceSelection, size: BucketSize) -> TraceMetricsRows:
    """Reads the metrics through a short cache. A range too long to compute is cached the same way, so a repeat visit
    gets the refusal without running the read again. Raises `TraceMetricsTooHeavyError` for that range."""
    key = metrics_cache_key(team, user, selection, size)
    cached = _read(key)
    if cached == _TOO_HEAVY:
        raise TraceMetricsTooHeavyError()
    if isinstance(cached, TraceMetricsRows):
        return cached
    try:
        rows = trace_metrics_queries.load_trace_metrics(team, user, selection, size)
    except TraceMetricsTooHeavyError:
        _write(key, _TOO_HEAVY)
        raise
    _write(key, rows)
    return rows


def cached_trace_count(team: Team, user: User, selection: TraceSelection, size: BucketSize) -> int:
    """The selection's trace count, from the metrics a recent read cached, else through a short cache of its own. Its
    own read counts the traces alone, so a range too heavy for the metrics still gets its count."""
    metrics = _read(metrics_cache_key(team, user, selection, size))
    if isinstance(metrics, TraceMetricsRows):
        return metrics.current.traces
    key = _cache_key("trace_count", team, user, selection)
    cached = cache.get(key)
    if isinstance(cached, int):
        return cached
    count = trace_selection_queries.load_trace_count(team, user, selection)
    cache.set(key, count, TRACE_METRICS_CACHE_SECONDS)
    return count
