import hashlib
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import structlog
from dateutil import parser
from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from sentry_sdk import configure_scope
from sentry_sdk.api import capture_exception
from statshog.defaults.django import statsd

from posthog.api.utils import (
    EventIngestionContext,
    get_data,
    get_event_ingestion_context,
    get_token,
    safe_clickhouse_string,
)
from posthog.exceptions import generate_exception_response
from posthog.helpers.session_recording import (
    ChunkedRecordingEvent,
    get_session_recording_events_for_object_storage,
    preprocess_session_recording_events_for_clickhouse,
)
from posthog.kafka_client.client import KafkaProducer
from posthog.kafka_client.topics import KAFKA_DEAD_LETTER_QUEUE
from posthog.logging.timing import timed
from posthog.models.feature_flag import get_active_feature_flags
from posthog.models.utils import UUIDT
from posthog.settings import (
    KAFKA_EVENTS_PLUGIN_INGESTION_TOPIC,
    KAFKA_RECORDING_EVENTS_TO_OBJECT_STORAGE_INGESTION_TOPIC,
)
from posthog.utils import cors_response, get_ip_address, should_write_recordings_to_object_storage

logger = structlog.get_logger(__name__)


def parse_kafka_event_data(
    distinct_id: str,
    ip: Optional[str],
    site_url: str,
    data: Dict,
    team_id: Optional[int],
    now: datetime,
    sent_at: Optional[datetime],
    event_uuid: UUIDT,
) -> Dict:
    return {
        "uuid": str(event_uuid),
        "distinct_id": safe_clickhouse_string(distinct_id),
        "ip": safe_clickhouse_string(ip) if ip else ip,
        "site_url": safe_clickhouse_string(site_url),
        "data": json.dumps(data),
        "team_id": team_id,
        "now": now.isoformat(),
        "sent_at": sent_at.isoformat() if sent_at else "",
    }


def parse_kafka_recording_for_object_storage_event_data(
    team_id: int, recording_event: ChunkedRecordingEvent,
) -> Tuple[List[Tuple[str, str]], str]:
    headers = [
        ("unixTimestamp", str(recording_event.unix_timestamp)),
        ("eventId", recording_event.recording_event_id),
        ("sessionId", recording_event.session_id),
        ("distinctId", recording_event.distinct_id),
        ("chunkCount", str(recording_event.chunk_count)),
        ("chunkIndex", str(recording_event.chunk_index)),
        ("eventSource", str(recording_event.recording_event_source) if recording_event.recording_event_source else "",),
        ("eventType", str(recording_event.recording_event_type) if recording_event.recording_event_type else ""),
        ("windowId", recording_event.window_id if recording_event.window_id else ""),
        ("teamId", str(team_id)),
    ]
    return (headers, recording_event.recording_event_data_chunk)


def log_event(data: Dict, event_name: str, partition_key: str) -> None:
    if settings.DEBUG:
        print(f"Logging event {event_name} to Kafka topic {KAFKA_EVENTS_PLUGIN_INGESTION_TOPIC}")

    # TODO: Handle Kafka being unavailable with exponential backoff retries
    try:
        KafkaProducer().produce(topic=KAFKA_EVENTS_PLUGIN_INGESTION_TOPIC, data=data, key=partition_key)
        statsd.incr("posthog_cloud_plugin_server_ingestion")
    except Exception as e:
        statsd.incr("capture_endpoint_log_event_error")
        print(f"Failed to produce event to Kafka topic {KAFKA_EVENTS_PLUGIN_INGESTION_TOPIC} with error:", e)
        raise e


def log_session_recording_event(headers: List[Tuple[str, str]], data: str, partition_key: str) -> None:
    if settings.DEBUG:
        print(f"Logging recording event to Kafka topic {KAFKA_RECORDING_EVENTS_TO_OBJECT_STORAGE_INGESTION_TOPIC}")
    try:
        KafkaProducer().produce(
            topic=KAFKA_RECORDING_EVENTS_TO_OBJECT_STORAGE_INGESTION_TOPIC,
            headers=headers,
            data=data,
            key=partition_key,
            value_serializer=lambda v: v.encode("utf-8"),
        )
        statsd.incr("recording_event_to_object_storage_ingestion")
    except Exception as e:
        statsd.incr("capture_endpoint_log_recording_event_error")
        print(
            f"Failed to produce recording event to Kafka topic {KAFKA_RECORDING_EVENTS_TO_OBJECT_STORAGE_INGESTION_TOPIC} with error:",
            e,
        )
        raise e


def log_event_to_dead_letter_queue(
    raw_payload: Dict,
    event_name: str,
    event: Dict,
    error_message: str,
    error_location: str,
    topic: str = KAFKA_DEAD_LETTER_QUEUE,
):
    data = event.copy()

    data["error_timestamp"] = datetime.now().isoformat()
    data["error_location"] = safe_clickhouse_string(error_location)
    data["error"] = safe_clickhouse_string(error_message)
    data["elements_chain"] = ""
    data["id"] = str(UUIDT())
    data["event"] = safe_clickhouse_string(event_name)
    data["raw_payload"] = json.dumps(raw_payload)
    data["now"] = datetime.fromisoformat(data["now"]).replace(tzinfo=None).isoformat() if data["now"] else None
    data["tags"] = ["django_server"]
    data["event_uuid"] = event["uuid"]
    del data["uuid"]

    try:
        KafkaProducer().produce(topic=topic, data=data)
        statsd.incr(settings.EVENTS_DEAD_LETTER_QUEUE_STATSD_METRIC)
    except Exception as e:
        capture_exception(e)
        statsd.incr("events_dead_letter_queue_produce_error")

        if settings.DEBUG:
            print("Failed to produce to events dead letter queue with error:", e)


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
    if not raw_value:
        statsd.incr("invalid_event", tags={"error": "invalid_distinct_id"})
        raise ValueError('Event field "distinct_id" should not be blank!')
    return str(raw_value)[0:200]


def _ensure_web_feature_flags_in_properties(
    event: Dict[str, Any], ingestion_context: EventIngestionContext, distinct_id: str
):
    """If the event comes from web, ensure that it contains property $active_feature_flags."""
    if event["properties"].get("$lib") == "web" and "$active_feature_flags" not in event["properties"]:
        flags = get_active_feature_flags(team_id=ingestion_context.team_id, distinct_id=distinct_id)
        event["properties"]["$active_feature_flags"] = list(flags.keys())
        for k, v in flags.items():
            event["properties"][f"$feature/{k}"] = v


@csrf_exempt
@timed("posthog_cloud_event_endpoint")
def get_event(request):
    # handle cors request
    if request.method == "OPTIONS":
        return cors_response(request, JsonResponse({"status": 1}))

    now = timezone.now()

    data, error_response = get_data(request)

    if error_response:
        return error_response

    sent_at, error_response = _get_sent_at(data, request)

    if error_response:
        return error_response

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

    ingestion_context, db_error, error_response = get_event_ingestion_context(request, data, token)

    if error_response:
        return error_response

    send_events_to_dead_letter_queue = False
    if db_error:
        send_events_to_dead_letter_queue = True

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
        if ingestion_context and should_write_recordings_to_object_storage(ingestion_context.team_id):
            session_recording_events = get_session_recording_events_for_object_storage(events)
            for recording_event in session_recording_events:
                headers, data = parse_kafka_recording_for_object_storage_event_data(
                    ingestion_context.team_id, recording_event,
                )
                log_session_recording_event(
                    headers,
                    data,
                    partition_key=hashlib.sha256(
                        f"{ingestion_context.team_id}:{recording_event.session_id}".encode()
                    ).hexdigest(),
                )
        events = preprocess_session_recording_events_for_clickhouse(events)
    except ValueError as e:
        return cors_response(
            request, generate_exception_response("capture", f"Invalid payload: {e}", code="invalid_payload")
        )

    site_url = request.build_absolute_uri("/")[:-1]

    ip = None if not ingestion_context or ingestion_context.anonymize_ips else get_ip_address(request)

    try:
        processed_events = list(validate_events(events, ingestion_context))
    except ValueError as e:
        return cors_response(
            request, generate_exception_response("capture", f"Invalid payload: {e}", code="invalid_payload")
        )

    for event, event_uuid, distinct_id in processed_events:
        if send_events_to_dead_letter_queue:
            kafka_event = parse_kafka_event_data(
                distinct_id=distinct_id,
                ip=None,
                site_url=site_url,
                team_id=None,
                now=now,
                event_uuid=event_uuid,
                data=event,
                sent_at=sent_at,
            )

            log_event_to_dead_letter_queue(
                data,
                event["event"],
                kafka_event,
                f"Unable to fetch team from Postgres. Error: {db_error}",
                "django_server_capture_endpoint",
            )
            continue

        try:
            capture_internal(event, distinct_id, ip, site_url, now, sent_at, ingestion_context.team_id, event_uuid)  # type: ignore
        except Exception as e:
            capture_exception(e, {"data": data})
            statsd.incr(
                "posthog_cloud_raw_endpoint_failure", tags={"endpoint": "capture",},
            )
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

    statsd.incr(
        "posthog_cloud_raw_endpoint_success", tags={"endpoint": "capture",},
    )
    return cors_response(request, JsonResponse({"status": 1}))


def validate_events(events, ingestion_context):
    for event in events:
        event_uuid = UUIDT()
        distinct_id = get_distinct_id(event)
        payload_uuid = event.get("uuid", None)
        if payload_uuid:
            del event["uuid"]
            if UUIDT.is_valid_uuid(payload_uuid):
                event_uuid = UUIDT(uuid_str=payload_uuid)
            else:
                statsd.incr("invalid_event_uuid")

        event = parse_event(event, distinct_id, ingestion_context)
        if not event:
            continue

        yield event, event_uuid, distinct_id


def parse_event(event, distinct_id, ingestion_context):
    if not event.get("event"):
        statsd.incr("invalid_event", tags={"error": "missing_event_name"})
        return

    if not event.get("properties"):
        event["properties"] = {}

    with configure_scope() as scope:
        scope.set_tag("library", event["properties"].get("$lib", "unknown"))
        scope.set_tag("library.version", event["properties"].get("$lib_version", "unknown"))

    if ingestion_context:
        _ensure_web_feature_flags_in_properties(event, ingestion_context, distinct_id)

    return event


def capture_internal(event, distinct_id, ip, site_url, now, sent_at, team_id, event_uuid=UUIDT()) -> None:
    parsed_event = parse_kafka_event_data(
        distinct_id=distinct_id,
        ip=ip,
        site_url=site_url,
        data=event,
        team_id=team_id,
        now=now,
        sent_at=sent_at,
        event_uuid=event_uuid,
    )
    partition_key = hashlib.sha256(f"{team_id}:{distinct_id}".encode()).hexdigest()
    log_event(parsed_event, event["event"], partition_key=partition_key)
