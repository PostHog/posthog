import dataclasses
import json
import re
from random import random
from concurrent.futures import ThreadPoolExecutor, Future

import structlog
import time
from requests import Response, Session
from requests.adapters import HTTPAdapter, Retry
from collections.abc import Iterator
from datetime import datetime, timedelta, UTC
from dateutil import parser
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from enum import Enum
from kafka.errors import KafkaError, MessageSizeTooLargeError, KafkaTimeoutError
from kafka.producer.future import FutureRecordMetadata
from prometheus_client import Counter, Gauge, Histogram
from rest_framework import status
from statshog.defaults.django import statsd
from token_bucket import Limiter, MemoryStorage
from typing import Any, Optional, Literal
import posthoganalytics

from ee.billing.quota_limiting import QuotaLimitingCaches
from posthog.api.utils import get_data, get_token, safe_clickhouse_string
from posthog.api.csp import process_csp_report
from posthog.cache_utils import cache_for
from posthog.exceptions import generate_exception_response
from posthog.exceptions_capture import capture_exception
from posthog.kafka_client.client import KafkaProducer, session_recording_kafka_producer
from posthog.kafka_client.topics import (
    KAFKA_EVENTS_PLUGIN_INGESTION,
    KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL,
    KAFKA_SESSION_RECORDING_EVENTS,
    KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS,
    KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_OVERFLOW,
    KAFKA_EXCEPTIONS_INGESTION,
)
from posthog.logging.timing import timed
from posthog.metrics import KLUDGES_COUNTER, LABEL_RESOURCE_TYPE
from posthog.models.utils import UUIDT
from posthog.redis import get_client
from posthog.settings.ingestion import (
    CAPTURE_INTERNAL_URL,
    CAPTURE_REPLAY_INTERNAL_URL,
    CAPTURE_INTERNAL_MAX_WORKERS,
    NEW_ANALYTICS_CAPTURE_ENDPOINT,
    REPLAY_CAPTURE_ENDPOINT,
)
from posthog.session_recordings.session_recording_helpers import (
    preprocess_replay_events_for_blob_ingestion,
    split_replay_events,
    byte_size_dict,
)
from posthog.storage import object_storage
from posthog.utils import get_ip_address
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

# TODO we should eventually be able to remove the code path this is counting
LEGACY_SNAPSHOT_EVENTS_RECEIVED_COUNTER = Counter(
    "capture_legacy_snapshot_events_received_total",
    "Legacy snapshot events received by capture, we should receive zero of these.",
)

EVENTS_RECEIVED_COUNTER = Counter(
    "capture_events_received_total",
    "Events received by capture, tagged by resource type.",
    labelnames=[LABEL_RESOURCE_TYPE],
)

EVENTS_DROPPED_OVER_QUOTA_COUNTER = Counter(
    "capture_events_dropped_over_quota",
    "Events dropped by capture due to quota-limiting, per resource_type and token.",
    labelnames=[LABEL_RESOURCE_TYPE, "token"],
)

EVENTS_REJECTED_OVER_QUOTA_COUNTER = Counter(
    "capture_events_rejected_over_quota",
    "Events rejected by capture due to quota-limiting, send a quota limiting signal to the client which stops sending us traffic.",
    labelnames=[LABEL_RESOURCE_TYPE],
)

PARTITION_KEY_CAPACITY_EXCEEDED_COUNTER = Counter(
    "capture_partition_key_capacity_exceeded_total",
    "Indicates that automatic partition override is active for a given key. Value incremented once a minute.",
    labelnames=["partition_key"],
)

TOKEN_SHAPE_INVALID_COUNTER = Counter(
    "capture_token_shape_invalid_total",
    "Events dropped due to an invalid token shape, per reason.",
    labelnames=["reason"],
)

OVERFLOWING_KEYS_LOADED_GAUGE = Gauge(
    "capture_overflowing_keys_loaded",
    "Number of keys loaded for the overflow redirection, per resource_type.",
    labelnames=[LABEL_RESOURCE_TYPE],
)

REPLAY_MESSAGE_SIZE_TOO_LARGE_COUNTER = Counter(
    "capture_replay_message_size_too_large",
    "Events dropped due to a replay message being too large",
)

KAFKA_TIMEOUT_ERROR_COUNTER = Counter(
    "capture_replay_kafka_timeout_error",
    "kafka timeout error while writing to replay kafka topic",
    # from a cardinality perspective
    # retry_count should only have 0, 1, or 2
    # and status_code only has 400 or 502
    labelnames=["retry_count", "status_code"],
)

REPLAY_MESSAGE_PRODUCTION_TIMER = Histogram(
    "capture_replay_message_production_seconds",
    "Time taken to produce a set of replay messages",
)

# This flag tells us to use the cookieless mode, and that we can't use distinct id as the partition key
COOKIELESS_MODE_FLAG_PROPERTY = "$cookieless_mode"


# This is a heuristic of ids we have seen used as anonymous. As they frequently
# have significantly more traffic than non-anonymous distinct_ids, and likely
# don't refer to the same underlying person we prefer to partition them randomly
# to distribute the load.
# This list mimics the array used in the plugin-server, and should be kept in-sync. See:
# https://github.com/PostHog/posthog/blob/master/plugin-server/src/worker/ingestion/person-state.ts#L22-L33
LIKELY_ANONYMOUS_IDS = {
    "0",
    "anon",
    "anon_id",
    "anonymous",
    "anonymous_id",
    "distinct_id",
    "distinctid",
    "email",
    "false",
    "guest",
    "id",
    "nan",
    "none",
    "not_authenticated",
    "null",
    "true",
    "undefined",
}

OVERFLOWING_REDIS_KEY = "@posthog/capture-overflow/"

TOKEN_DISTINCT_ID_PAIRS_TO_DROP: Optional[set[str]] = None


def get_tokens_to_drop() -> set[str]:
    global TOKEN_DISTINCT_ID_PAIRS_TO_DROP

    if TOKEN_DISTINCT_ID_PAIRS_TO_DROP is None:
        TOKEN_DISTINCT_ID_PAIRS_TO_DROP = set()
        if settings.DROP_EVENTS_BY_TOKEN_DISTINCT_ID:
            # DROP_EVENTS_BY_TOKEN_DISTINCT_ID is a comma separated list of <team_id:distinct_id> pairs where the distinct_id is optional
            TOKEN_DISTINCT_ID_PAIRS_TO_DROP = set(settings.DROP_EVENTS_BY_TOKEN_DISTINCT_ID.split(","))

    return TOKEN_DISTINCT_ID_PAIRS_TO_DROP


class InputType(Enum):
    EVENTS = "events"
    REPLAY = "replay"


def build_kafka_event_data(
    distinct_id: str,
    ip: Optional[str],
    site_url: str,
    data: dict,
    now: datetime,
    sent_at: Optional[datetime],
    event_uuid: UUIDT,
    token: str,
) -> dict:
    logger.debug("build_kafka_event_data", token=token)
    res = {
        "uuid": str(event_uuid),
        "distinct_id": safe_clickhouse_string(distinct_id),
        "ip": safe_clickhouse_string(ip) if ip else ip,
        "site_url": safe_clickhouse_string(site_url),
        "data": json.dumps(data),
        "now": now.isoformat(),
        "token": token,
    }

    # Equivalent to rust captures "skip_serialising_if = Option::is_none"
    if sent_at:
        res["sent_at"] = sent_at.isoformat()

    return res


def _kafka_topic(event_name: str, historical: bool = False, overflowing: bool = False) -> str:
    # To allow for different quality of service on session recordings
    # and other events, we push to a different topic.

    match event_name:
        case "$snapshot":
            LEGACY_SNAPSHOT_EVENTS_RECEIVED_COUNTER.inc()
            return KAFKA_SESSION_RECORDING_EVENTS
        case "$snapshot_items":
            if overflowing:
                return KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_OVERFLOW
            return KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS
        case "$exception":
            return KAFKA_EXCEPTIONS_INGESTION
        case _:
            # If the token is in the TOKENS_HISTORICAL_DATA list, we push to the
            # historical data topic.
            if historical:
                return KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL
            return KAFKA_EVENTS_PLUGIN_INGESTION


def log_event(
    data: dict,
    event_name: str,
    partition_key: Optional[str],
    headers: Optional[list] = None,
    historical: bool = False,
    overflowing: bool = False,
) -> FutureRecordMetadata:
    kafka_topic = _kafka_topic(event_name, historical=historical, overflowing=overflowing)

    logger.debug("logging_event", event_name=event_name, kafka_topic=kafka_topic)

    # TODO: Handle Kafka being unavailable with exponential backoff retries
    try:
        if event_name in SESSION_RECORDING_DEDICATED_KAFKA_EVENTS:
            producer = session_recording_kafka_producer()
        else:
            producer = KafkaProducer()

        future = producer.produce(topic=kafka_topic, data=data, key=partition_key, headers=headers)
        statsd.incr("posthog_cloud_plugin_server_ingestion")
        return future
    except Exception:
        statsd.incr("capture_endpoint_log_event_error")
        logger.exception("Failed to produce event to Kafka topic %s with error", kafka_topic)
        raise


def _datetime_from_seconds_or_millis(timestamp: str) -> datetime:
    if len(timestamp) > 11:  # assuming milliseconds / update "11" to "12" if year > 5138 (set a reminder!)
        timestamp_number = float(timestamp) / 1000
    else:
        timestamp_number = int(timestamp)
        KLUDGES_COUNTER.labels(kludge="sent_at_seconds_timestamp").inc()

    return datetime.fromtimestamp(timestamp_number, UTC)


def _get_retry_count(request) -> int | None:
    """
    The web sdk advertises a retry count once it is retrying (other SDKs do not)
    so it isn't guaranteed to be present
    but can be used when present to try to check if a web client is retrying
    """
    try:
        return int(request.GET.get("retry_count", 0))
    except ValueError:
        return None


def _get_sent_at(data, request) -> tuple[Optional[datetime], Any]:
    try:
        if request.GET.get("_"):  # posthog-js
            sent_at = request.GET["_"]
        elif isinstance(data, dict) and data.get("sent_at"):  # posthog-android, posthog-ios
            sent_at = data["sent_at"]
        elif request.POST.get("sent_at"):  # when urlencoded body and not JSON (in some test)
            sent_at = request.POST["sent_at"]
            if sent_at:
                KLUDGES_COUNTER.labels(kludge="sent_at_post_field").inc()
        else:
            return None, None

        if re.match(r"^\d+(?:\.\d+)?$", sent_at):
            return _datetime_from_seconds_or_millis(sent_at), None

        KLUDGES_COUNTER.labels(kludge="sent_at_not_timestamp").inc()
        return parser.isoparse(sent_at), None
    except Exception as error:
        statsd.incr("capture_endpoint_invalid_sent_at")
        logger.exception(f"Invalid sent_at value", error=error)
        return (
            None,
            cors_response(
                request,
                generate_exception_response(
                    "capture",
                    f"Malformed request data, invalid sent at: {error}",
                    code="invalid_payload",
                ),
            ),
        )


def _check_token_shape(token: Any) -> Optional[str]:
    if not token:
        return "empty"
    if not isinstance(token, str):
        return "not_string"
    if len(token) > 64:
        return "too_long"
    if not token.isascii():  # Legacy tokens were base64, so let's be permissive
        return "not_ascii"
    if token.startswith("phx_"):  # Used by previous versions of the zapier integration, can happen on user error
        return "personal_api_key"
    return None


def get_distinct_id(data: dict[str, Any]) -> str:
    raw_value: Any = ""
    try:
        raw_value = data["$distinct_id"]
    except KeyError:
        try:
            raw_value = data["properties"]["distinct_id"]
        except KeyError:
            try:
                raw_value = data["distinct_id"]
            except KeyError:
                statsd.incr("invalid_event", tags={"error": "missing_distinct_id"})
                raise ValueError('All events must have the event field "distinct_id"!')
        except TypeError:
            raise ValueError(f'Properties must be a JSON object, received {type(data["properties"]).__name__}!')
    if not raw_value:
        statsd.incr("invalid_event", tags={"error": "invalid_distinct_id"})
        raise ValueError('Event field "distinct_id" should not be blank!')
    return str(raw_value)[0:200]


def enforce_numeric_offset(properties: dict[str, Any]):
    try:
        raw_offset = properties["offset"]
    except KeyError:
        return

    if not isinstance(raw_offset, int):
        raise ValueError(f'Event field "offset" must be numeric, received {type(properties["offset"]).__name__}!')


def drop_performance_events(events: list[Any]) -> list[Any]:
    cleaned_list = [event for event in events if event.get("event") != "$performance_event"]
    return cleaned_list


@dataclasses.dataclass(frozen=True)
class EventsOverQuotaResult:
    events: list[Any]
    events_were_limited: bool
    exceptions_were_limited: bool
    recordings_were_limited: bool


def drop_events_over_quota(token: str, events: list[Any]) -> EventsOverQuotaResult:
    if not settings.EE_AVAILABLE:
        return EventsOverQuotaResult(events, False, False, False)

    from ee.billing.quota_limiting import QuotaResource, list_limited_team_attributes

    results = []
    limited_tokens_events = list_limited_team_attributes(
        QuotaResource.EVENTS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
    )
    limited_tokens_exceptions = list_limited_team_attributes(
        QuotaResource.EXCEPTIONS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
    )
    limited_tokens_recordings = list_limited_team_attributes(
        QuotaResource.RECORDINGS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
    )

    recordings_were_limited = False
    exceptions_were_limited = False
    events_were_limited = False
    for event in events:
        if event.get("event") in SESSION_RECORDING_EVENT_NAMES:
            EVENTS_RECEIVED_COUNTER.labels(resource_type="recordings").inc()
            if token in limited_tokens_recordings:
                EVENTS_DROPPED_OVER_QUOTA_COUNTER.labels(resource_type="recordings", token=token).inc()
                if settings.QUOTA_LIMITING_ENABLED:
                    recordings_were_limited = True
                    continue

        elif event.get("event") == "$exception":
            EVENTS_RECEIVED_COUNTER.labels(resource_type="exceptions").inc()
            if token in limited_tokens_exceptions:
                EVENTS_DROPPED_OVER_QUOTA_COUNTER.labels(resource_type="exceptions", token=token).inc()
                if settings.QUOTA_LIMITING_ENABLED:
                    exceptions_were_limited = True
                    continue

        else:
            EVENTS_RECEIVED_COUNTER.labels(resource_type="events").inc()
            if token in limited_tokens_events:
                EVENTS_DROPPED_OVER_QUOTA_COUNTER.labels(resource_type="events", token=token).inc()
                if settings.QUOTA_LIMITING_ENABLED:
                    events_were_limited = True
                    continue

        results.append(event)

    return EventsOverQuotaResult(
        results,
        events_were_limited=events_were_limited,
        exceptions_were_limited=exceptions_were_limited,
        recordings_were_limited=recordings_were_limited,
    )


def lib_version_from_query_params(request) -> str:
    # url has a ver parameter from posthog-js
    return request.GET.get("ver", "unknown")


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

    # Explicit mark for get_event pipeline to handle CSP reports on this flow
    return get_event(request, csp_report=csp_report)


@csrf_exempt
@timed("posthog_cloud_event_endpoint")
def get_event(request, csp_report: dict[str, Any] | None = None):
    structlog.contextvars.unbind_contextvars("team_id")

    # handle cors request
    if request.method == "OPTIONS":
        return cors_response(request, JsonResponse({"status": 1}))

    now = timezone.now()

    error_response = None
    data: Any | None = None
    if csp_report:
        data = csp_report
    else:
        data, error_response = get_data(request)

    if error_response:
        return error_response

    sent_at, error_response = _get_sent_at(data, request)

    if error_response:
        return error_response

    retry_count = _get_retry_count(request)

    token = get_token(data, request)

    if not token:
        return cors_response(
            request,
            generate_exception_response(
                "capture",
                "API key not provided. You can find your project API key in PostHog project settings.",
                type="authentication_error",
                code="missing_api_key",
                status_code=status.HTTP_401_UNAUTHORIZED,
            ),
        )

    try:
        invalid_token_reason = _check_token_shape(token)
    except Exception as e:
        invalid_token_reason = "exception"
        logger.warning(
            "capture_token_shape_exception",
            token=token,
            reason="exception",
            exception=e,
        )

    if invalid_token_reason:
        TOKEN_SHAPE_INVALID_COUNTER.labels(reason=invalid_token_reason).inc()
        logger.warning("capture_token_shape_invalid", token=token, reason=invalid_token_reason)
        return cors_response(
            request,
            generate_exception_response(
                "capture",
                f"Provided API key is not valid: {invalid_token_reason}",
                type="authentication_error",
                code=invalid_token_reason,
                status_code=status.HTTP_401_UNAUTHORIZED,
            ),
        )

    structlog.contextvars.bind_contextvars(token=token)

    replay_events: list[Any] = []

    historical = token in settings.TOKENS_HISTORICAL_DATA
    if isinstance(data, dict):
        if data.get("batch"):  # posthog-python and posthog-ruby
            if not historical:
                # If they're not forced into historical by token, they can still opt into it
                # for batches via `historical_migration=true`
                historical = bool(data.get("historical_migration", False))
            data = data["batch"]
            assert data is not None

            KLUDGES_COUNTER.labels(kludge="data_is_batch_field").inc()
        elif "engage" in request.path_info:  # JS identify call
            data["event"] = "$identify"  # make sure it has an event name

    if isinstance(data, list):
        events = data
    else:
        events = [data]

    if not all(data):  # Check that all items are truthy (not null, not empty dict)
        return cors_response(
            request,
            generate_exception_response("capture", f"Invalid payload: some events are null", code="invalid_payload"),
        )

    try:
        events = drop_performance_events(events)
    except Exception as e:
        capture_exception(e)

    # we're not going to change the response for events
    recordings_were_quota_limited = False
    try:
        events_over_quota_result = drop_events_over_quota(token, events)
        events = events_over_quota_result.events
        recordings_were_quota_limited = events_over_quota_result.recordings_were_limited
    except Exception as e:
        # NOTE: Whilst we are testing this code we want to track exceptions but allow the events through if anything goes wrong
        capture_exception(e)

    try:
        # split the replay events off as they are passed to kafka separately
        replay_events, other_events = split_replay_events(events)
        events = other_events

    except ValueError as e:
        return cors_response(
            request,
            generate_exception_response("capture", f"Invalid payload: {e}", code="invalid_payload"),
        )

    # We don't use the site_url anymore, but for safe roll-outs keeping it here for now
    site_url = request.build_absolute_uri("/")[:-1]
    ip = get_ip_address(request)

    try:
        processed_events = list(preprocess_events(events))

    except ValueError as e:
        return cors_response(
            request,
            generate_exception_response("capture", f"Invalid payload: {e}", code="invalid_payload"),
        )

    futures: list[FutureRecordMetadata] = []

    with posthoganalytics.new_context():
        posthoganalytics.tag("event.count", len(processed_events))
        for event, event_uuid, distinct_id in processed_events:
            if f"{token}:{distinct_id}" in get_tokens_to_drop():
                logger.warning("Dropping event", token=token, distinct_id=distinct_id)
                continue

            try:
                futures.append(
                    capture_internal(
                        event,
                        distinct_id,
                        ip,
                        site_url,
                        now,
                        sent_at,
                        event_uuid,
                        token,
                        historical,
                    )
                )

            except Exception as exc:
                capture_exception(exc, {"data": data})
                statsd.incr("posthog_cloud_raw_endpoint_failure", tags={"endpoint": "capture"})
                logger.exception("kafka_produce_failure", exc_info=exc)

                return cors_response(
                    request,
                    generate_exception_response(
                        "capture",
                        "Unable to store event. Please try again. If you are the owner of this app you can check the logs for further details.",
                        code="server_error",
                        type="server_error",
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    ),
                )

    with posthoganalytics.new_context():
        posthoganalytics.tag("future.count", len(futures))
        start_time = time.monotonic()
        for future in futures:
            try:
                future.get(timeout=settings.KAFKA_PRODUCE_ACK_TIMEOUT_SECONDS - (time.monotonic() - start_time))
            except KafkaError as exc:
                # TODO: distinguish between retriable errors and non-retriable
                # errors, and set Retry-After header accordingly.
                # TODO: return 400 error for non-retriable errors that require the
                # client to change their request.

                logger.exception(
                    "kafka_produce_failure",
                    exc_info=exc,
                    name=exc.__class__.__name__,
                    # data could be large, so we don't always want to include it,
                    # but we do want to include it for some errors to aid debugging
                    data=data if isinstance(exc, MessageSizeTooLargeError) else None,
                )
                return cors_response(
                    request,
                    generate_exception_response(
                        "capture",
                        "Unable to store some events. Please try again. If you are the owner of this app you can check the logs for further details.",
                        code="server_error",
                        type="server_error",
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    ),
                )

    try:
        if replay_events:
            lib_version = lib_version_from_query_params(request)
            user_agent = request.headers.get("User-Agent", "")

            alternative_replay_events = preprocess_replay_events_for_blob_ingestion(
                replay_events, settings.SESSION_RECORDING_KAFKA_MAX_REQUEST_SIZE_BYTES, user_agent
            )

            replay_futures: list[tuple[FutureRecordMetadata, tuple, dict]] = []

            # We want to be super careful with our new ingestion flow for now so the whole thing is separated
            # This is mostly a copy of above except we only log, we don't error out
            if alternative_replay_events:
                processed_events = list(preprocess_events(alternative_replay_events))
                with REPLAY_MESSAGE_PRODUCTION_TIMER.time():
                    for event, event_uuid, distinct_id in processed_events:
                        capture_args = (
                            event,
                            distinct_id,
                            ip,
                            site_url,
                            now,
                            sent_at,
                            event_uuid,
                            token,
                        )
                        extra_headers: list[tuple[str, str]] = [
                            ("lib_version", lib_version),
                        ]
                        capture_kwargs: dict[str, Any] = {
                            "extra_headers": extra_headers,
                        }
                        resp = capture_internal(*capture_args, **capture_kwargs)
                        replay_futures.append((resp, capture_args, capture_kwargs))

                    start_time = time.monotonic()
                    for future, args, kwargs in replay_futures:
                        if future is not None:
                            try:
                                future.get(
                                    timeout=settings.KAFKA_PRODUCE_ACK_TIMEOUT_SECONDS - (time.monotonic() - start_time)
                                )
                            except MessageSizeTooLargeError as mstle:
                                REPLAY_MESSAGE_SIZE_TOO_LARGE_COUNTER.inc()
                                warning_event = replace_with_warning(args[0], token, mstle, lib_version)
                                if warning_event:
                                    warning_future = capture_internal(warning_event, *args[1:], **kwargs)
                                    warning_future.get(timeout=settings.KAFKA_PRODUCE_ACK_TIMEOUT_SECONDS)

    except ValueError as e:
        capture_exception(e, {"capture-pathway": "replay", "ph-team-token": token})
        # this means we're getting an event we can't process, we shouldn't swallow this
        # in production this is mostly seen as events with a missing distinct_id
        return cors_response(
            request,
            generate_exception_response("capture", f"Invalid recording payload", code="invalid_payload"),
        )
    except KafkaTimeoutError as kte:
        # posthog-js will retry when it receives a 504, and it sends `retry_count` in the query params,
        # so we use this to retry on 0, 1, and 2 and then return a 400 on the fourth attempt
        # this is to prevent a client from retrying indefinitely
        status_code = status.HTTP_400_BAD_REQUEST if (retry_count or 0) > 2 else status.HTTP_504_GATEWAY_TIMEOUT

        KAFKA_TIMEOUT_ERROR_COUNTER.labels(retry_count=retry_count, status_code=status_code).inc()

        if status_code == status.HTTP_400_BAD_REQUEST:
            capture_exception(
                kte,
                {
                    "capture-pathway": "replay",
                    "ph-team-token": token,
                    "retry_count": retry_count,
                },
            )

        return cors_response(
            request,
            generate_exception_response(
                "capture",
                "timed out writing to kafka",
                type="timeout_error",
                code="kafka_timeout",
                status_code=status_code,
            ),
        )
    except Exception as exc:
        capture_exception(
            exc,
            {"data": data, "capture-pathway": "replay", "ph-team-token": token},
        )
        logger.exception("kafka_session_recording_produce_failure", exc_info=exc)
        return cors_response(
            request,
            generate_exception_response(
                "capture",
                "Unable to store recording snapshot. Please try again. If you are the owner of this app you can check the logs for further details.",
                code="server_error",
                type="server_error",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            ),
        )

    statsd.incr("posthog_cloud_raw_endpoint_success", tags={"endpoint": "capture"})

    response_body: dict[str, int | list[str]] = {"status": 1}
    # if this has an unexpected effect we don't want it to have an unexpected effect on all clients at once,
    # so we check if a random number if less than the given sample rate
    # that means we can set SAMPLE_RATE to 0 to disable this and 1 to turn on for all clients
    if recordings_were_quota_limited and random() < settings.RECORDINGS_QUOTA_LIMITING_RESPONSES_SAMPLE_RATE:
        EVENTS_REJECTED_OVER_QUOTA_COUNTER.labels(resource_type="recordings").inc()
        response_body["quota_limited"] = ["recordings"]

    # If we have a csp_report parsed, we should return a 204 since that's the standard
    # https://github.com/PostHog/posthog/pull/32174
    if csp_report:
        return cors_response(request, HttpResponse(status=status.HTTP_204_NO_CONTENT))

    return cors_response(request, JsonResponse(response_body))


def replace_with_warning(
    event: dict[str, Any], token: str, mstle: MessageSizeTooLargeError, lib_version: str
) -> dict[str, Any] | None:
    """
    Replace the event with a warning message if the event is too large to be sent to Kafka.
    The event passed in should be safe to discard (because we know kafka won't accept it).
    We do this so that when we're playing back the recording we can insert useful info in the UI.
    """
    try:
        sample_replay_data_to_object_storage(event, random(), token, lib_version)

        posthog_size_calculation = byte_size_dict(event)

        properties = event.pop("properties", {})
        snapshot_items = properties.pop("$snapshot_items", [])
        # since we had message too large there really should be an item in the list
        # but just in case, since we would have dropped this anyway
        if not snapshot_items:
            return None

        first_item = snapshot_items[0]
        if not isinstance(first_item, dict) or ("$window_id" not in first_item and "timestamp" not in first_item):
            return None

        only_meta_events = [x for x in snapshot_items if isinstance(x, dict) and ("type" in x and x["type"] == 4)]

        kafka_size: int | None = None
        size_difference: int | Literal["unknown"] = "unknown"
        try:
            kafka_size = int(mstle.args[0].split(" ")[3])
            size_difference = kafka_size - posthog_size_calculation
        except:
            pass

        logger.info(
            "REPLAY_MESSAGE_TOO_LARGE",
            session_id=properties.get("$session_id"),
            kafka_size=kafka_size,
            posthog_calculation=posthog_size_calculation,
            lib_version=lib_version,
        )

        return {
            **event,
            "properties": {
                **properties,
                "$snapshot_bytes": 0,
                "$snapshot_items": [
                    *only_meta_events,
                    {
                        "type": 5,
                        "data": {
                            "tag": "Message too large",
                            "payload": {
                                "error_message": mstle.message,
                                "error": str(mstle),
                                "kafka_size": kafka_size,
                                "posthog_calculation": posthog_size_calculation,
                                "lib_version": lib_version,
                                "size_difference": size_difference,
                            },
                        },
                        "$window_id": first_item.get("$window_id"),
                        "timestamp": first_item.get("timestamp"),
                    },
                ],
            },
        }
    except Exception as ex:
        capture_exception(ex, {"capture-pathway": "replay"})
        return None


def sample_replay_data_to_object_storage(
    event: dict[str, Any], random_number: float, token: str, lib_version: str
) -> None:
    """
    the random number is passed in to make testing easier
    both the random number and the sample rate must be between 0 and 0.01
    if the random number is less than the sample_rate then we write the event to S3
    """
    try:
        # capture more of posthog message too large since we know we're using latest versions
        max_sample_rate = 0.6 if token == "sTMFPsFhdP1Ssg" else 0.01
        sample_rate = 0.5 if token == "sTMFPsFhdP1Ssg" else settings.REPLAY_MESSAGE_TOO_LARGE_SAMPLE_RATE

        if 0 < random_number < sample_rate <= max_sample_rate:
            if "properties" in event:
                event["properties"]["$lib_version"] = lib_version

            object_key = f"token-{token}-session_id-{event.get('properties', {}).get('$session_id', 'unknown')}.json"
            object_storage.write(object_key, json.dumps(event), bucket=settings.REPLAY_MESSAGE_TOO_LARGE_SAMPLE_BUCKET)
    except Exception as ex:
        capture_exception(ex, {"capture-pathway": "replay", "ph-team-token": token})


def preprocess_events(events: list[dict[str, Any]]) -> Iterator[tuple[dict[str, Any], UUIDT, str]]:
    for event in events:
        event_uuid = UUIDT()
        distinct_id = get_distinct_id(event)
        payload_uuid = event.get("uuid", None)
        if payload_uuid:
            if UUIDT.is_valid_uuid(payload_uuid):
                event_uuid = UUIDT(uuid_str=payload_uuid)
            else:
                statsd.incr("invalid_event_uuid")
                raise ValueError('Event field "uuid" is not a valid UUID!')

        event = parse_event(event)
        if not event:
            continue

        yield event, event_uuid, distinct_id


def parse_event(event):
    if not event.get("event"):
        statsd.incr("invalid_event", tags={"error": "missing_event_name"})
        return

    if not event.get("properties"):
        event["properties"] = {}

    enforce_numeric_offset(event["properties"])

    with posthoganalytics.new_context():
        posthoganalytics.tag("library", event["properties"].get("$lib", "unknown"))
        posthoganalytics.tag("library.version", event["properties"].get("$lib_version", "unknown"))

    return event


class CaptureInternalError(Exception):
    pass


# TODO: replace raw_event input with structured inputs after transition off old capture_internal
def new_capture_internal(
    token: Optional[str], distinct_id: Optional[str], raw_event: dict[str, Any], process_person_profile: bool = False
) -> Response:
    """
    new_capture_internal submits a single-event capture request payload to
    PostHog (capture-rs backend) rather than pushing directly to Kafka and
    bypassing downstream checks
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
) -> list[Future[Response]]:
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

    futures: list[Future[Response]] = []

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


def capture_internal(
    event,
    distinct_id,
    ip,
    site_url,
    now,
    sent_at,
    event_uuid=None,
    token=None,
    historical=False,
    extra_headers: list[tuple[str, str]] | None = None,
):
    if event_uuid is None:
        event_uuid = UUIDT()

    if extra_headers is None:
        extra_headers = []

    headers = [("token", token), ("distinct_id", distinct_id), *extra_headers]

    parsed_event = build_kafka_event_data(
        distinct_id=distinct_id,
        ip=ip,
        site_url=site_url,
        data=event,
        now=now,
        sent_at=sent_at,
        event_uuid=event_uuid,
        token=token,
    )

    if event["event"] in SESSION_RECORDING_EVENT_NAMES:
        session_id = event["properties"]["$session_id"]

        overflowing = False
        if token in settings.REPLAY_OVERFLOW_FORCED_TOKENS:
            overflowing = True
        elif settings.REPLAY_OVERFLOW_SESSIONS_ENABLED:
            overflowing = session_id in _list_overflowing_keys(InputType.REPLAY)

        return log_event(
            parsed_event,
            event["event"],
            partition_key=session_id,
            headers=headers,
            overflowing=overflowing,
        )

    # We aim to always partition by {team_id}:{distinct_id} but allow
    # overriding this to deal with hot partitions in specific cases.
    # Setting the partition key to None means using random partitioning.
    candidate_partition_key = f"{token}:{distinct_id}"
    if event.get("properties", {}).get(COOKIELESS_MODE_FLAG_PROPERTY):
        # In cookieless mode, the distinct id is meaningless, so we can't use it as the partition key.
        # Instead, use the IP address as the partition key.
        candidate_partition_key = f"{token}:{ip}"

    if (
        not historical
        and settings.CAPTURE_ALLOW_RANDOM_PARTITIONING
        and (distinct_id.lower() in LIKELY_ANONYMOUS_IDS or is_randomly_partitioned(candidate_partition_key))
    ):
        kafka_partition_key = None
    else:
        kafka_partition_key = candidate_partition_key

    return log_event(
        parsed_event, event["event"], partition_key=kafka_partition_key, historical=historical, headers=headers
    )


def is_randomly_partitioned(candidate_partition_key: str) -> bool:
    """Check whether event with given partition key is to be randomly partitioned.

    Checking whether an event should be randomly partitioned is a two step process:

    1. Using a token-bucket algorithm, check if the event's candidate key has exceeded
       the given PARTITION_KEY_BUCKET_CAPACITY. If it has, events with that key could
       be experiencing a temporary burst in traffic and should be randomly partitioned.
       Otherwise, go to 2.

    2. Check if the candidate partition key is set in the
       EVENT_PARTITION_KEYS_TO_OVERRIDE instance setting. If it is, then the event
       should be randomly partitioned. Otherwise, no random partition should occur and
       the candidate partition key can be used.

    Token-bucket algorithm (step 1) is ignored if the
    PARTITION_KEY_AUTOMATIC_OVERRIDE_ENABLED setting is set to False.

    Args:
        candidate_partition_key: The partition key that would be used if we decide
            on no random partitioniong. This is in the format `team_id:distinct_id`.

    Returns:
        Whether the given partition key should be used.
    """
    if settings.PARTITION_KEY_AUTOMATIC_OVERRIDE_ENABLED:
        has_capacity = LIMITER.consume(candidate_partition_key)

        if not has_capacity:
            if not LOG_RATE_LIMITER.consume(candidate_partition_key):
                # Return early if we have logged this key already.
                return True

            PARTITION_KEY_CAPACITY_EXCEEDED_COUNTER.labels(partition_key=candidate_partition_key.split(":")[0]).inc()
            statsd.incr(
                "partition_key_capacity_exceeded",
                tags={"partition_key": candidate_partition_key},
            )
            logger.warning(
                "Partition key %s overridden as bucket capacity of %s tokens exceeded",
                candidate_partition_key,
                LIMITER._capacity,
            )
            return True

    keys_to_override = settings.EVENT_PARTITION_KEYS_TO_OVERRIDE

    return candidate_partition_key in keys_to_override


@cache_for(timedelta(seconds=30), background_refresh=True)
def _list_overflowing_keys(input_type: InputType) -> set[str]:
    """Retrieve the active overflows from Redis with caching and pre-fetching

    cache_for will keep the old value if Redis is temporarily unavailable.
    In case of a prolonged Redis outage, new pods would fail to retrieve anything and fail
    to ingest, but Django is currently unable to start if the common Redis is unhealthy.
    Setting REPLAY_OVERFLOW_SESSIONS_ENABLED back to false neutralizes this code path.
    """
    now = timezone.now()
    redis_client = get_client()
    results = redis_client.zrangebyscore(f"{OVERFLOWING_REDIS_KEY}{input_type.value}", min=now.timestamp(), max="+inf")
    OVERFLOWING_KEYS_LOADED_GAUGE.labels(input_type.value).set(len(results))
    return {x.decode("utf-8") for x in results}
