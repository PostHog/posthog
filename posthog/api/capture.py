"""capture_internal — batch-native client for the v1 analytics capture endpoint.

Targets ``/i/v1/analytics/events`` (capture-rs v1).  Analytics events only;
replay event names are rejected client-side.  Typed ``event.options`` replaces
the legacy property-stuffing pattern, and legacy ``$``-keys are defensively
stripped so capture-rs's blind property splicing never produces duplicate keys.
"""

from __future__ import annotations

import time
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
    "Batch submissions to capture v1 endpoint.",
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
        if existing is not None and existing is not False:
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
    if not token:
        raise CaptureInternalError(f"capture_internal ({event_source}): API token is required")
    if not events:
        raise CaptureInternalError(f"capture_internal ({event_source}): at least one event is required")

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
    """Submit multiple events in a single HTTP request to capture-rs (v1 analytics endpoint).

    This is the preferred method for publishing events from the Django app on behalf of
    non-PostHog-admin teams/projects. DO NOT write events directly to ingestion Kafka
    topics — use this!

    Unlike the legacy implementation, this is a true batch POST (not a fan-out of
    individual requests). capture-rs returns per-event results; events that get a
    ``retry`` result are automatically resubmitted up to ``max_attempts`` rounds.
    Transport-level retries on 5xx are handled by urllib3 (3 retries with backoff).

    Args:
        events: list of event dicts to capture. Each MUST include:
            - ``event`` (str): event name (replay names like ``$snapshot`` are rejected)
            - ``distinct_id`` (str): required; may alternatively appear in ``properties``
            - ``properties`` (dict): event properties (can be empty)
            Optional per-event fields:
            - ``timestamp`` (str | datetime): defaults to now UTC if absent
            - ``options`` (dict): typed options — keys: ``cookieless_mode``,
              ``disable_skew_correction``, ``product_tour_id``, ``process_person_profile``.
              Prefer this over stuffing ``$``-prefixed keys into properties.
            - ``session_id``, ``window_id`` (str): top-level fields; legacy
              ``$session_id``/``$window_id`` in properties are also recognized and stripped
            - ``event_uuid`` (str): deterministic UUID; defaults to a fresh UUIDv4
        token: API token to submit events on behalf of (required)
        event_source: observability tag for the internal module/codepath submitting events (required)
        historical_migration: if True, routes events to the historical ingestion path in capture-rs
        process_person_profile: if True, process person profiles per event/team config.
            If False (default), explicitly disables person processing for all events in
            the batch — avoids expensive person profile updates from internal tooling.
        max_attempts: application-level retry budget for per-event ``retry`` results from
            capture-rs (default: 4). Does not affect transport-level 5xx retries.
        timeout: HTTP request timeout in seconds (default: 2)

    Returns:
        CaptureInternalResult with per-event outcomes. Call ``.raise_for_status()`` to raise
        ``CaptureInternalError`` on any failure (whole-request or partial). Inspect
        ``.ok``, ``.dropped``, ``.retried``, ``.unaccounted`` lists for fine-grained handling.

    Raises:
        CaptureInternalError: on client-side validation failures (missing token, empty batch,
            replay event names, unknown option keys) or HTTP/transport errors. The exception
            carries a ``.status_code`` attribute (the HTTP status from capture-rs, or 0 for
            client-side/transport errors).
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

    # Build the index of uuid→event so we can resubmit subsets.
    uuid_to_event: dict[str, dict[str, Any]] = {}
    for uid, entry in zip(uuids, payload["batch"]):
        uuid_to_event[uid] = entry

    # Aggregate terminal outcomes across rounds.
    aggregated: dict[str, dict[str, Any]] = {}
    attempt = 1
    pending_batch = payload["batch"]

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

            try:
                resp = session.post(url, json=submit_payload, headers=headers, timeout=timeout)
            except RequestException as exc:
                CAPTURE_V1_REQUEST_FAILED.labels(event_source=event_source, status_code="transport").inc()
                return CaptureInternalResult(
                    status_code=0,
                    error={"error": "transport_error", "error_description": str(exc)},
                )

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
                return CaptureInternalResult(
                    status_code=resp.status_code,
                    error=error_body,
                )

            # --- 200: parse per-event results ---
            try:
                body = resp.json()
            except Exception:
                return CaptureInternalResult(
                    status_code=resp.status_code,
                    error={"error": "invalid_json", "error_description": "could not parse 200 body"},
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

    # Sweep for uuids never acknowledged by capture-rs.
    for uid in uuid_to_event:
        if uid not in aggregated:
            aggregated[uid] = {"result": "unaccounted"}

    result = CaptureInternalResult(status_code=200, results=aggregated)
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
    """Submit a single event to capture-rs (v1 analytics endpoint).

    This is the preferred method for publishing events from the Django app on behalf of
    non-PostHog-admin teams/projects. DO NOT write events directly to ingestion Kafka
    topics — use this!

    Wraps the event into a 1-element batch and delegates to :func:`capture_batch_internal`.

    Args:
        token: API token to submit the event on behalf of (required)
        event_name: name of the event to publish (required). Replay event names
            (``$snapshot``, ``$performance_event``, ``$snapshot_items``) are rejected
            client-side — those go through the dedicated replay capture path.
        event_source: observability tag for the internal module/codepath submitting
            the event (required). Used in Prometheus metrics to detect new call sites.
        distinct_id: distinct ID for the event (required)
        timestamp: event timestamp (optional; defaults to now UTC). Accepts datetime
            objects or ISO8601 strings.
        properties: event properties dict (optional; can be empty). Legacy ``$``-prefixed
            keys that map to typed options (``$session_id``, ``$window_id``,
            ``$cookieless_mode``, ``$ignore_sent_at``, ``$product_tour_id``,
            ``$process_person_profile``) are automatically extracted and stripped.
        options: typed event options dict (optional). Valid keys: ``cookieless_mode``,
            ``disable_skew_correction``, ``product_tour_id``, ``process_person_profile``.
            Prefer this over stuffing ``$``-prefixed keys into properties.
        session_id: session ID (optional). Preferred over ``$session_id`` in properties.
        window_id: window ID (optional). Preferred over ``$window_id`` in properties.
        event_uuid: deterministic UUID to assign to the event (optional; default:
            capture-rs assigns a fresh UUIDv7). Use when the caller needs a stable,
            queryable event UUID — e.g. to link back to the event from an admin UI.
        process_person_profile: if True, process the person profile for this event
            according to the caller's settings. If False (default), explicitly disables
            person processing — avoids expensive person profile updates from internal
            tooling.
        historical_migration: if True, routes to the historical ingestion path in
            capture-rs (separate Kafka topic/consumer group).
        timeout: HTTP request timeout in seconds (default: 2)

    Returns:
        CaptureInternalResult with per-event outcome. Call ``.raise_for_status()`` to raise
        ``CaptureInternalError`` on failure. For best-effort fire-and-forget patterns,
        check ``.succeeded()`` instead.

    Raises:
        CaptureInternalError: on client-side validation failures or HTTP/transport errors.
            Carries a ``.status_code`` attribute (HTTP status from capture-rs, or 0 for
            client-side/transport errors) so callers can propagate into their own responses.
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
