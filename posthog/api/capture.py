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
    "Events received by capture_internal, tagged by source.",
    labelnames=["event_source"],  # which internal codepath submitted this event
)


class CaptureInternalError(Exception):
    pass


@timed("capture_internal_event_submission")
def capture_internal(
    *,  # only keyword args for clarity
    token: str,
    event_name: str,
    event_source: str,
    distinct_id: str,
    timestamp: Optional[datetime | str],
    properties: dict[str, Any],
    process_person_profile: bool = False,
) -> Response:
    """
    capture_internal submits a single-event capture request payload to the capture-rs backend service.
    This is the preferred method for publishing events from the Django app on behalf of non-PostHog admin
    teams/projects. PLEASE DO NOT write events directly to ingestion Kafka topics - USE THIS!

    Args:
        token: API token to use for the event (required)
        event_name: the name of the event to be published (required)
        event_source: the caller, for observability of internal use cases (required)
        distinct_id: the distict ID of the event (optional; required in properties if absent)
        timestamp: the timestamp of the event to be published (optional; will be set to now UTC if absent)
        properties: event payload to submit to capture-rs backend (required; can be empty)
        process_person_profile: if TRUE, process the person profile for the event according to the caller's settings.
                                if FALSE, disable person processing for this event.

    Returns:
        Response object, the result of POSTing the event payload to the capture-rs backend service.
    """
    logger.debug(
        "capture_internal",
        token=token,
        distinct_id=distinct_id,
        event_name=event_name,
        event_source=event_source,
    )

    event_payload = prepare_capture_internal_payload(
        token, event_name, event_source, distinct_id, timestamp, properties, process_person_profile
    )

    # determine if this is a recordings or events type, route to correct capture endpoint
    resolved_capture_url = f"{CAPTURE_INTERNAL_URL}{NEW_ANALYTICS_CAPTURE_ENDPOINT}"
    if event_name in SESSION_RECORDING_EVENT_NAMES:
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


def capture_batch_internal(
    *,
    events: list[dict[str, Any]],
    event_source: str,
    token: str,
    process_person_profile: bool = False,
) -> list[Future]:
    """
    capture_batch_internal submits multiple capture request payloads to
    PostHog (capture-rs backend) concurrently using ThreadPoolExecutor.
    This does not submit serial requests to the /batch/ endpoint, so historical
    event submission is not supported.

    Args:
        events: List of event dictionaries to capture. The payloads MUST include
                well-formed distinct_id, timestamp, and optional properties map
        event_source: observability tag for error logging
        token: Optional API token to use for all events (overrides individual event tokens)
        process_person_profile: if FALSE (default) specifically disable person processing on each event

    Returns:
        List of Future objects that the caller can await to get Response objects or thrown Exceptions
    """
    logger.debug(
        "capture_batch_internal",
        event_count=len(events),
        event_source=event_source,
        token=token,
        process_person_profile=process_person_profile,
    )

    futures: list[Future] = []

    with ThreadPoolExecutor(max_workers=CAPTURE_INTERNAL_MAX_WORKERS) as executor:
        # Note:
        # 1. token should be supplied by caller, and be consistent per batch submitted.
        #    new capture_internal will attempt to extract from each event if missing
        # 2. distinct_id should be present on each event since these can differ within a batch
        for event in events:
            properties: dict[str, Any] = event.get("properties", {})
            distinct_id: str = event.get("distinct_id", "")
            timestamp: str = event.get("timestamp", properties.get("timestamp", ""))

            future = executor.submit(
                capture_internal,
                token=token,
                event_name=event.get("event", ""),
                event_source=event_source,
                distinct_id=distinct_id,
                timestamp=timestamp,
                properties=properties,
                process_person_profile=process_person_profile,
            )
            futures.append(future)

    return futures


# prep payload for new capture_internal to POST to capture-rs
def prepare_capture_internal_payload(
    token: str,
    event_name: str,
    event_source: str,
    distinct_id: Optional[str],
    timestamp: Optional[datetime | str],
    properties: dict[str, Any],
    process_person_profile: bool = False,
) -> dict[str, Any]:
    # mark event as internal for observability
    properties["capture_internal"] = True

    # for back compatibility, if this is TRUE, we don't change the event
    # so existing event (or team acct) settings for $process_person_profile
    # will apply. If FALSE, we set the prop to explicitly force the issue.
    # with FALSE as default, we avoid accidental internal uses that cause
    # expensive person profile updates for no reason
    if not process_person_profile:
        properties["$process_person_profile"] = process_person_profile

    # ensure args passed into capture_internal that
    # override event attributes are well formed

    if not token:
        raise CaptureInternalError(f"capture_internal ({event_source}, {event_name}): API token is required")

    if not distinct_id:
        distinct_id = properties.get("distinct_id", None)
    if not distinct_id:
        raise CaptureInternalError(f"capture_internal ({event_source}, {event_name}): distinct ID is required")

    if not event_name:
        raise CaptureInternalError(f"capture_internal ({event_source}): event name is required")

    event_timestamp = datetime.now(UTC).isoformat()
    if timestamp:
        if isinstance(timestamp, datetime):
            event_timestamp = timestamp.replace(tzinfo=UTC).isoformat()
        elif isinstance(timestamp, str):
            # assume its an ISO8601 string and submit it as-is
            event_timestamp = timestamp

    return {
        "api_key": token,
        "timestamp": event_timestamp,
        "distinct_id": distinct_id,
        "event": event_name,
        "properties": properties,
    }
