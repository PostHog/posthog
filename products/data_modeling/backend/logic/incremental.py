"""Incremental materialization config, fingerprinting, and watermark persistence.

A materialized view normally recomputes its whole query on every run. When a saved query
declares an incremental config, the materialization instead filters the query down to rows
whose ``incremental_key`` has advanced past the last run's watermark, and upserts the result
into the existing Delta table keyed on ``unique_key``.

Correctness rests on one property: every output row a run touches is recomputed in full.
That holds because the injected filter targets the key's *defining expression* rather than a
raw source timestamp (see ``incremental_filter``), so a grouped bucket is either untouched or
rebuilt from all of its source rows. It is what lets any aggregate be incrementalized here,
including non-associative ones that other systems have to reject.
"""

import json
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Optional

from django.db import transaction

from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import clear_locations

DEFAULT_LOOKBACK_SECONDS = 0

# Guards against a config that would make every run re-read most of history. Any larger window
# is better served by a full refresh, which at least produces a table with no stale rows.
MAX_LOOKBACK_SECONDS = 60 * 60 * 24 * 30


@dataclass(frozen=True, kw_only=True, slots=True)
class IncrementalConfig:
    """The user-declared half of an incremental view."""

    incremental_key: str
    unique_key: tuple[str, ...]
    lookback_seconds: int = DEFAULT_LOOKBACK_SECONDS

    def canonical(self) -> dict[str, Any]:
        """Fingerprint input. Order-insensitive for unique_key, since reordering it changes nothing.

        Deliberately excludes lookback_seconds: it is operational, not definitional. It changes how
        far future runs re-read, not what the stored rows mean, and rows arriving later than any
        lookback are best-effort by design. Widening it does not repair past gaps either way; the
        explicit rebuild action does.
        """
        return {
            "incremental_key": self.incremental_key,
            "unique_key": sorted(self.unique_key),
        }


@dataclass(frozen=True, kw_only=True, slots=True)
class IncrementalState:
    """The system-written half: how far the last successful run got."""

    watermark: Any = None
    watermark_type: Optional[str] = None
    definition_fingerprint: Optional[str] = None
    last_full_refresh_at: Optional[str] = None
    last_run_mode: Optional[str] = None


def get_incremental_config(saved_query) -> Optional[IncrementalConfig]:
    """Return the config only when it is enabled and complete. Anything malformed reads as off,
    so a half-written config degrades to a full refresh rather than failing a run."""
    raw = saved_query.incremental_config
    if not isinstance(raw, dict) or not raw.get("enabled"):
        return None

    incremental_key = raw.get("incremental_key")
    unique_key = raw.get("unique_key")
    if not isinstance(incremental_key, str) or not incremental_key:
        return None
    if not isinstance(unique_key, list) or not unique_key:
        return None
    if not all(isinstance(column, str) and column for column in unique_key):
        return None

    lookback = raw.get("lookback_seconds", DEFAULT_LOOKBACK_SECONDS)
    if not isinstance(lookback, int) or isinstance(lookback, bool) or lookback < 0:
        lookback = DEFAULT_LOOKBACK_SECONDS

    return IncrementalConfig(
        incremental_key=incremental_key,
        unique_key=tuple(unique_key),
        lookback_seconds=min(lookback, MAX_LOOKBACK_SECONDS),
    )


def get_incremental_state(saved_query) -> IncrementalState:
    raw = saved_query.incremental_state
    if not isinstance(raw, dict):
        return IncrementalState()
    return IncrementalState(
        watermark=raw.get("watermark"),
        watermark_type=raw.get("watermark_type"),
        definition_fingerprint=raw.get("definition_fingerprint"),
        last_full_refresh_at=raw.get("last_full_refresh_at"),
        last_run_mode=raw.get("last_run_mode"),
    )


def definition_fingerprint(query: dict | None, config: IncrementalConfig) -> Optional[str]:
    """Hash the query's parsed shape plus its incremental config.

    Deliberately the *parsed AST* rather than the raw SQL string, so reformatting, comments, and
    whitespace do not force a rebuild of a large table. Equally deliberately not the printed
    ClickHouse SQL: that embeds resolved settings and modifiers, so an unrelated change to the
    HogQL printer would invalidate every incremental view on the platform in one deploy.
    """
    sql = (query or {}).get("query")
    if not isinstance(sql, str):
        return None

    try:
        node = clear_locations(parse_select(sql))
    except Exception:
        # An unparseable query cannot be fingerprinted, and returning None routes the run to a
        # full refresh, which surfaces the parse error where the user can see it.
        return None

    # repr() of the cleared AST: HogQL nodes are dataclasses, so their repr is deterministic and
    # covers every field. With source locations cleared it is identical for two queries that
    # differ only in whitespace or comments.
    payload = json.dumps(
        {"ast": repr(node), "config": config.canonical()},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def window_start(state: IncrementalState, config: IncrementalConfig) -> Any:
    """The lower bound for this run: the stored watermark, deserialized, then pulled back by the
    lookback. Deserializing first is load-bearing: a persisted temporal watermark is an ISO
    string, and shifting has to happen on the datetime it encodes, not on the string.

    Only datetime watermarks can be shifted; a numeric or string key has no meaningful notion of
    "seconds earlier", so its lookback is ignored rather than guessed at.
    """
    watermark = deserialize_watermark(state.watermark, state.watermark_type)
    if watermark is None:
        return None
    if config.lookback_seconds and isinstance(watermark, datetime):
        return watermark - timedelta(seconds=config.lookback_seconds)
    return watermark


def set_incremental_state(saved_query, *, watermark: Any, fingerprint: Optional[str], mode: str) -> None:
    """Row-locked read-modify-write of the state blob.

    Locked and re-read because the API can be writing ``incremental_config`` on the same row while
    a materialization is running; ``update_fields`` then keeps this write off every other column.
    """
    model = type(saved_query)
    watermark = _clamp_temporal_watermark(watermark)
    with transaction.atomic():
        locked = model.objects.select_for_update().get(pk=saved_query.pk)
        state = dict(locked.incremental_state or {})
        state["last_run_mode"] = mode
        if mode == "full_refresh":
            state["last_full_refresh_at"] = _isoformat(watermark_now())
        if watermark is not None:
            state["watermark"] = _serialize_watermark(watermark)
            state["watermark_type"] = _watermark_type(watermark)
        state["definition_fingerprint"] = fingerprint
        locked.incremental_state = state
        locked.save(update_fields=["incremental_state"])
    saved_query.incremental_state = state


def _clamp_temporal_watermark(watermark: Any) -> Any:
    """Capture accepts event timestamps up to ~23 hours in the future, so one future-dated row
    would advance the watermark past data that has not arrived yet, and later runs would skip the
    legitimate rows in between. Persisting at most "now" costs re-reading the future row's window
    once; skipping real data is silent loss."""
    if isinstance(watermark, datetime):
        try:
            return min(watermark, watermark_now())
        except TypeError:
            # Naive vs aware comparison. Keep the observed watermark rather than guess a timezone.
            return watermark
    if isinstance(watermark, date):
        return min(watermark, watermark_now().date())
    return watermark


def clear_incremental_state(saved_query) -> None:
    """Drop the watermark so the next run rebuilds from scratch. Used by a definition change, by
    an explicit full refresh, and by any engine failure we do not want to retry incrementally."""
    model = type(saved_query)
    with transaction.atomic():
        locked = model.objects.select_for_update().get(pk=saved_query.pk)
        state = dict(locked.incremental_state or {})
        state.pop("watermark", None)
        state.pop("watermark_type", None)
        state.pop("definition_fingerprint", None)
        locked.incremental_state = state
        locked.save(update_fields=["incremental_state"])
    saved_query.incremental_state = state


def watermark_now() -> datetime:
    from django.utils import timezone

    return timezone.now()


def _serialize_watermark(value: Any) -> Any:
    # `date` covers `datetime` too, since datetime subclasses it. A Date incremental key yields a
    # plain date, which the JSON field cannot store on its own.
    if isinstance(value, date):
        return _isoformat(value)
    return value


def _watermark_type(value: Any) -> Optional[str]:
    """The tag ``deserialize_watermark`` trusts. Written by the same code that serializes the
    value, so a string key whose values merely look like dates never comes back as a date."""
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, date):
        return "date"
    if isinstance(value, str):
        return "string"
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    return None


def _isoformat(value: date) -> str:
    return value.isoformat()


def _parse_iso(value: Any, parse: Callable[[str], Any]) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return parse(value)
    except ValueError:
        # A corrupted watermark reads as absent, which routes the run to a full refresh.
        return None


def deserialize_watermark(value: Any, watermark_type: Optional[str] = None) -> Any:
    """Rehydrate a JSON-stored watermark, strictly by its persisted type tag.

    Sniffing the value would be wrong here: a string incremental key such as
    ``toString(toDate(timestamp))`` produces values that look like dates, and turning one into a
    date would compare a Date constant against a String column on the next run.
    """
    if value is None:
        return None
    if watermark_type == "datetime":
        return _parse_iso(value, datetime.fromisoformat)
    if watermark_type == "date":
        return _parse_iso(value, date.fromisoformat)
    if watermark_type in ("int", "float", "string"):
        return value

    # No tag means the state predates the tag (pre-release dev state only — the feature has never
    # shipped without it). Reading it as absent costs one full refresh, which re-records a tagged
    # watermark; sniffing the value's type is exactly the guessing the tag exists to prevent.
    return None
