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
from http import HTTPStatus
from typing import Any, Optional
from uuid import uuid4

import structlog
from prometheus_client import Counter
from requests.adapters import HTTPAdapter, Retry
from requests.exceptions import RequestException

from posthog.dataclasses import frozen
from posthog.security.outbound_proxy import internal_requests_session
from posthog.settings.ingestion import (
    CAPTURE_AI_INTERNAL_URL,
    CAPTURE_INTERNAL_BATCH_CHUNK_SIZE,
    CAPTURE_INTERNAL_MAX_WORKERS,
    CAPTURE_INTERNAL_URL,
    CAPTURE_V1_AI_INTERNAL_ENDPOINT,
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

# `_capture_batch_impl` sends every event with this prefix to capture-ai.
AI_EVENT_NAME_PREFIX = "$ai_"

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
    labelnames=["event_source", "lane"],
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
    labelnames=["event_source", "status_code", "lane"],
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
CAPTURE_V1_EVENTS_REROUTED = Counter(
    "capture_v1_internal_events_rerouted",
    "Events whose name put them on the other lane than the entry point the caller used.",
    labelnames=["event_source", "from_lane"],
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

    @property
    def is_billing_limit_exceeded(self) -> bool:
        return self.status_code == HTTPStatus.PAYMENT_REQUIRED


@frozen
class RequestFailure:
    """One HTTP submission that failed as a whole; its events are in ``unaccounted``."""

    lane: str
    status_code: int
    error: dict[str, Any]
    event_count: int


# Mutable on purpose: _submit_batch_chunk and _merge_results build it up in place.
@dataclass(frozen=False)
class CaptureInternalResult:
    """Outcome of one v1 batch submission across all of its requests.

    Every submitted uuid lands in exactly one of ``ok``, ``dropped``, ``warnings``,
    ``retried`` or ``unaccounted``. A multi-request batch can be partially acked, so
    retry only ``unaccounted`` and ``retried`` uuids, never the whole batch.
    """

    status_code: int
    results: dict[str, dict[str, Any]] = field(default_factory=dict)
    error: Optional[dict[str, Any]] = None

    ok: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    retried: list[str] = field(default_factory=list)
    unaccounted: list[str] = field(default_factory=list)
    request_failures: list[RequestFailure] = field(default_factory=list)

    def succeeded(self) -> bool:
        return self.error is None and not self.dropped and not self.retried and not self.unaccounted

    def terminal_failures(self) -> dict[str, dict[str, Any]]:
        return {
            uid: self.results[uid] for uid in (*self.dropped, *self.retried, *self.unaccounted) if uid in self.results
        }

    def raise_for_status(self) -> None:
        if self.error:
            acked = len(self.ok) + len(self.warnings)
            scope = "partial-request" if acked else "whole-request"
            lanes = ", ".join(f"{rf.lane} {rf.status_code}" for rf in self.request_failures) or str(self.status_code)
            raise CaptureInternalError(
                f"capture internal {scope} failure ({lanes}): "
                f"{self.error.get('error', 'unknown')}: {self.error.get('error_description', '')}; "
                f"{acked} events acked, {len(self.unaccounted)} unaccounted",
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


@frozen
class EventIdentity:
    """The two fields the routing checks had to read, kept named so a caller
    cannot swap them: both are strings."""

    event_name: str
    distinct_id: str


@frozen
class NormalizedEventParts:
    options: dict[str, Any]
    session_id: Optional[str]
    window_id: Optional[str]
    properties: dict[str, Any]


def _reject_unknown_option_keys(event_dict: dict[str, Any], *, event_source: str) -> None:
    """Refuse option keys the v1 envelope has no field for.

    Split out of normalization so the batch path can run it before publishing
    anything. It is a set difference, so running it in both places is cheaper
    than normalizing an event twice.
    """
    unknown = set((event_dict.get("options") or {}).keys()) - _VALID_OPTION_KEYS
    if unknown:
        raise CaptureInternalError(f"capture_internal ({event_source}): unknown option key(s): {sorted(unknown)}")


def _normalize_options_and_properties(
    event_dict: dict[str, Any],
    *,
    process_person_profile: bool,
    event_source: str,
) -> NormalizedEventParts:
    """Separate typed ``options``/fields from free-form ``properties``.

    Returns a ``NormalizedEventParts``. The caller's dicts are never mutated.
    """
    raw_options: dict[str, Any] = event_dict.get("options") or {}
    props: dict[str, Any] = dict(event_dict.get("properties") or {})

    _reject_unknown_option_keys(event_dict, event_source=event_source)

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

    return NormalizedEventParts(options=options, session_id=session_id, window_id=window_id, properties=props)


# --------------------------------------------------------------------------- #
# Payload builder
# --------------------------------------------------------------------------- #


def _lane_label(ai_lane: bool) -> str:
    return "ai" if ai_lane else "analytics"


def _lane_fn_name(ai_lane: bool) -> str:
    """Name the entry point the caller actually used, so an error points at their code."""
    return "capture_ai_internal" if ai_lane else "capture_internal"


def _validate_batch_inputs(
    events: list[dict[str, Any]], *, token: str, event_source: str, ai_lane: bool = False
) -> None:
    """Validate required batch-level inputs. Raises CaptureInternalError on failure."""
    fn = _lane_fn_name(ai_lane)
    if not event_source:
        raise CaptureInternalError(f"{fn}: event_source is required (identifies the submitting call site)")
    if not token:
        raise CaptureInternalError(f"{fn} ({event_source}): API token is required")
    if not events:
        raise CaptureInternalError(f"{fn} ({event_source}): at least one event is required")


def _validate_event(ev: dict[str, Any], *, event_source: str, ai_lane: bool) -> EventIdentity:
    """Every client-side rejection lives here so a batch is cleared before its first chunk publishes.

    ``ai_lane`` only names the entry point in error messages; the wire lane is chosen
    per event from the `$ai_` prefix.
    """
    fn = _lane_fn_name(ai_lane)

    event_name = ev.get("event", "")
    if not isinstance(event_name, str) or not event_name:
        raise CaptureInternalError(f"{fn} ({event_source}): event name is required and must be a non-empty string")

    if event_name in SESSION_RECORDING_EVENT_NAMES:
        raise CaptureInternalError(
            f"{fn} ({event_source}): '{event_name}' is a replay event; use the replay capture path"
        )

    # Normalization would otherwise fail on these inside a worker, after other chunks published.
    for key in ("properties", "options"):
        value = ev.get(key)
        if value is not None and not isinstance(value, dict):
            raise CaptureInternalError(f"{fn} ({event_source}, {event_name}): {key} must be a dict")

    distinct_id: str = ev.get("distinct_id", "")
    if not distinct_id:
        props = ev.get("properties") or {}
        distinct_id = props.get("distinct_id", "")
    if not distinct_id:
        raise CaptureInternalError(f"{fn} ({event_source}, {event_name}): distinct_id is required")

    _reject_unknown_option_keys(ev, event_source=event_source)

    return EventIdentity(event_name=event_name, distinct_id=distinct_id)


def _validate_batch_events(events: list[dict[str, Any]], *, event_source: str, ai_lane: bool) -> None:
    """Validate every event and reject duplicate uuids: results are keyed by uuid, so a
    duplicate would overwrite one event's outcome."""
    fn = _lane_fn_name(ai_lane)
    seen_uuids: set[str] = set()
    for ev in events:
        _validate_event(ev, event_source=event_source, ai_lane=ai_lane)
        event_uuid = ev.get("event_uuid") or ev.get("uuid")
        if event_uuid:
            if event_uuid in seen_uuids:
                raise CaptureInternalError(f"{fn} ({event_source}): duplicate event_uuid {event_uuid!r} in batch")
            seen_uuids.add(event_uuid)


def prepare_capture_internal_batch(
    events: list[dict[str, Any]],
    *,
    token: str,
    event_source: str,
    historical_migration: bool = False,
    process_person_profile: bool = False,
    ai_lane: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    """Build a v1 batch envelope from caller-supplied event dicts.

    Returns ``(payload, ordered_uuids)`` so callers can correlate the
    results map.

    ``ai_lane`` only names the entry point in error messages; the envelope is the
    same on both lanes.
    """
    _validate_batch_inputs(events, token=token, event_source=event_source, ai_lane=ai_lane)

    batch: list[dict[str, Any]] = []
    uuids: list[str] = []

    for ev in events:
        identity = _validate_event(ev, event_source=event_source, ai_lane=ai_lane)

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

        parts = _normalize_options_and_properties(
            ev, process_person_profile=process_person_profile, event_source=event_source
        )

        entry: dict[str, Any] = {
            "event": identity.event_name,
            "uuid": event_uuid,
            "distinct_id": identity.distinct_id,
            "timestamp": timestamp_str,
            "properties": parts.properties,
        }
        if parts.session_id is not None:
            entry["session_id"] = parts.session_id
        if parts.window_id is not None:
            entry["window_id"] = parts.window_id
        if parts.options:
            entry["options"] = parts.options

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
    ai_lane: bool = False,
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
        ai_lane=ai_lane,
    )

    # A different deployment, not just a different path: `/i/v1/ai/events` is
    # mounted only on capture-ai.
    if ai_lane:
        url = f"{CAPTURE_AI_INTERNAL_URL}{CAPTURE_V1_AI_INTERNAL_ENDPOINT}"
    else:
        url = f"{CAPTURE_INTERNAL_URL}{CAPTURE_V1_INTERNAL_ENDPOINT}"
    lane = _lane_label(ai_lane)

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
        if error is not None:
            result.request_failures.append(
                RequestFailure(lane=lane, status_code=status_code, error=error, event_count=len(pending_batch))
            )
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

            CAPTURE_V1_REQUEST_SUBMITTED.labels(event_source=event_source, lane=lane).inc()
            try:
                resp = session.post(url, json=submit_payload, headers=headers, timeout=timeout)
            except RequestException as exc:
                CAPTURE_V1_REQUEST_FAILED.labels(event_source=event_source, status_code="transport", lane=lane).inc()
                logger.warning(
                    "capture_internal_transport_error",
                    event_source=event_source,
                    lane=lane,
                    request_id=headers.get("PostHog-Request-Id", ""),
                    batch_size=len(pending_batch),
                    error=str(exc),
                )
                return _finalize(0, {"error": "transport_error", "error_description": str(exc)})

            if resp.status_code != 200:
                CAPTURE_V1_REQUEST_FAILED.labels(
                    event_source=event_source,
                    status_code=str(resp.status_code),
                    lane=lane,
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
                    lane=lane,
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

            results_map = body.get("results", {}) if isinstance(body, dict) else None
            if not isinstance(results_map, dict):
                # Raising here would lose this chunk's uuids; _finalize marks them unaccounted.
                return _finalize(
                    resp.status_code,
                    {"error": "invalid_response", "error_description": "200 body is not a results object"},
                )

            retry_uuids: list[str] = []
            for uid in list(uuid_to_event.keys()):
                if uid in aggregated:
                    continue
                entry = results_map.get(uid)
                if not isinstance(entry, dict):
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
    """Merge the results of several requests (chunks, lanes) into one.

    ``error`` comes from the first failed request, rewritten to ``partial_request_failure``
    when another request was acked so a caller does not resend the acked events.
    """
    merged = CaptureInternalResult(status_code=200)
    any_acked_request = False
    for cr in chunk_results:
        if cr.error is not None and merged.error is None:
            merged.error = cr.error
            merged.status_code = cr.status_code
        if cr.error is None:
            any_acked_request = True
        merged.request_failures.extend(cr.request_failures)
        merged.results.update(cr.results)
        merged.ok.extend(cr.ok)
        merged.dropped.extend(cr.dropped)
        merged.warnings.extend(cr.warnings)
        merged.retried.extend(cr.retried)
        merged.unaccounted.extend(cr.unaccounted)
    if merged.error is not None and any_acked_request:
        first = merged.error
        merged.error = {
            "error": "partial_request_failure",
            "error_description": (
                f"{len(merged.request_failures)} of {len(chunk_results)} requests failed; "
                f"first: {first.get('error', 'unknown')}: {first.get('error_description', '')}"
            ),
        }
    return merged


def _submit_chunks(
    *,
    lanes: list[tuple[list[dict[str, Any]], bool]],
    token: str,
    event_source: str,
    historical_migration: bool,
    process_person_profile: bool,
    max_attempts: int,
    timeout: float,
) -> CaptureInternalResult:
    """Submit every lane's chunks over one shared worker pool.

    Lanes go to different deployments, so a mixed batch runs them concurrently; sharing
    the pool keeps it within the connection budget of a single-lane batch.
    """
    chunk_size = max(CAPTURE_INTERNAL_BATCH_CHUNK_SIZE, 1)
    chunks: list[tuple[list[dict[str, Any]], bool]] = [
        (lane_events[i : i + chunk_size], lane_is_ai)
        for lane_events, lane_is_ai in lanes
        for i in range(0, len(lane_events), chunk_size)
    ]

    def _submit_chunk(chunk_events: list[dict[str, Any]], ai_lane: bool) -> CaptureInternalResult:
        return _submit_batch_chunk(
            events=chunk_events,
            token=token,
            event_source=event_source,
            historical_migration=historical_migration,
            process_person_profile=process_person_profile,
            max_attempts=max_attempts,
            timeout=timeout,
            ai_lane=ai_lane,
        )

    # Hot path: one lane, one chunk, so skip the pool.
    if len(chunks) == 1:
        return _submit_chunk(*chunks[0])

    logger.info(
        "capture_batch_internal_chunked",
        event_source=event_source,
        total_events=sum(len(lane_events) for lane_events, _ in lanes),
        chunks=len(chunks),
        events_per_lane={_lane_label(lane_is_ai): len(lane_events) for lane_events, lane_is_ai in lanes},
        chunk_size=chunk_size,
        max_workers=CAPTURE_INTERNAL_MAX_WORKERS,
    )

    chunk_results: list[CaptureInternalResult] = []
    with ThreadPoolExecutor(max_workers=CAPTURE_INTERNAL_MAX_WORKERS) as executor:
        futures = {
            executor.submit(_submit_chunk, chunk, ai_lane): (i, ai_lane) for i, (chunk, ai_lane) in enumerate(chunks)
        }
        for future in as_completed(futures):
            chunk_idx, ai_lane = futures[future]
            try:
                chunk_results.append(future.result())
            except Exception as exc:
                logger.exception(
                    "capture_batch_internal_chunk_error",
                    event_source=event_source,
                    lane=_lane_label(ai_lane),
                    chunk=chunk_idx,
                    error=str(exc),
                )
                error = {"error": "chunk_exception", "error_description": str(exc)}
                chunk_results.append(
                    CaptureInternalResult(
                        status_code=0,
                        error=error,
                        request_failures=[
                            RequestFailure(
                                lane=_lane_label(ai_lane),
                                status_code=0,
                                error=error,
                                event_count=len(chunks[chunk_idx][0]),
                            )
                        ],
                    )
                )

    return _merge_results(chunk_results)


def _capture_batch_impl(
    *,
    events: list[dict[str, Any]],
    token: str,
    event_source: str,
    historical_migration: bool,
    process_person_profile: bool,
    max_attempts: int,
    timeout: float,
    ai_lane: bool,
) -> CaptureInternalResult:
    """Shared body of capture_batch_internal and capture_batch_ai_internal.

    The wire lane follows the event name, not ``ai_lane``: capture-ai drops a non-AI
    event as `misrouted_event`, and capture-analytics would give an `$ai_*` event person
    processing. Reroutes are counted so a call site on the wrong entry point is visible.
    """
    _validate_batch_inputs(events, token=token, event_source=event_source, ai_lane=ai_lane)

    # Reject the whole batch before either lane publishes a chunk.
    _validate_batch_events(events, event_source=event_source, ai_lane=ai_lane)

    ai_events = [ev for ev in events if ev["event"].startswith(AI_EVENT_NAME_PREFIX)]
    analytics_events = [ev for ev in events if not ev["event"].startswith(AI_EVENT_NAME_PREFIX)]

    rerouted = analytics_events if ai_lane else ai_events
    if rerouted:
        from_lane = _lane_label(ai_lane)
        CAPTURE_V1_EVENTS_REROUTED.labels(event_source=event_source, from_lane=from_lane).inc(len(rerouted))
        logger.info(
            "capture_internal_rerouted",
            event_source=event_source,
            entry_point=_lane_fn_name(ai_lane),
            from_lane=from_lane,
            rerouted_events=len(rerouted),
            total_events=len(events),
        )

    return _submit_chunks(
        lanes=[
            (lane_events, lane_is_ai)
            for lane_events, lane_is_ai in ((analytics_events, False), (ai_events, True))
            if lane_events
        ],
        token=token,
        event_source=event_source,
        historical_migration=historical_migration,
        process_person_profile=process_person_profile,
        max_attempts=max_attempts,
        timeout=timeout,
    )


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

        Each chunk gets its own retry budget (``max_attempts``) and its own ``timeout``.
        If one chunk fails entirely (transport error), its events appear in
        ``unaccounted``; other chunks' results are preserved and ``error["error"]`` reads
        ``partial_request_failure``.  Retry only ``unaccounted`` and ``retried`` uuids,
        never the whole batch, or the acked events are ingested twice.

        A batch that mixes `$ai_`-prefixed and other names is one request per lane;
        both lanes' chunks share the same worker pool and run concurrently.

    Session replay events ($snapshot, $performance_event, $snapshot_items) are NOT SUPPORTED
    and will raise CaptureInternalError.  Real replay ingestion flows through SDKs directly
    to the capture-rs /s/ endpoint.

    Events with an `$ai_`-prefixed name are sent to the AI lane (see capture_ai_internal)
    and counted as rerouted; the rest of the batch goes to the analytics lane as usual.
    A uuid that appears twice in one batch is rejected before anything is sent.

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
    return _capture_batch_impl(
        events=events,
        token=token,
        event_source=event_source,
        historical_migration=historical_migration,
        process_person_profile=process_person_profile,
        max_attempts=max_attempts,
        timeout=timeout,
        ai_lane=False,
    )


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


def _capture_single_impl(
    *,
    token: str,
    event_name: str,
    event_source: str,
    distinct_id: str,
    timestamp: Optional[str | datetime],
    properties: Optional[dict[str, Any]],
    options: Optional[dict[str, Any]],
    session_id: Optional[str],
    window_id: Optional[str],
    event_uuid: Optional[str],
    process_person_profile: bool,
    historical_migration: bool,
    timeout: float,
    ai_lane: bool,
) -> CaptureInternalResult:
    """Shared body of capture_internal and capture_ai_internal.

    The lane is not a public argument: callers pick it by choosing an entry point,
    so there is exactly one way to reach each lane.
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

    return _capture_batch_impl(
        events=[event_dict],
        token=token,
        event_source=event_source,
        historical_migration=historical_migration,
        process_person_profile=process_person_profile,
        max_attempts=CAPTURE_V1_INTERNAL_MAX_ATTEMPTS,
        timeout=timeout,
        ai_lane=ai_lane,
    )


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
    return _capture_single_impl(
        token=token,
        event_name=event_name,
        event_source=event_source,
        distinct_id=distinct_id,
        timestamp=timestamp,
        properties=properties,
        options=options,
        session_id=session_id,
        window_id=window_id,
        event_uuid=event_uuid,
        process_person_profile=process_person_profile,
        historical_migration=historical_migration,
        timeout=timeout,
        ai_lane=False,
    )


def capture_ai_internal(
    *,
    token: str,
    event_name: str,
    event_source: str,
    distinct_id: str,
    timestamp: Optional[str | datetime] = None,
    properties: Optional[dict[str, Any]] = None,
    options: Optional[dict[str, Any]] = None,
    event_uuid: Optional[str] = None,
    process_person_profile: bool = False,
    timeout: float = 2,
) -> CaptureInternalResult:
    """
    capture_ai_internal is capture_internal for the AI lane.  Use it for every `$ai_*`
    event submitted from the Django app on behalf of a customer team.

    Same arguments, return value, retry behaviour and per-event result semantics as
    capture_internal — see its docstring.  The difference is the destination:
    `/i/v1/ai/events` on capture-ai rather than `/i/v1/analytics/events` on
    capture-analytics.  That deployment is configured for AI traffic: an 8MiB per-event
    ceiling instead of 983040 bytes, and a direct produce to the AI topic.

    A non-`$ai_` name passed here goes to the analytics lane, and an `$ai_` name
    passed to capture_internal goes to the AI lane; each reroute is counted
    (``capture_v1_internal_events_rerouted``). Prefer the matching entry point: it
    keeps ``historical_migration`` and ``session_id`` / ``window_id`` off AI events.

    ``historical_migration`` is not offered: AI backfills do not run through this path.

    Args:
        see capture_internal.  ``session_id`` / ``window_id`` are omitted because they are
        replay concepts and carry no meaning on the AI lane.

    Returns:
        CaptureInternalResult with per-event outcome, exactly as capture_internal.

    Raises:
        CaptureInternalError: on client-side validation failures or HTTP/transport errors.
    """
    return _capture_single_impl(
        token=token,
        event_name=event_name,
        event_source=event_source,
        distinct_id=distinct_id,
        timestamp=timestamp,
        properties=properties,
        options=options,
        session_id=None,
        window_id=None,
        event_uuid=event_uuid,
        process_person_profile=process_person_profile,
        historical_migration=False,
        timeout=timeout,
        ai_lane=True,
    )


def capture_batch_ai_internal(
    *,
    events: list[dict[str, Any]],
    token: str,
    event_source: str,
    process_person_profile: bool = False,
    max_attempts: int = CAPTURE_V1_INTERNAL_MAX_ATTEMPTS,
    timeout: float = 2,
) -> CaptureInternalResult:
    """
    capture_batch_ai_internal is capture_batch_internal for the AI lane.

    Same chunking, concurrency, retry rounds and per-event result merging — see
    capture_batch_internal's docstring.  An event without an `$ai_` prefixed name is
    sent to the analytics lane instead and counted as rerouted; see capture_ai_internal.

    ``historical_migration`` is not offered: AI backfills do not run through this path.
    """
    return _capture_batch_impl(
        events=events,
        token=token,
        event_source=event_source,
        historical_migration=False,
        process_person_profile=process_person_profile,
        max_attempts=max_attempts,
        timeout=timeout,
        ai_lane=True,
    )
