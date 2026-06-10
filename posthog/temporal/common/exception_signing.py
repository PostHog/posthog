"""Sign `$exception` events captured by temporal workers.

The PostHog ingest key is public, so a forged `$exception` event reaches Error Tracking and
any downstream webhook indistinguishably from a real one. Workers therefore attach an HMAC
signature over a self-contained *attestation* — a small JSON blob carrying the exception's
type/message/top-frame plus whatever job context is on the event. A consumer that shares the
secret can verify the attestation and trust only its contents (server-side ingestion mutates
the reserved ``$exception_*`` fields, but custom properties pass through byte-for-byte).

Wired as a posthoganalytics ``before_send`` hook in ``start_temporal_worker`` so it covers
every capture path (the temporal interceptor and inline ``capture_exception`` calls) across
all task queues. Pure stdlib so it is safe inside the workflow sandbox.
"""

import hmac
import json
import hashlib
import datetime as dt
from typing import Any, Callable, Optional

import structlog

logger = structlog.get_logger(__name__)

ATTESTATION_PROPERTY = "$temporal_exception_attestation"
SIGNATURE_PROPERTY = "$temporal_exception_signature"

# Bound the embedded message so a pathological exception can't bloat the event. The consumer
# only needs enough to triage; this is plenty.
MAX_MESSAGE_LENGTH = 4096

# Optional job-context keys copied verbatim from the event properties when present. These are
# set on data-import activities (via ``properties_to_log``) and the temporal interceptor;
# absent on other workers, in which case they serialize as null.
_JOB_CONTEXT = {
    "team_id": "team_id",
    "run_id": "run_id",
    "source_id": "source_id",
    "schema_id": "schema_id",
    "workflow_run_id": "temporal.workflow.run_id",
}


def _first_exception(properties: dict[str, Any]) -> dict[str, Any]:
    exception_list = properties.get("$exception_list")
    if isinstance(exception_list, list) and exception_list and isinstance(exception_list[0], dict):
        return exception_list[0]
    return {}


def _top_frame(properties: dict[str, Any]) -> Optional[str]:
    """Best path-like identifier of the first in-app frame, falling back to the first frame.

    At capture time frames carry ``filename``/``abs_path``/``module`` (the resolved ``source``
    field is added later, server-side), so we record our own value here for the consumer to
    attribute against.
    """
    fallback: Optional[str] = None
    exception_list = properties.get("$exception_list")
    if not isinstance(exception_list, list):
        return None
    for exc in exception_list:
        if not isinstance(exc, dict):
            continue
        stacktrace = exc.get("stacktrace")
        frames = stacktrace.get("frames") if isinstance(stacktrace, dict) else None
        if not isinstance(frames, list):
            continue
        for frame in frames:
            if not isinstance(frame, dict):
                continue
            path = frame.get("filename") or frame.get("abs_path") or frame.get("module")
            if not path:
                continue
            if frame.get("in_app") is True:
                return path
            if fallback is None:
                fallback = path
    return fallback


def build_attestation(properties: dict[str, Any], *, captured_at: str) -> dict[str, Any]:
    """Build the signable attestation from a built ``$exception`` event's properties."""
    exc = _first_exception(properties)
    message = exc.get("value")
    if isinstance(message, str) and len(message) > MAX_MESSAGE_LENGTH:
        message = message[:MAX_MESSAGE_LENGTH]

    attestation: dict[str, Any] = {
        "v": 1,
        "exception_type": exc.get("type"),
        "message": message if isinstance(message, str) else None,
        "top_frame": _top_frame(properties),
        "captured_at": captured_at,
    }
    for out_key, prop_key in _JOB_CONTEXT.items():
        attestation[out_key] = properties.get(prop_key)
    return attestation


def serialize_attestation(attestation: dict[str, Any]) -> str:
    """Canonical, stable serialization. The consumer signs/verifies this exact string."""
    return json.dumps(attestation, separators=(",", ":"), sort_keys=True)


def sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def make_exception_signer(secret: str) -> Callable[[dict[str, Any]], Optional[dict[str, Any]]]:
    """Build a posthoganalytics ``before_send`` hook that signs ``$exception`` events.

    Non-exception events pass through untouched. Any failure is swallowed (and logged) so
    signing can never drop or break exception capture.
    """

    def before_send(event: dict[str, Any]) -> Optional[dict[str, Any]]:
        try:
            if not isinstance(event, dict) or event.get("event") != "$exception":
                return event
            properties = event.get("properties")
            if not isinstance(properties, dict):
                return event

            captured_at = event.get("timestamp")
            if not isinstance(captured_at, str):
                captured_at = dt.datetime.now(dt.UTC).isoformat()

            attestation = serialize_attestation(build_attestation(properties, captured_at=captured_at))
            properties[ATTESTATION_PROPERTY] = attestation
            properties[SIGNATURE_PROPERTY] = sign(secret, attestation)
        except Exception:
            logger.exception("Failed to sign temporal exception event")
        return event

    return before_send
