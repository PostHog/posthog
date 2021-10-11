import json
import re
from datetime import datetime, tzinfo
from typing import Any, Dict, Optional

from dateutil import parser
from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from sentry_sdk import capture_exception, configure_scope, push_scope
from sentry_sdk.api import capture_exception
from statshog.defaults.django import statsd

from posthog.api.utils import get_data, get_team, get_token
from posthog.celery import app as celery_app
from posthog.exceptions import RequestParsingError, generate_exception_response
from posthog.helpers.session_recording import preprocess_session_recording_events
from posthog.models import Team
from posthog.models.feature_flag import get_active_feature_flags
from posthog.models.utils import UUIDT
from posthog.settings import EVENTS_DEAD_LETTER_QUEUE_STATSD_METRIC
from posthog.utils import cors_response, get_ip_address, is_clickhouse_enabled

if is_clickhouse_enabled():
    from ee.kafka_client.client import KafkaProducer
    from ee.kafka_client.topics import KAFKA_DEAD_LETTER_QUEUE, KAFKA_EVENTS_PLUGIN_INGESTION

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
            "distinct_id": distinct_id,
            "ip": ip,
            "site_url": site_url,
            "data": json.dumps(data),
            "team_id": team_id,
            "now": now.isoformat(),
            "sent_at": sent_at.isoformat() if sent_at else "",
        }

    def log_event(data: Dict, event_name: str, topic: str = KAFKA_EVENTS_PLUGIN_INGESTION,) -> None:
        if settings.DEBUG:
            print(f"Logging event {event_name} to Kafka topic {topic}")
        KafkaProducer().produce(topic=topic, data=data)

    def log_event_to_dead_letter_queue(
        raw_payload: Dict,
        event_name: str,
        event: Dict,
        error_message: str,
        error_location: str,
        topic: str = KAFKA_DEAD_LETTER_QUEUE,
    ):
        data = event.copy()

        data["failure_timestamp"] = datetime.now().isoformat()
        data["error_location"] = error_location
        data["error"] = error_message
        data["elements_chain"] = ""
        data["id"] = str(UUIDT())
        data["event"] = event_name
        data["raw_payload"] = json.dumps(raw_payload)
        data["now"] = datetime.fromisoformat(data["now"]).replace(tzinfo=None).isoformat() if data["now"] else None

        data["event_uuid"] = event["uuid"]
        del data["uuid"]

        try:
            KafkaProducer().produce(topic=topic, data=data)
            statsd.incr(EVENTS_DEAD_LETTER_QUEUE_STATSD_METRIC)
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


def _get_sent_at(data, request) -> Optional[datetime]:
    if request.GET.get("_"):  # posthog-js
        sent_at = request.GET["_"]
    elif isinstance(data, dict) and data.get("sent_at"):  # posthog-android, posthog-ios
        sent_at = data["sent_at"]
    elif request.POST.get("sent_at"):  # when urlencoded body and not JSON (in some test)
        sent_at = request.POST["sent_at"]
    else:
        return None

    if re.match(r"^[0-9]+$", sent_at):
        return _datetime_from_seconds_or_millis(sent_at)

    return parser.isoparse(sent_at)


def _get_distinct_id(data: Dict[str, Any]) -> str:
    raw_value: Any = ""
    try:
        raw_value = data["$distinct_id"]
    except KeyError:
        try:
            raw_value = data["properties"]["distinct_id"]
        except KeyError:
            raw_value = data["distinct_id"]
    if not raw_value:
        raise ValueError()
    return str(raw_value)[0:200]


def _ensure_web_feature_flags_in_properties(event: Dict[str, Any], team: Team, distinct_id: str):
    """If the event comes from web, ensure that it contains property $active_feature_flags."""
    if event["properties"].get("$lib") == "web" and "$active_feature_flags" not in event["properties"]:
        flags = get_active_feature_flags(team, distinct_id)
        event["properties"]["$active_feature_flags"] = list(flags.keys())
        for k, v in flags.items():
            event["properties"][f"$feature/{k}"] = v


@csrf_exempt
def get_event(request):
    timer = statsd.timer("posthog_cloud_event_endpoint").start()
    now = timezone.now()

    data, error_response = get_data(request)

    if error_response:
        return error_response

    sent_at = _get_sent_at(data, request)

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

    team, db_error, error_response = get_team(request, data, token)

    if error_response:
        return error_response

    send_events_to_dead_letter_queue = False
    if db_error and is_clickhouse_enabled():
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
        events = preprocess_session_recording_events(events)
    except ValueError as e:
        return cors_response(
            request, generate_exception_response("capture", f"Invalid payload: {e}", code="invalid_payload")
        )

    site_url = request.build_absolute_uri("/")[:-1]

    ip = None if not team or team.anonymize_ips else get_ip_address(request)
    for event in events:
        event_uuid = UUIDT()
        distinct_id = get_distinct_id(event)
        if not distinct_id:
            continue

        event = parse_event(event, distinct_id, team)
        if not event:
            continue

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

        statsd.incr("posthog_cloud_plugin_server_ingestion")
        capture_internal(event, distinct_id, ip, site_url, now, sent_at, team.pk, event_uuid)  # type: ignore

    timer.stop()
    statsd.incr(
        f"posthog_cloud_raw_endpoint_success", tags={"endpoint": "capture",},
    )
    return cors_response(request, JsonResponse({"status": 1}))


def parse_event(event, distinct_id, team):
    if not event.get("event"):
        statsd.incr("invalid_event", tags={"error": "missing_event_name"})
        return

    if not event.get("properties"):
        event["properties"] = {}

    with configure_scope() as scope:
        scope.set_tag("library", event["properties"].get("$lib", "unknown"))
        scope.set_tag("library.version", event["properties"].get("$lib_version", "unknown"))

    if team:
        _ensure_web_feature_flags_in_properties(event, team, distinct_id)

    return event


def get_distinct_id(event):
    try:
        distinct_id = _get_distinct_id(event)
    except KeyError:
        statsd.incr("invalid_event", tags={"error": "missing_distinct_id"})
        return
    except ValueError:
        statsd.incr("invalid_event", tags={"error": "invalid_distinct_id"})
        return

    return distinct_id


def capture_internal(event, distinct_id, ip, site_url, now, sent_at, team_id, event_uuid=UUIDT()) -> None:
    if is_clickhouse_enabled():
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
        log_event(parsed_event, event["event"])
    else:
        task_name = "posthog.tasks.process_event.process_event_with_plugins"
        celery_queue = settings.PLUGINS_CELERY_QUEUE
        celery_app.send_task(
            name=task_name,
            queue=celery_queue,
            args=[distinct_id, ip, site_url, event, team_id, now.isoformat(), sent_at,],
        )
