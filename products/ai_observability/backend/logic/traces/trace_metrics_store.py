import hashlib
from dataclasses import replace
from typing import Any, Literal, cast

from django.core.cache import cache

from pydantic import TypeAdapter, ValidationError

from posthog.models import Team, User

from . import trace_metrics_queries
from .summary_store import requester_fingerprint
from .trace_metrics import BucketSize
from .trace_metrics_queries import TraceMetricsRows, TraceMetricsTooHeavyError
from .trace_selection import TraceSelection, TraceWindow

TRACE_METRICS_CACHE_SECONDS = 300

_TOO_HEAVY: Literal["too_heavy"] = "too_heavy"
_Entry = TraceMetricsRows | Literal["too_heavy"]
_ENTRY = TypeAdapter[_Entry](cast(Any, _Entry))


def metrics_cache_key(team: Team, user: User, selection: TraceSelection, size: BucketSize) -> str:
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
    # Two windows within the same minutes can straddle the span that switches hourly buckets to daily ones.
    return f"ai_observability:trace_metrics:{team.pk}:{selection_hash}:{size.value}:{requester}"


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
