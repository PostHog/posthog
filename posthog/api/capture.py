"""capture_internal — batch-native client for the v1 analytics capture endpoint.

This module provides the PREFERRED method for publishing analytics events from the Django
app on behalf of customer teams/projects.  PLEASE DO NOT write events directly to
ingestion Kafka topics — USE THIS!  The capture-rs pipeline handles deduplication,
quotas, billing, and routing; bypassing it creates safety and correctness problems.

NOTE: This is for submitting events ON BEHALF OF A CUSTOMER TEAM.  It is NOT for
submitting SDK-style internal telemetry events for PostHog's own team (team 2) — the
posthoganalytics SDK integration handles that separately.

Session replay events ($snapshot, $performance_event, $snapshot_items) are NOT SUPPORTED.
They are rejected client-side with CaptureInternalError.  Real replay ingestion flows
through SDKs directly to the capture-rs /s/ endpoint.

Targets ``/i/v1/analytics/events`` (capture-rs v1).  Typed ``event.options`` replaces
the legacy property-stuffing pattern, and legacy ``$``-keys are defensively stripped so
capture-rs's blind property splicing never produces duplicate keys.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Optional
from uuid import uuid4

import structlog
from prometheus_client import Counter
from requests.adapters import HTTPAdapter, Retry
from requests.exceptions import RequestException

from posthog.security.outbound_proxy import internal_requests_session
from posthog.settings.ingestion import (
    CAPTURE_INTERNAL_BATCH_CHUNK_SIZE,
    CAPTURE_INTERNAL_MAX_WORKERS,
    CAPTURE_INTERNAL_URL,
    CAPTURE_V1_INTERNAL_ENDPOINT,
    CAPTURE_V1_INTERNAL_MAX_ATTEMPTS,
    CAPTURE_V1_INTERNAL_RETRY_AFTER_CAP_SECONDS,
)

logger = structlog.get_logger(__name__)

# --------------------------------------------------------------------------- #
# Replay event names — shared constant for client-side rejection
# --------------------------------------------------------------------------- #

SESSION_RECORDING_DEDICATED_KAFKA_EVENTS = ("$snapshot_items",)
SESSION_RECORDING_EVENT_NAMES = ("$snapshot", "$performance_event", *SESSION_RECORDING_DEDICATED_KAFKA_EVENTS)

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

SDK_INFO = "posthog-capture-v1-internal/1.0"

# v1 Options struct fields and their legacy property counterparts.
_OPTIONS_TO_LEGACY_PROPERTY: dict[str, str] = {
    "cookieless_mode": "$cookieless_mode",
    "disable_skew_correction": "$ignore_sent_at",
    "product_tour_id": "$product_tour_id",
    "process_person_profile": "$process_person_profile",
}
_VALID_OPTION_KEYS = frozenset(_OPTIONS_TO_LEGACY_PROPERTY.keys())

# Extra legacy aliases that must also be stripped from properties.
_EXTRA_LEGACY_ALIASES: dict[str, str] = {
    "disable_skew_correction": "disable_skew_adjustment",
}

_KNOWN_RESULT_STATUSES = frozenset({"ok", "drop", "warning", "retry"})

# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #

CAPTURE_V1_BATCH_SUBMITTED = Counter(
    "capture_v1_internal_batch_submitted",
    "Chunked batches submitted to capture v1 endpoint (one per chunk, retries excluded).",
    labelnames=["event_source"],
)
CAPTURE_V1_REQUEST_SUBMITTED = Counter(
    "capture_v1_internal_request_submitted",
    "HTTP POST requests to capture v1 endpoint (one per attempt, retries included).",
    labelnames=["event_source"],
)
CAPTURE_V1_EVENT_SUBMITTED = Counter(
    "capture_v1_internal_event_submitted",
    "Individual events submitted to capture v1 endpoint.",
    labelnames=["event_source"],
)
CAPTURE_V1_EVENT_RESULT = Counter(
    "capture_v1_internal_event_result",
    "Per-event result status from capture v1 endpoint.",
    labelnames=["event_source", "result"],
)
CAPTURE_V1_REQUEST_FAILED = Counter(
    "capture_v1_internal_request_failed",
    "Whole-request failures from capture v1 endpoint.",
    labelnames=["event_source", "status_code"],
)
CAPTURE_V1_RESUBMIT = Counter(
    "capture_v1_internal_resubmit",
    "Resubmit rounds triggered by retry results.",
    labelnames=["event_source"],
)
CAPTURE_V1_OPTION_CONFLICT = Counter(
    "capture_v1_internal_option_conflict",
    "Typed option input disagreed with a legacy property; explicit won.",
    labelnames=["event_source", "field"],
)

# --------------------------------------------------------------------------- #
# Errors & result type
# --------------------------------------------------------------------------- #


class CaptureInternalError(Exception):
    """Raised on client-side validation failures or transport/HTTP errors.

    Carries a ``.status_code`` (the HTTP status from capture-rs, or 0 for
    client-side / transport errors) so callers can propagate it into their
    own HTTP responses.
    """

    def __init__(self, message: str, *, status_code: int = 0) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class CaptureInternalResult:
    """Aggregated outcome of a (possibly multi-round) v1 batch submission."""

    status_code: int
    results: dict[str, dict[str, Any]] = field(default_factory=dict)
    error: Optional[dict[str, Any]] = None

    ok: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    retried: list[str] = field(default_factory=list)
    unaccounted: list[str] = field(default_factory=list)

    def succeeded(self) -> bool:
        return self.error is None and not self.dropped and not self.retried and not self.unaccounted

    def terminal_failures(self) -> dict[str, dict[str, Any]]:
        return {
            uid: self.results[uid] for uid in (*self.dropped, *self.retried, *self.unaccounted) if uid in self.results
        }

    def raise_for_status(self) -> None:
        if self.error:
            raise CaptureInternalError(
                f"capture internal whole-request failure ({self.status_code}): "
                f"{self.error.get('error', 'unknown')}: {self.error.get('error_description', '')}",
                status_code=self.status_code,
            )
        failures = len(self.dropped) + len(self.retried) + len(self.unaccounted)
        if failures:
            raise CaptureInternalError(
                f"capture internal partial failure: {len(self.dropped)} dropped, "
                f"{len(self.retried)} exhausted retries, {len(self.unaccounted)} unaccounted",
                status_code=0,
            )


# --------------------------------------------------------------------------- #
# Header builder — single chokepoint for every physical POST
# --------------------------------------------------------------------------- #


def _build_v1_headers(token: str, attempt: int) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": SDK_INFO,
        "PostHog-Sdk-Info": SDK_INFO,
        "PostHog-Attempt": str(attempt),
        "PostHog-Request-Id": str(uuid4()),
        "PostHog-Request-Timestamp": datetime.now(UTC).isoformat(),
    }


# --------------------------------------------------------------------------- #
# Options / properties normalizer
# --------------------------------------------------------------------------- #


def _resolve_scalar(
    explicit: Any,
    legacy: Any,
    *,
    field: str,
    event_source: str,
) -> Any:
    """Return *explicit* if set, else *legacy*; log + count when both are set and disagree."""
    if explicit is not None:
        if legacy is not None and legacy != explicit:
            logger.warning(
                "capture_internal option conflict",
                event_source=event_source,
                field=field,
                explicit=explicit,
                legacy=legacy,
            )
            CAPTURE_V1_OPTION_CONFLICT.labels(event_source=event_source, field=field).inc()
        return explicit
    return legacy


def _normalize_options_and_properties(
    event_dict: dict[str, Any],
    *,
    process_person_profile: bool,
    event_source: str,
) -> tuple[dict[str, Any], Optional[str], Optional[str], dict[str, Any]]:
    """Separate typed ``options``/fields from free-form ``properties``.

    Returns ``(options_dict, session_id, window_id, cleaned_properties)``.
    The caller's dicts are never mutated.
    """
    raw_options: dict[str, Any] = event_dict.get("options") or {}
    props: dict[str, Any] = dict(event_dict.get("properties") or {})

    unknown = set(raw_options.keys()) - _VALID_OPTION_KEYS
    if unknown:
        raise CaptureInternalError(f"capture_internal ({event_source}): unknown option key(s): {sorted(unknown)}")

    options: dict[str, Any] = {}

    for opt_key, legacy_prop in _OPTIONS_TO_LEGACY_PROPERTY.items():
        explicit = raw_options.get(opt_key)
        legacy = props.pop(legacy_prop, None)

        alias = _EXTRA_LEGACY_ALIASES.get(opt_key)
        if alias:
            alias_val = props.pop(alias, None)
            if legacy is None:
                legacy = alias_val

        resolved = _resolve_scalar(explicit, legacy, field=opt_key, event_source=event_source)
        if resolved is not None:
            options[opt_key] = resolved

    session_id: Optional[str] = _resolve_scalar(
        event_dict.get("session_id"),
        props.pop("$session_id", None),
        field="session_id",
        event_source=event_source,
    )
    window_id: Optional[str] = _resolve_scalar(
        event_dict.get("window_id"),
        props.pop("$window_id", None),
        field="window_id",
        event_source=event_source,
    )

    # Function-level override: when the caller says no person processing,
    # force it even if the event-level option disagrees (but log the conflict).
    if not process_person_profile:
        existing = options.get("process_person_profile")
        if existing not in (None, False):
            logger.warning(
                "capture_internal option conflict",
                event_source=event_source,
                field="process_person_profile",
                explicit=f"function_param={process_person_profile}",
                legacy=existing,
            )
            CAPTURE_V1_OPTION_CONFLICT.labels(event_source=event_source, field="process_person_profile").inc()
        options["process_person_profile"] = False

    return options, session_id, window_id, props


# --------------------------------------------------------------------------- #
# Payload builder
# --------------------------------------------------------------------------- #


def _validate_batch_inputs(events: list[dict[str, Any]], *, token: str, event_source: str) -> None:
    """Validate required batch-level inputs. Raises CaptureInternalError on failure."""
    if not event_source:
        raise CaptureInternalError("capture_internal: event_source is required (identifies the submitting call site)")
    if not token:
        raise CaptureInternalError(f"capture_internal ({event_source}): API token is required")
    if not events:
        raise CaptureInternalError(f"capture_internal ({event_source}): at least one event is required")


def prepare_capture_internal_batch(
    events: list[dict[str, Any]],
    *,
    token: str,
    event_source: str,
    historical_migration: bool = False,
    process_person_profile: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    """Build a v1 batch envelope from caller-supplied event dicts.

    Returns ``(payload, ordered_uuids)`` so callers can correlate the
    results map.
    """
    _validate_batch_inputs(events, token=token, event_source=event_source)

    batch: list[dict[str, Any]] = []
    uuids: list[str] = []

    for ev in events:
        event_name: str = ev.get("event", "")
        if not event_name:
            raise CaptureInternalError(f"capture_internal ({event_source}): event name is required")

        if event_name in SESSION_RECORDING_EVENT_NAMES:
            raise CaptureInternalError(
                f"capture_internal ({event_source}): '{event_name}' is a replay event; use the replay capture path"
            )

        distinct_id: str = ev.get("distinct_id", "")
        if not distinct_id:
            props = ev.get("properties") or {}
            distinct_id = props.get("distinct_id", "")
        if not distinct_id:
            raise CaptureInternalError(f"capture_internal ({event_source}, {event_name}): distinct_id is required")

        event_uuid: str = ev.get("event_uuid") or ev.get("uuid") or str(uuid4())
        uuids.append(event_uuid)

        raw_ts: Any = ev.get("timestamp", "")
        if not raw_ts:
            timestamp_str = datetime.now(UTC).isoformat()
        elif isinstance(raw_ts, datetime):
            if raw_ts.tzinfo is None:
                raw_ts = raw_ts.replace(tzinfo=UTC)
            timestamp_str = raw_ts.astimezone(UTC).isoformat()
        else:
            timestamp_str = str(raw_ts)

        options, session_id, window_id, cleaned_props = _normalize_options_and_properties(
            ev, process_person_profile=process_person_profile, event_source=event_source
        )

        entry: dict[str, Any] = {
            "event": event_name,
            "uuid": event_uuid,
            "distinct_id": distinct_id,
            "timestamp": timestamp_str,
            "properties": cleaned_props,
        }
        if session_id is not None:
            entry["session_id"] = session_id
        if window_id is not None:
            entry["window_id"] = window_id
        if options:
            entry["options"] = options

        batch.append(entry)

    payload: dict[str, Any] = {
        "created_at": datetime.now(UTC).isoformat(),
        "capture_internal": True,
        "historical_migration": historical_migration,
        "batch": batch,
    }
    return payload, uuids


# --------------------------------------------------------------------------- #
# Primary API
# --------------------------------------------------------------------------- #


def _submit_batch_chunk(
    *,
    events: list[dict[str, Any]],
    token: str,
    event_source: str,
    historical_migration: bool,
    process_person_profile: bool,
    max_attempts: int,
    timeout: float,
) -> CaptureInternalResult:
    """Submit a single chunk of events to the v1 batch endpoint with retry logic.

    This is the internal workhorse — callers should use ``capture_batch_internal``
    which handles validation, chunking, and concurrent fan-out.
    """
    payload, uuids = prepare_capture_internal_batch(
        events,
        token=token,
        event_source=event_source,
        historical_migration=historical_migration,
        process_person_profile=process_person_profile,
    )

    url = f"{CAPTURE_INTERNAL_URL}{CAPTURE_V1_INTERNAL_ENDPOINT}"

    CAPTURE_V1_BATCH_SUBMITTED.labels(event_source=event_source).inc()
    CAPTURE_V1_EVENT_SUBMITTED.labels(event_source=event_source).inc(len(uuids))

    uuid_to_event: dict[str, dict[str, Any]] = {}
    for uid, entry in zip(uuids, payload["batch"]):
        uuid_to_event[uid] = entry

    aggregated: dict[str, dict[str, Any]] = {}
    attempt = 1
    pending_batch = payload["batch"]

    def _finalize(status_code: int, error: Optional[dict[str, Any]] = None) -> CaptureInternalResult:
        # Any uuid capture-rs never acked — including whole-request failures — is unaccounted.
        for uid in uuid_to_event:
            aggregated.setdefault(uid, {"result": "unaccounted"})
        result = CaptureInternalResult(status_code=status_code, results=aggregated, error=error)
        for uid, entry in aggregated.items():
            status = entry.get("result", "ok")
            if status == "ok":
                result.ok.append(uid)
            elif status == "drop":
                result.dropped.append(uid)
            elif status == "warning":
                result.warnings.append(uid)
            elif status == "retry":
                result.retried.append(uid)
            else:
                result.unaccounted.append(uid)
        return result

    with internal_requests_session() as session:
        session.mount(
            url,
            HTTPAdapter(
                max_retries=Retry(
                    total=3,
                    backoff_factor=0.1,
                    status_forcelist=[500, 502, 503, 504],
                    allowed_methods={"POST"},
                )
            ),
        )

        while True:
            headers = _build_v1_headers(token, attempt)
            submit_payload: dict[str, Any] = {
                "created_at": payload["created_at"],
                "capture_internal": payload["capture_internal"],
                "historical_migration": payload["historical_migration"],
                "batch": pending_batch,
            }

            CAPTURE_V1_REQUEST_SUBMITTED.labels(event_source=event_source).inc()
            try:
                resp = session.post(url, json=submit_payload, headers=headers, timeout=timeout)
            except RequestException as exc:
                CAPTURE_V1_REQUEST_FAILED.labels(event_source=event_source, status_code="transport").inc()
                logger.warning(
                    "capture_internal_transport_error",
                    event_source=event_source,
                    request_id=headers.get("PostHog-Request-Id", ""),
                    batch_size=len(pending_batch),
                    error=str(exc),
                )
                return _finalize(0, {"error": "transport_error", "error_description": str(exc)})

            if resp.status_code != 200:
                CAPTURE_V1_REQUEST_FAILED.labels(
                    event_source=event_source,
                    status_code=str(resp.status_code),
                ).inc()
                try:
                    error_body = resp.json()
                except Exception:
                    error_body = {
                        "error": "unknown",
                        "error_description": resp.text[:500] if resp.text else "",
                    }
                logger.warning(
                    "capture_internal_request_failed",
                    event_source=event_source,
                    request_id=headers.get("PostHog-Request-Id", ""),
                    status_code=resp.status_code,
                    batch_size=len(pending_batch),
                    error=error_body.get("error", "unknown"),
                )
                return _finalize(resp.status_code, error_body)

            # --- 200: parse per-event results ---
            try:
                body = resp.json()
            except Exception:
                return _finalize(
                    resp.status_code,
                    {"error": "invalid_json", "error_description": "could not parse 200 body"},
                )

            results_map: dict[str, Any] = body.get("results", {})

            retry_uuids: list[str] = []
            for uid in list(uuid_to_event.keys()):
                if uid in aggregated:
                    continue
                entry = results_map.get(uid)
                if entry is None:
                    continue
                clamped = entry.get("result", "ok")
                if clamped not in _KNOWN_RESULT_STATUSES:
                    clamped = "unknown"
                CAPTURE_V1_EVENT_RESULT.labels(event_source=event_source, result=clamped).inc()
                if entry.get("result") == "retry":
                    retry_uuids.append(uid)
                else:
                    aggregated[uid] = entry

            if not retry_uuids or attempt >= max_attempts:
                for uid in retry_uuids:
                    entry = results_map.get(uid, {"result": "retry"})
                    aggregated[uid] = entry
                break

            # --- resubmit retry-uuids ---
            CAPTURE_V1_RESUBMIT.labels(event_source=event_source).inc()
            retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
            if retry_after > 0:
                time.sleep(retry_after)

            pending_batch = [uuid_to_event[uid] for uid in retry_uuids]
            attempt += 1

    return _finalize(200)


def _merge_results(chunk_results: list[CaptureInternalResult]) -> CaptureInternalResult:
    """Merge results from multiple chunk submissions into a single result."""
    merged = CaptureInternalResult(status_code=200)
    for cr in chunk_results:
        if cr.error is not None and merged.error is None:
            merged.error = cr.error
            merged.status_code = cr.status_code
        merged.results.update(cr.results)
        merged.ok.extend(cr.ok)
        merged.dropped.extend(cr.dropped)
        merged.warnings.extend(cr.warnings)
        merged.retried.extend(cr.retried)
        merged.unaccounted.extend(cr.unaccounted)
    return merged


def capture_batch_internal(
    *,
    events: list[dict[str, Any]],
    token: str,
    event_source: str,
    historical_migration: bool = False,
    process_person_profile: bool = False,
    max_attempts: int = CAPTURE_V1_INTERNAL_MAX_ATTEMPTS,
    timeout: float = 2,
) -> CaptureInternalResult:
    """
    capture_batch_internal submits multiple capture request payloads to capture-rs on
    behalf of a customer team.  This is the preferred method for publishing analytics events
    from the Django app.  PLEASE DO NOT write events directly to ingestion Kafka topics —
    USE THIS!  The capture-rs pipeline handles deduplication, quotas, billing, and routing;
    bypassing it creates safety and correctness problems.

    NOTE: This is for submitting events ON BEHALF OF A CUSTOMER TEAM.  It is NOT for
    submitting SDK-style internal telemetry events for PostHog's own team (team 2) — the
    posthoganalytics SDK integration handles that separately.

    Submits events as true batch POSTs to the v1 analytics endpoint.  capture-rs returns
    per-event results; events that get a ``retry`` result are automatically resubmitted up
    to ``max_attempts`` rounds.  Transport-level retries on 5xx are handled by urllib3.

    Automatic chunking:
        Batches larger than ``CAPTURE_INTERNAL_BATCH_CHUNK_SIZE`` (default 200 events) are
        automatically split into chunks and submitted concurrently using up to
        ``CAPTURE_INTERNAL_MAX_WORKERS`` (default 8) threads.  Callers do NOT need to
        pre-chunk — the API handles this transparently.  Small batches (<=200 events)
        are submitted directly with zero threading overhead.

        Each chunk gets its own retry budget (``max_attempts``).  If one chunk fails
        entirely (transport error), its events appear in ``unaccounted``; other chunks'
        results are preserved.

    Session replay events ($snapshot, $performance_event, $snapshot_items) are NOT SUPPORTED
    and will raise CaptureInternalError.  Real replay ingestion flows through SDKs directly
    to the capture-rs /s/ endpoint.

    event.options reference (typed options replacing legacy $-prefixed properties):
    ┌─────────────────────────┬────────────────────────────┬──────────────┐
    │ options key             │ replaces legacy property   │ default      │
    ├─────────────────────────┼────────────────────────────┼──────────────┤
    │ cookieless_mode         │ $cookieless_mode           │ None/omitted │
    │ disable_skew_correction │ $ignore_sent_at            │ None/omitted │
    │                         │ (alias: disable_skew_      │              │
    │                         │  adjustment)               │              │
    │ product_tour_id         │ $product_tour_id           │ None/omitted │
    │ process_person_profile  │ $process_person_profile    │ see below    │
    └─────────────────────────┴────────────────────────────┴──────────────┘

    Additional top-level event fields (also extracted from properties):
    ┌─────────────────────────┬────────────────────────────┬──────────────┐
    │ event field             │ replaces legacy property   │ default      │
    ├─────────────────────────┼────────────────────────────┼──────────────┤
    │ session_id              │ $session_id                │ None/omitted │
    │ window_id               │ $window_id                 │ None/omitted │
    └─────────────────────────┴────────────────────────────┴──────────────┘

    When both a typed key AND its legacy $-property are present, the typed key wins
    (a warning metric ``capture_v1_internal_option_conflict`` is emitted).  The legacy
    property is always stripped from ``properties`` regardless.

    process_person_profile interaction:
        The batch-level ``process_person_profile`` param acts as a SAFETY RAIL.  When
        False (default), it forces ``options.process_person_profile = False`` for EVERY
        event in the batch — even if the event's own options dict says True (a warning
        is logged on conflict).  Only when the batch-level param is True does the
        per-event ``options.process_person_profile`` value get respected as-is.  This
        prevents accidental expensive person profile updates from internal tooling.

    Args:
        events: list of event dicts to capture. Each MUST include:
            - ``event`` (str): event name
            - ``distinct_id`` (str): required; may alternatively appear in ``properties``
            - ``properties`` (dict): event properties (required; can be empty)
            Optional per-event fields:
            - ``timestamp`` (str | datetime): defaults to now UTC if absent
            - ``options`` (dict): typed options per table above
            - ``session_id``, ``window_id`` (str): top-level fields per table above
            - ``event_uuid`` (str): deterministic UUID; defaults to a fresh UUIDv7
        token: API token to submit events on behalf of (required; overrides individual
            event tokens)
        event_source: observability tag indicating the internal module/codepath submitting
            the events (REQUIRED — validated; raises CaptureInternalError if empty).
            Callers MUST supply this so Prometheus metrics can identify which call site
            is submitting events and detect (ab)usive new callers.
        historical_migration: if True, routes events to the historical ingestion path
            in capture-rs (separate Kafka topic/consumer group)
        process_person_profile: batch-level safety rail (default: False).  See
            "process_person_profile interaction" above.
        max_attempts: application-level retry budget for per-event ``retry`` results from
            capture-rs (default: 4). Does not affect transport-level 5xx retries.
        timeout: HTTP request timeout in seconds (default: 2)

    Returns:
        CaptureInternalResult with per-event outcomes.  Call ``.raise_for_status()`` to
        raise ``CaptureInternalError`` on any failure (whole-request or partial).  Inspect
        ``.ok``, ``.dropped``, ``.retried``, ``.unaccounted`` lists for fine-grained handling.

    Raises:
        CaptureInternalError: on client-side validation failures (missing/empty event_source,
            missing token, empty batch, replay event names, unknown option keys) or
            HTTP/transport errors.  The exception carries a ``.status_code`` attribute
            (the HTTP status from capture-rs, or 0 for client-side/transport errors).
    """
    # Validate early so we fail fast before chunking/fan-out, not inside a worker thread.
    _validate_batch_inputs(events, token=token, event_source=event_source)

    chunk_size = max(CAPTURE_INTERNAL_BATCH_CHUNK_SIZE, 1)

    def _submit_chunk(chunk_events: list[dict[str, Any]]) -> CaptureInternalResult:
        return _submit_batch_chunk(
            events=chunk_events,
            token=token,
            event_source=event_source,
            historical_migration=historical_migration,
            process_person_profile=process_person_profile,
            max_attempts=max_attempts,
            timeout=timeout,
        )

    # Hot path: small batch — submit directly, no threading overhead.
    if len(events) <= chunk_size:
        return _submit_chunk(events)

    # Large batch: chunk and fan out concurrently.
    chunks = [events[i : i + chunk_size] for i in range(0, len(events), chunk_size)]
    logger.info(
        "capture_batch_internal_chunked",
        event_source=event_source,
        total_events=len(events),
        chunks=len(chunks),
        chunk_size=chunk_size,
        max_workers=CAPTURE_INTERNAL_MAX_WORKERS,
    )

    chunk_results: list[CaptureInternalResult] = []
    with ThreadPoolExecutor(max_workers=CAPTURE_INTERNAL_MAX_WORKERS) as executor:
        futures = {executor.submit(_submit_chunk, chunk): i for i, chunk in enumerate(chunks)}
        for future in as_completed(futures):
            chunk_idx = futures[future]
            try:
                chunk_results.append(future.result())
            except Exception as exc:
                logger.exception(
                    "capture_batch_internal_chunk_error",
                    event_source=event_source,
                    chunk=chunk_idx,
                    error=str(exc),
                )
                chunk_results.append(
                    CaptureInternalResult(
                        status_code=0,
                        error={"error": "chunk_exception", "error_description": str(exc)},
                    )
                )

    return _merge_results(chunk_results)


def _parse_retry_after(header_value: Optional[str]) -> float:
    """Parse Retry-After header, capped to the configured maximum."""
    if not header_value:
        return 0.0
    try:
        val = float(header_value)
    except (ValueError, TypeError):
        return 1.0
    return min(max(val, 0), CAPTURE_V1_INTERNAL_RETRY_AFTER_CAP_SECONDS)


# --------------------------------------------------------------------------- #
# Convenience single-event wrapper
# --------------------------------------------------------------------------- #


def capture_internal(
    *,
    token: str,
    event_name: str,
    event_source: str,
    distinct_id: str,
    timestamp: Optional[str | datetime] = None,
    properties: Optional[dict[str, Any]] = None,
    options: Optional[dict[str, Any]] = None,
    session_id: Optional[str] = None,
    window_id: Optional[str] = None,
    event_uuid: Optional[str] = None,
    process_person_profile: bool = False,
    historical_migration: bool = False,
    timeout: float = 2,
) -> CaptureInternalResult:
    """
    capture_internal submits a single-event capture request payload to the capture-rs
    backend service.  This is the preferred method for publishing events from the Django
    app on behalf of non-PostHog-admin teams/projects.  PLEASE DO NOT write events directly
    to ingestion Kafka topics — USE THIS!  The capture-rs pipeline handles deduplication,
    quotas, billing, and routing; bypassing it creates safety and correctness problems.

    NOTE: This is for submitting events ON BEHALF OF A CUSTOMER TEAM.  It is NOT for
    submitting SDK-style internal telemetry events for PostHog's own team (team 2) — the
    posthoganalytics SDK integration handles that separately.

    Wraps the event into a 1-element batch and delegates to capture_batch_internal.
    See capture_batch_internal's docstring for the full event.options reference table
    and the process_person_profile batch-level interaction.

    Session replay events ($snapshot, $performance_event, $snapshot_items) are NOT SUPPORTED
    and will raise CaptureInternalError.  Real replay ingestion flows through SDKs directly
    to the capture-rs /s/ endpoint.

    Args:
        token: API token to submit the event on behalf of (required)
        event_name: the name of the event to be published (required)
        event_source: observability tag indicating the internal module/codepath submitting
            the event (REQUIRED — validated; raises CaptureInternalError if empty).
            Callers MUST supply this so Prometheus metrics can identify which call site
            is submitting events and detect (ab)usive new callers.
        distinct_id: the distinct ID for the event (required)
        timestamp: the timestamp of the event (optional; will be set to now UTC if absent).
            Accepts datetime objects or ISO8601 strings.
        properties: event properties to submit with the event (optional; can be empty).
            Legacy ``$``-prefixed keys that map to typed options are automatically
            extracted and stripped — see the options table in capture_batch_internal.
        options: typed event options dict (optional).  See the options reference table in
            capture_batch_internal for valid keys, legacy equivalents, and defaults.
        session_id: session ID (optional). Preferred over ``$session_id`` in properties.
        window_id: window ID (optional). Preferred over ``$window_id`` in properties.
        event_uuid: optional deterministic UUID to assign to the event (default: capture-rs
            assigns a fresh UUIDv7).  Use when the caller needs a stable, queryable event
            UUID — e.g. to link back to the event from an admin UI.  Must be a parseable
            UUID string.
        process_person_profile: batch-level safety rail (default: False).  When False,
            forces person processing OFF regardless of per-event options.  When True,
            per-event options.process_person_profile is respected.  See
            capture_batch_internal docstring for the full interaction.
        historical_migration: if True, routes to the historical ingestion path in
            capture-rs (separate Kafka topic/consumer group).
        timeout: HTTP request timeout in seconds (default: 2)

    Returns:
        CaptureInternalResult with per-event outcome.  Call ``.raise_for_status()`` to raise
        ``CaptureInternalError`` on failure.  For best-effort fire-and-forget patterns,
        check ``.succeeded()`` instead.

    Raises:
        CaptureInternalError: on client-side validation failures (missing/empty event_source,
            missing token, replay event names, etc.) or HTTP/transport errors.  Carries a
            ``.status_code`` attribute (HTTP status from capture-rs, or 0 for client-side/
            transport errors) so callers can propagate into their own HTTP responses.
    """
    event_dict: dict[str, Any] = {
        "event": event_name,
        "distinct_id": distinct_id,
        "properties": properties or {},
    }
    if timestamp is not None:
        event_dict["timestamp"] = timestamp
    if options is not None:
        event_dict["options"] = options
    if session_id is not None:
        event_dict["session_id"] = session_id
    if window_id is not None:
        event_dict["window_id"] = window_id
    if event_uuid is not None:
        event_dict["event_uuid"] = event_uuid

    return capture_batch_internal(
        events=[event_dict],
        token=token,
        event_source=event_source,
        historical_migration=historical_migration,
        process_person_profile=process_person_profile,
        timeout=timeout,
    )
