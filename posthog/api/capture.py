import json
import re
from datetime import datetime
from typing import Any, Dict, Optional

from dateutil import parser
from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from sentry_sdk import capture_exception
from statshog.defaults.django import statsd

from posthog.api.utils import get_token
from posthog.celery import app as celery_app
from posthog.constants import ENVIRONMENT_TEST
from posthog.exceptions import RequestParsingError, generate_exception_response
from posthog.helpers.session_recording import preprocess_session_recording_events
from posthog.models import Team, User
from posthog.models.feature_flag import get_active_feature_flags
from posthog.models.utils import UUIDT
from posthog.settings import EVENTS_DEAD_LETTER_QUEUE_STATSD_METRIC
from posthog.utils import cors_response, get_ip_address, is_clickhouse_enabled, load_data_from_request

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

    def log_event(data: Dict, topic: str = KAFKA_EVENTS_PLUGIN_INGESTION,) -> None:
        if settings.DEBUG:
            print(f'Logging event {data["event"]} to Kafka topic {topic}')
        KafkaProducer().produce(topic=topic, key=data["ip"], data=data)

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
        data["event_uuid"] = event["uuid"]
        data["event"] = event_name
        data["raw_payload"] = json.dumps(raw_payload)

        del data["uuid"]

        KafkaProducer().produce(topic=topic, data=data)

        statsd.incr(EVENTS_DEAD_LETTER_QUEUE_STATSD_METRIC)


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


def _get_project_id(data, request) -> Optional[int]:
    if request.GET.get("project_id"):
        return int(request.POST["project_id"])
    if request.POST.get("project_id"):
        return int(request.POST["project_id"])
    if isinstance(data, list):
        data = data[0]  # Mixpanel Swift SDK
    if data.get("project_id"):
        return int(data["project_id"])
    return None


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
    try:
        data = load_data_from_request(request)
    except RequestParsingError as error:
        capture_exception(error)  # We still capture this on Sentry to identify actual potential bugs
        return cors_response(
            request, generate_exception_response("capture", f"Malformed request data: {error}", code="invalid_payload"),
        )
    if not data:
        return cors_response(
            request,
            generate_exception_response(
                "capture",
                "No data found. Make sure to use a POST request when sending the payload in the body of the request.",
                code="no_data",
            ),
        )

    sent_at = _get_sent_at(data, request)

    token, is_test_environment = get_token(data, request)

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

    send_events_to_dead_letter_queue = False
    fetch_team_error = None
    team = None

    try:
        team = Team.objects.get_team_from_token(token)
    except Exception as e:
        capture_exception(e)
        statsd.incr("capture_endpoint_fetch_team_fail")

        # Postgres deployments don't have a dead letter queue, so
        # just return an error to the client
        if not is_clickhouse_enabled():
            return cors_response(
                request,
                generate_exception_response(
                    "capture",
                    "Unable to fetch team from database.",
                    type="server_error",
                    code="fetch_team_fail",
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                ),
            )

        fetch_team_error = getattr(e, "message", repr(e))

        # We use this approach because each individual event needs to go through some parsing
        # before being added to the dead letter queue
        send_events_to_dead_letter_queue = True

    if team is None and not send_events_to_dead_letter_queue:
        try:
            project_id = _get_project_id(data, request)
        except ValueError:
            return cors_response(
                request,
                generate_exception_response(
                    "capture", "Invalid Project ID.", code="invalid_project", attr="project_id"
                ),
            )
        if not project_id:
            return cors_response(
                request,
                generate_exception_response(
                    "capture",
                    "Project API key invalid. You can find your project API key in PostHog project settings.",
                    type="authentication_error",
                    code="invalid_api_key",
                    status_code=status.HTTP_401_UNAUTHORIZED,
                ),
            )
        user = User.objects.get_from_personal_api_key(token)
        if user is None:
            return cors_response(
                request,
                generate_exception_response(
                    "capture",
                    "Invalid Personal API key.",
                    type="authentication_error",
                    code="invalid_personal_api_key",
                    status_code=status.HTTP_401_UNAUTHORIZED,
                ),
            )
        team = user.teams.get(id=project_id)

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

    for event in events:
        try:
            distinct_id = _get_distinct_id(event)
        except KeyError:
            statsd.incr("invalid_event", tags={"error": "missing_distinct_id"})
            continue
        except ValueError:
            statsd.incr("invalid_event", tags={"error": "invalid_distinct_id"})
            continue
        if not event.get("event"):
            statsd.incr("invalid_event", tags={"error": "missing_event_name"})
            continue

        event_uuid = UUIDT()
        site_url = request.build_absolute_uri("/")[:-1]

        if not event.get("properties"):
            event["properties"] = {}

        # Support test_[apiKey] for users with multiple environments
        if event["properties"].get("$environment") is None and is_test_environment:
            event["properties"]["$environment"] = ENVIRONMENT_TEST

        # Dead Letter Queue is a EE-only feature, as it uses Kafka + CH
        # The first check is redundant but added for typing and explictness
        if is_clickhouse_enabled() and send_events_to_dead_letter_queue:
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
                f"Unable to fetch team from Postgres. Error: {fetch_team_error}",
                "django_server_capture_endpoint",
            )
            continue

        # this should not happen, but is needed to satisfy typing as team "could be" None
        if not team:
            return cors_response(
                request,
                generate_exception_response(
                    "capture",
                    "No team found for API Key",
                    type="authentication_error",
                    code="invalid_personal_api_key",
                    status_code=status.HTTP_401_UNAUTHORIZED,
                ),
            )

        ip = None if team.anonymize_ips else get_ip_address(request)
        _ensure_web_feature_flags_in_properties(event, team, distinct_id)

        statsd.incr("posthog_cloud_plugin_server_ingestion")
        capture_internal(event, distinct_id, ip, site_url, now, sent_at, team.pk, event_uuid)

    timer.stop()
    statsd.incr(
        f"posthog_cloud_raw_endpoint_success", tags={"endpoint": "capture",},
    )
    return cors_response(request, JsonResponse({"status": 1}))


def capture_internal(event, distinct_id, ip, site_url, now, sent_at, team_id, event_uuid=UUIDT()):
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
        log_event(parsed_event)
    else:
        task_name = "posthog.tasks.process_event.process_event_with_plugins"
        celery_queue = settings.PLUGINS_CELERY_QUEUE
        celery_app.send_task(
            name=task_name,
            queue=celery_queue,
            args=[distinct_id, ip, site_url, event, team_id, now.isoformat(), sent_at,],
        )
