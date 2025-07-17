from concurrent.futures import ThreadPoolExecutor, Future

import structlog
from requests import HTTPError, Response, Session
from requests.adapters import HTTPAdapter, Retry
from datetime import datetime, UTC
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from enum import Enum
from prometheus_client import Counter
from rest_framework import status
from token_bucket import Limiter, MemoryStorage
from typing import Any, Optional

from posthog.api.utils import get_token
from posthog.api.csp import process_csp_report
from posthog.exceptions import generate_exception_response
from posthog.exceptions_capture import capture_exception
from posthog.logging.timing import timed
from posthog.metrics import LABEL_RESOURCE_TYPE
from posthog.settings.ingestion import (
    CAPTURE_INTERNAL_URL,
    CAPTURE_REPLAY_INTERNAL_URL,
    CAPTURE_INTERNAL_MAX_WORKERS,
    NEW_ANALYTICS_CAPTURE_ENDPOINT,
    REPLAY_CAPTURE_ENDPOINT,
)
from posthog.utils_cors import cors_response

logger = structlog.get_logger(__name__)

LIMITER = Limiter(
    rate=settings.PARTITION_KEY_BUCKET_REPLENTISH_RATE,
    capacity=settings.PARTITION_KEY_BUCKET_CAPACITY,
    storage=MemoryStorage(),
)
LOG_RATE_LIMITER = Limiter(
    rate=1 / 60,
    capacity=1,
    storage=MemoryStorage(),
)

# These event names are reserved for internal use and refer to non-analytics
# events that are ingested via a separate path than analytics events. They have
# fewer restrictions on e.g. the order they need to be processed in.
SESSION_RECORDING_DEDICATED_KAFKA_EVENTS = ("$snapshot_items",)
SESSION_RECORDING_EVENT_NAMES = ("$snapshot", "$performance_event", *SESSION_RECORDING_DEDICATED_KAFKA_EVENTS)

INTERNAL_EVENTS_RECEIVED_COUNTER = Counter(
    "capture_internal_events_received_total",
    "Events received by capture, tagged by resource type.",
    labelnames=[LABEL_RESOURCE_TYPE, "token"],
)


class InputType(Enum):
    EVENTS = "events"
    REPLAY = "replay"


@csrf_exempt
@timed("posthog_cloud_csp_event_endpoint")
def get_csp_event(request):
    # we want to handle this as early as possible and avoid any processing
    if request.method == "OPTIONS":
        return cors_response(request, JsonResponse({"status": 1}))

    debug_enabled = request.GET.get("debug", "").lower() == "true"
    if debug_enabled:
        logger.exception(
            "CSP debug request",
            error=ValueError("CSP debug request"),
            method=request.method,
            url=request.build_absolute_uri(),
            content_type=request.content_type,
            headers=dict(request.headers),
            query_params=dict(request.GET),
            body_size=len(request.body) if request.body else 0,
            body=request.body.decode("utf-8", errors="ignore") if request.body else None,
        )

    csp_report, error_response = process_csp_report(request)
    if error_response:
        return error_response

    first_distinct_id = None  # temp: only used for feature flag check
    if csp_report and isinstance(csp_report, list):
        # For list of reports, use the first one's distinct_id for feature flag check
        first_distinct_id = csp_report[0].get("distinct_id", None)
    elif csp_report and isinstance(csp_report, dict):
        # For single report, use the distinct_id for the same
        first_distinct_id = csp_report.get("distinct_id", None)
    else:
        # mimic what get_event does if no data is returned from process_csp_report
        return cors_response(
            request,
            generate_exception_response(
                "csp_report_capture",
                f"Failed to submit CSP report",
                code="invalid_payload",
                type="invalid_payload",
                status_code=status.HTTP_400_BAD_REQUEST,
            ),
        )

    try:
        token = get_token(csp_report, request)

        if isinstance(csp_report, list):
            futures = new_capture_batch_internal(csp_report, token, False)
            for future in futures:
                result = future.result()
                result.raise_for_status()
        else:
            resp = new_capture_internal(token, first_distinct_id, csp_report, False)
            resp.raise_for_status()

        return cors_response(request, HttpResponse(status=status.HTTP_204_NO_CONTENT))

    except HTTPError as hte:
        capture_exception(hte, {"capture-http": "csp_report", "ph-team-token": token})
        logger.exception("csp_report_capture_http_error", exc_info=hte)
        return cors_response(
            request,
            generate_exception_response(
                "csp_report_capture",
                f"Failed to submit CSP report",
                code="capture_http_error",
                type="capture_http_error",
                status_code=hte.response.status_code,
            ),
        )
    except Exception as e:
        capture_exception(e, {"capture-pathway": "csp_report", "ph-team-token": token})
        logger.exception("csp_report_capture_error", exc_info=e)
        return cors_response(
            request,
            generate_exception_response(
                "csp_report_capture",
                f"Failed to submit CSP report",
                code="capture_error",
                type="capture_error",
                status_code=status.HTTP_400_BAD_REQUEST,
            ),
        )


class CaptureInternalError(Exception):
    pass


# TODO: replace raw_event input with structured inputs after transition off old capture_internal
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

        return s.post(
            resolved_capture_url,
            json=event_payload,
            timeout=2,
        )


# TODO: rename as capture_batch_internal after the trasition from old capture_internal is complete
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
