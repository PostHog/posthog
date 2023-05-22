import base64
import hashlib
import json
import re
import time
from datetime import datetime
from random import random
from typing import Any, Dict, Iterator, List, Optional, Tuple

import structlog
from dateutil import parser
from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from kafka.errors import KafkaError, MessageSizeTooLargeError
from kafka.producer.future import FutureRecordMetadata
from prometheus_client import Counter
from rest_framework import status
from sentry_sdk import configure_scope
from sentry_sdk.api import capture_exception, start_span
from statshog.defaults.django import statsd
from token_bucket import Limiter, MemoryStorage

from posthog.api.utils import get_data, get_token, safe_clickhouse_string
from posthog.exceptions import generate_exception_response
from posthog.kafka_client.client import (
    KafkaProducer,
    sessionRecordingKafkaProducer,
)
from posthog.kafka_client.topics import (
    KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL,
    KAFKA_SESSION_RECORDING_EVENTS,
    KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS,
)
from posthog.logging.timing import timed
from posthog.metrics import LABEL_RESOURCE_TYPE
from posthog.models.utils import UUIDT
from posthog.session_recordings.session_recording_helpers import (
    legacy_preprocess_session_recording_events_for_clickhouse,
    preprocess_replay_events_for_blob_ingestion,
    split_replay_events,
)
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
SESSION_RECORDING_EVENT_NAMES = ("$snapshot", "$performance_event") + SESSION_RECORDING_DEDICATED_KAFKA_EVENTS

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


def build_kafka_event_data(
    distinct_id: str,
    ip: Optional[str],
    site_url: str,
    data: Dict,
    now: datetime,
    sent_at: Optional[datetime],
    event_uuid: UUIDT,
    token: str,
) -> Dict:
    logger.debug("build_kafka_event_data", token=token)
    return {
        "uuid": str(event_uuid),
        "distinct_id": safe_clickhouse_string(distinct_id),
        "ip": safe_clickhouse_string(ip) if ip else ip,
        "site_url": safe_clickhouse_string(site_url),
        "data": json.dumps(data),
        "now": now.isoformat(),
        "sent_at": sent_at.isoformat() if sent_at else "",
        "token": token,
    }


def _kafka_topic(event_name: str, data: Dict) -> str:
    # To allow for different quality of service on session recordings
    # and other events, we push to a different topic.

    match event_name:
        case "$snapshot":
            return KAFKA_SESSION_RECORDING_EVENTS
        case "$snapshot_items":
            return KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS
        case _:
            # If the token is in the TOKENS_HISTORICAL_DATA list, we push to the
            # historical data topic.
            if data.get("token") in settings.TOKENS_HISTORICAL_DATA:
                return KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL
            return settings.KAFKA_EVENTS_PLUGIN_INGESTION_TOPIC


def log_event(data: Dict, event_name: str, partition_key: Optional[str]):
    kafka_topic = _kafka_topic(event_name, data)

    logger.debug("logging_event", event_name=event_name, kafka_topic=kafka_topic)

    # TODO: Handle Kafka being unavailable with exponential backoff retries
    try:
        if event_name in SESSION_RECORDING_DEDICATED_KAFKA_EVENTS:
            producer = sessionRecordingKafkaProducer()
        else:
            producer = KafkaProducer()

        future = producer.produce(topic=kafka_topic, data=data, key=partition_key)
        statsd.incr("posthog_cloud_plugin_server_ingestion")
        return future
    except Exception as e:
        statsd.incr("capture_endpoint_log_event_error")
        logger.exception("Failed to produce event to Kafka topic %s with error", kafka_topic)
        raise e


def _datetime_from_seconds_or_millis(timestamp: str) -> datetime:
    if len(timestamp) > 11:  # assuming milliseconds / update "11" to "12" if year > 5138 (set a reminder!)
        timestamp_number = float(timestamp) / 1000
    else:
        timestamp_number = int(timestamp)

    return datetime.fromtimestamp(timestamp_number, timezone.utc)


def _get_sent_at(data, request) -> Tuple[Optional[datetime], Any]:
    try:
        if request.GET.get("_"):  # posthog-js
            sent_at = request.GET["_"]
        elif isinstance(data, dict) and data.get("sent_at"):  # posthog-android, posthog-ios
            sent_at = data["sent_at"]
        elif request.POST.get("sent_at"):  # when urlencoded body and not JSON (in some test)
            sent_at = request.POST["sent_at"]
        else:
            return None, None

        if re.match(r"^\d+(?:\.\d+)?$", sent_at):
            return _datetime_from_seconds_or_millis(sent_at), None

        return parser.isoparse(sent_at), None
    except Exception as error:
        statsd.incr("capture_endpoint_invalid_sent_at")
        logger.exception(f"Invalid sent_at value", error=error)
        return (
            None,
            cors_response(
                request,
                generate_exception_response(
                    "capture", f"Malformed request data, invalid sent at: {error}", code="invalid_payload"
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


def get_distinct_id(data: Dict[str, Any]) -> str:
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


def drop_performance_events(events: List[Any]) -> List[Any]:
    cleaned_list = [event for event in events if event.get("event") != "$performance_event"]
    return cleaned_list


def drop_events_over_quota(token: str, events: List[Any]) -> List[Any]:
    if not settings.EE_AVAILABLE:
        return events

    from ee.billing.quota_limiting import QuotaResource, list_limited_team_tokens

    results = []
    limited_tokens_events = list_limited_team_tokens(QuotaResource.EVENTS)
    limited_tokens_recordings = list_limited_team_tokens(QuotaResource.RECORDINGS)

    for event in events:
        if event.get("event") in SESSION_RECORDING_EVENT_NAMES:
            EVENTS_RECEIVED_COUNTER.labels(resource_type="recordings").inc()
            if token in limited_tokens_recordings:
                EVENTS_DROPPED_OVER_QUOTA_COUNTER.labels(resource_type="recordings", token=token).inc()
                if settings.QUOTA_LIMITING_ENABLED:
                    continue

        else:
            EVENTS_RECEIVED_COUNTER.labels(resource_type="events").inc()
            if token in limited_tokens_events:
                EVENTS_DROPPED_OVER_QUOTA_COUNTER.labels(resource_type="events", token=token).inc()
                if settings.QUOTA_LIMITING_ENABLED:
                    continue

        results.append(event)

    return results


@csrf_exempt
@timed("posthog_cloud_event_endpoint")
def get_event(request):
    structlog.contextvars.unbind_contextvars("team_id")

    # handle cors request
    if request.method == "OPTIONS":
        return cors_response(request, JsonResponse({"status": 1}))

    now = timezone.now()

    # Optionally dump requests and Kafka messages to collect test cases
    if settings.DUMP_CAPTURE_TO_FILE:
        request_dump = {
            "path": request.get_full_path(),
            "method": request.method,
            "content-encoding": request.META.get("content-encoding", ""),
            "ip": request.META.get("HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR")),
            "now": now.isoformat(),
            "body": base64.b64encode(request.body).decode(encoding="ascii"),
            "output": [],
        }
    else:
        request_dump = None

    data, error_response = get_data(request)

    if error_response:
        return error_response

    sent_at, error_response = _get_sent_at(data, request)

    if error_response:
        return error_response

    with start_span(op="request.authenticate"):
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
            logger.warning("capture_token_shape_exception", token=token, reason="exception", exception=e)

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

    replay_events: List[Any] = []

    with start_span(op="request.process"):
        if isinstance(data, dict):
            if data.get("batch"):  # posthog-python and posthog-ruby
                data = data["batch"]
                assert data is not None
            elif "engage" in request.path_info:  # JS identify call
                data["event"] = "$identify"  # make sure it has an event name

        if isinstance(data, list):
            events = data
        else:
            events = [data]

        try:
            events = drop_performance_events(events)
        except Exception as e:
            capture_exception(e)

        try:
            events = drop_events_over_quota(token, events)
        except Exception as e:
            # NOTE: Whilst we are testing this code we want to track exceptions but allow the events through if anything goes wrong
            capture_exception(e)

        consumer_destination = "v2" if random() <= settings.REPLAY_EVENTS_NEW_CONSUMER_RATIO else "v1"

        try:
            replay_events, other_events = split_replay_events(events)
            processed_replay_events = replay_events

            if len(replay_events) > 0:
                # Legacy solution stays in place
                processed_replay_events = legacy_preprocess_session_recording_events_for_clickhouse(replay_events)

                # Mark all events so that they are only consumed by one consumer
                for event in processed_replay_events:
                    event["properties"]["$snapshot_consumer"] = consumer_destination

            events = processed_replay_events + other_events

        except ValueError as e:
            return cors_response(
                request, generate_exception_response("capture", f"Invalid payload: {e}", code="invalid_payload")
            )

        # We don't use the site_url anymore, but for safe roll-outs keeping it here for now
        site_url = request.build_absolute_uri("/")[:-1]
        ip = get_ip_address(request)

        try:
            processed_events = list(preprocess_events(events))
        except ValueError as e:
            return cors_response(
                request, generate_exception_response("capture", f"Invalid payload: {e}", code="invalid_payload")
            )

    futures: List[FutureRecordMetadata] = []
    with start_span(op="kafka.produce") as span:
        span.set_tag("event.count", len(processed_events))
        for event, event_uuid, distinct_id in processed_events:
            try:
                futures.append(
                    capture_internal(event, distinct_id, ip, site_url, now, sent_at, event_uuid, token, request_dump)
                )
            except Exception as exc:
                capture_exception(exc, {"data": data})
                statsd.incr("posthog_cloud_raw_endpoint_failure", tags={"endpoint": "capture"})
                logger.error("kafka_produce_failure", exc_info=exc)
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

    if settings.DUMP_CAPTURE_TO_FILE:
        try:
            with open(settings.DUMP_CAPTURE_TO_FILE, "a") as dump_file:
                json.dump(request_dump, dump_file, separators=(",", ":"))
                dump_file.write("\n")
        except Exception as exc:
            logger.error("dump_capture_failure", exc_info=exc)

    with start_span(op="kafka.wait"):
        span.set_tag("future.count", len(futures))
        start_time = time.monotonic()
        for future in futures:
            try:
                future.get(timeout=settings.KAFKA_PRODUCE_ACK_TIMEOUT_SECONDS - (time.monotonic() - start_time))
            except KafkaError as exc:
                # TODO: distinguish between retriable errors and non-retriable
                # errors, and set Retry-After header accordingly.
                # TODO: return 400 error for non-retriable errors that require the
                # client to change their request.

                logger.error(
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
            # The new flow we only enable if the dedicated kafka is enabled
            alternative_replay_events = preprocess_replay_events_for_blob_ingestion(
                replay_events, settings.SESSION_RECORDING_KAFKA_MAX_REQUEST_SIZE_BYTES
            )

            # Mark all events so that they are only consumed by one consumer
            for event in alternative_replay_events:
                event["properties"]["$snapshot_consumer"] = consumer_destination

            futures = []

            # We want to be super careful with our new ingestion flow for now so the whole thing is separated
            # This is mostly a copy of above except we only log, we don't error out
            if alternative_replay_events:
                processed_events = list(preprocess_events(alternative_replay_events))
                for event, event_uuid, distinct_id in processed_events:
                    futures.append(capture_internal(event, distinct_id, ip, site_url, now, sent_at, event_uuid, token))

                start_time = time.monotonic()
                for future in futures:
                    future.get(timeout=settings.KAFKA_PRODUCE_ACK_TIMEOUT_SECONDS - (time.monotonic() - start_time))

    except Exception as exc:
        capture_exception(exc, {"data": data})
        logger.error("kafka_session_recording_produce_failure", exc_info=exc)
        pass

    statsd.incr("posthog_cloud_raw_endpoint_success", tags={"endpoint": "capture"})
    return cors_response(request, JsonResponse({"status": 1}))


def preprocess_events(events: List[Dict[str, Any]]) -> Iterator[Tuple[Dict[str, Any], UUIDT, str]]:
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

    with configure_scope() as scope:
        scope.set_tag("library", event["properties"].get("$lib", "unknown"))
        scope.set_tag("library.version", event["properties"].get("$lib_version", "unknown"))

    return event


def capture_internal(
    event, distinct_id, ip, site_url, now, sent_at, event_uuid=None, token=None, request_dump: Optional[Dict] = None
):
    if event_uuid is None:
        event_uuid = UUIDT()

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

    if request_dump:
        request_dump["output"].append(parsed_event)

    # We aim to always partition by {team_id}:{distinct_id} but allow
    # overriding this to deal with hot partitions in specific cases.
    # Setting the partition key to None means using random partitioning.
    kafka_partition_key = None

    if event["event"] in SESSION_RECORDING_EVENT_NAMES:
        kafka_partition_key = event["properties"]["$session_id"]
        return log_event(parsed_event, event["event"], partition_key=kafka_partition_key)

    candidate_partition_key = f"{token}:{distinct_id}"

    if (
        distinct_id.lower() not in LIKELY_ANONYMOUS_IDS
        and is_randomly_partitioned(candidate_partition_key) is False
        or token in settings.TOKENS_HISTORICAL_DATA
    ):
        kafka_partition_key = hashlib.sha256(candidate_partition_key.encode()).hexdigest()

    return log_event(parsed_event, event["event"], partition_key=kafka_partition_key)


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

        if has_capacity is False:
            if not LOG_RATE_LIMITER.consume(candidate_partition_key):
                # Return early if we have logged this key already.
                return True

            PARTITION_KEY_CAPACITY_EXCEEDED_COUNTER.labels(partition_key=candidate_partition_key.split(":")[0]).inc()
            statsd.incr("partition_key_capacity_exceeded", tags={"partition_key": candidate_partition_key})
            logger.warning(
                "Partition key %s overridden as bucket capacity of %s tokens exceeded",
                candidate_partition_key,
                LIMITER._capacity,
            )
            return True

    keys_to_override = settings.EVENT_PARTITION_KEYS_TO_OVERRIDE

    return candidate_partition_key in keys_to_override
