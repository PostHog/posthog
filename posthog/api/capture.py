from concurrent.futures import ThreadPoolExecutor, Future

import structlog
from requests import Response, Session
from requests.adapters import HTTPAdapter, Retry
from datetime import datetime, UTC
from prometheus_client import Counter
from typing import Any, Optional

from posthog.logging.timing import timed
from posthog.settings.ingestion import (
    CAPTURE_INTERNAL_URL,
    CAPTURE_REPLAY_INTERNAL_URL,
    CAPTURE_INTERNAL_MAX_WORKERS,
    NEW_ANALYTICS_CAPTURE_ENDPOINT,
    REPLAY_CAPTURE_ENDPOINT,
)

logger = structlog.get_logger(__name__)

# These event names are reserved for internal use and refer to non-analytics
# events that are ingested via a separate path than analytics events. They have
# fewer restrictions on e.g. the order they need to be processed in.
SESSION_RECORDING_DEDICATED_KAFKA_EVENTS = ("$snapshot_items",)
SESSION_RECORDING_EVENT_NAMES = ("$snapshot", "$performance_event", *SESSION_RECORDING_DEDICATED_KAFKA_EVENTS)

# let's track who is using this to detect new (ab)usive call sites quickly
CAPTURE_INTERNAL_EVENT_SUBMITTED_COUNTER = Counter(
    "capture_internal_event_submitted",
    "Events received by capture_internal, tagged by resource type.",
    labelnames=["event_source"],
)


class CaptureInternalError(Exception):
    pass


# TODO: replace raw_event input with structured inputs after transition off old capture_internal
@timed("capture_internal_event_submission")
def new_capture_internal(
    token: Optional[str], distinct_id: Optional[str], raw_event: dict[str, Any], process_person_profile: bool = False
) -> Response:
    """
    new_capture_internal submits a single-event capture request payload to the capture-rs backend service.

    Args:
        token: API token to use for the event.
        distinct_id: distinct_id to use for the event. Will be extracted from raw_event if not provided.
        raw_event: raw event payload to enrich and submit to capture-rs.
        process_person_profile: if TRUE, process the person profile for the event according to the caller's settings.
                                if FALSE, disable person processing for this event.

    Returns:
        Response object, the result of POSTing the event payload to the capture-rs backend service.
    """
    logger.debug(
        "new_capture_internal", token=token, distinct_id=distinct_id, event_name=raw_event.get("event", "MISSING")
    )

    event_payload = prepare_capture_internal_payload(token, distinct_id, raw_event, process_person_profile)
    # determine if this is a recordings or events type, route to correct capture endpoint
    resolved_capture_url = f"{CAPTURE_INTERNAL_URL}{NEW_ANALYTICS_CAPTURE_ENDPOINT}"
    if event_payload["event"] in SESSION_RECORDING_EVENT_NAMES:
        resolved_capture_url = f"{CAPTURE_REPLAY_INTERNAL_URL}{REPLAY_CAPTURE_ENDPOINT}"

    with Session() as s:
        s.mount(
            resolved_capture_url,
            HTTPAdapter(
                max_retries=Retry(
                    total=3, backoff_factor=0.1, status_forcelist=[500, 502, 503, 504], allowed_methods={"POST"}
                )
            ),
        )

        CAPTURE_INTERNAL_EVENT_SUBMITTED_COUNTER.labels(event_source="TODO").inc()
        return s.post(
            resolved_capture_url,
            json=event_payload,
            timeout=2,
        )


def new_capture_batch_internal(
    events: list[dict[str, Any]],
    token: Optional[str] = None,
    process_person_profile: bool = False,
) -> list[Future]:
    """
    new_capture_batch_internal submits multiple capture request payloads to
    PostHog (capture-rs backend) concurrently using ThreadPoolExecutor.

    Args:
        events: List of event dictionaries to capture
        token: Optional API token to use for all events (overrides individual event tokens)
        process_person_profile: if FALSE (default) specifically disable person processing on each event

    Returns:
        List of Future objects that the caller can await to get Response objects or thrown Exceptions
    """
    logger.debug(
        "new_capture_batch_internal",
        event_count=len(events),
        token=token,
        process_person_profile=process_person_profile,
    )

    futures: list[Future] = []

    with ThreadPoolExecutor(max_workers=CAPTURE_INTERNAL_MAX_WORKERS) as executor:
        # Note:
        # 1. token should be supplied by caller, and be consistent per batch submitted.
        #    new_capture_internal will attempt to extract from each event if missing
        # 2. distinct_id should be present on each event since these can differ within a batch
        for event in events:
            future = executor.submit(
                new_capture_internal,
                token=token,
                distinct_id=None,
                raw_event=event,
                process_person_profile=process_person_profile,
            )
            futures.append(future)

    return futures


# prep payload for new_capture_internal to POST to capture-rs
def prepare_capture_internal_payload(
    token: Optional[str],
    distinct_id: Optional[str],
    raw_event: dict[str, Any],
    process_person_profile: bool = False,
) -> dict[str, Any]:
    # mark event as internal for observability
    properties = raw_event.get("properties", {})
    properties["capture_internal"] = True

    # for back compat, if the caller specifies TRUE to process_person_profile
    # we don't change the event contents at all; either the caller set the
    # event prop to force the issue, or we rely on the caller's default PostHog
    # person processing settings to decide during ingest processing.
    # If the caller set process_person_profile to FALSE, we *do* explictly
    # set it as an event property, to ensure internal capture events don't
    # engage in expensive person processing without explicitly opting in
    if not process_person_profile:
        properties["$process_person_profile"] = process_person_profile

    # ensure args passed into capture_internal that
    # override event attributes are well formed
    if token is None:
        token = raw_event.get("api_key", raw_event.get("token", None))
    if token is None:
        raise CaptureInternalError("capture_internal: API token is required")

    if distinct_id is None:
        distinct_id = raw_event.get("distinct_id", None)
    if distinct_id is None:
        distinct_id = properties.get("distinct_id", None)
    if distinct_id is None:
        raise CaptureInternalError("capture_internal: distinct ID is required")

    event_name = raw_event.get("event", None)
    if event_name is None:
        raise CaptureInternalError("capture_internal: event name is required")

    event_timestamp = raw_event.get("timestamp", None)
    if event_timestamp is None:
        event_timestamp = datetime.now(UTC).isoformat()

    return {
        "api_key": token,
        "timestamp": event_timestamp,
        "distinct_id": distinct_id,
        "event": event_name,
        "properties": properties,
    }
