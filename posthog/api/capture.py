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
from posthog.utils import cors_response, get_ip_address, is_clickhouse_enabled, load_data_from_request

if is_clickhouse_enabled():
    from ee.kafka_client.client import KafkaProducer
    from ee.kafka_client.topics import KAFKA_EVENTS_PLUGIN_INGESTION

    def log_event(
        distinct_id: str,
        ip: Optional[str],
        site_url: str,
        data: dict,
        team_id: int,
        now: datetime,
        sent_at: Optional[datetime],
        event_uuid: UUIDT,
        *,
        topic: str = KAFKA_EVENTS_PLUGIN_INGESTION,
    ) -> None:
        if settings.DEBUG:
            print(f'Logging event {data["event"]} to Kafka topic {topic}')
        data = {
            "uuid": str(event_uuid),
            "distinct_id": distinct_id,
            "ip": ip,
            "site_url": site_url,
            "data": json.dumps(data),
            "team_id": team_id,
            "now": now.isoformat(),
            "sent_at": sent_at.isoformat() if sent_at else "",
        }
        KafkaProducer().produce(topic=topic, data=data)


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

    team = Team.objects.get_team_from_token(token)

    if team is None:
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
            return cors_response(
                request,
                generate_exception_response(
                    "capture",
                    "You need to set user distinct ID field `distinct_id`.",
                    code="required",
                    attr="distinct_id",
                ),
            )
        except ValueError:
            return cors_response(
                request,
                generate_exception_response(
                    "capture",
                    "Distinct ID field `distinct_id` must have a non-empty value.",
                    code="required",
                    attr="distinct_id",
                ),
            )
        if not event.get("event"):
            return cors_response(
                request,
                generate_exception_response(
                    "capture", "You need to set user event name, field `event`.", code="required", attr="event"
                ),
            )

        site_url = request.build_absolute_uri("/")[:-1]
        ip = None if team.anonymize_ips else get_ip_address(request)

        if not event.get("properties"):
            event["properties"] = {}

        # Support test_[apiKey] for users with multiple environments
        if event["properties"].get("$environment") is None and is_test_environment:
            event["properties"]["$environment"] = ENVIRONMENT_TEST

        _ensure_web_feature_flags_in_properties(event, team, distinct_id)

        statsd.incr("posthog_cloud_plugin_server_ingestion")
        capture_internal(event, distinct_id, ip, site_url, now, sent_at, team.pk)

    timer.stop()
    statsd.incr(
        f"posthog_cloud_raw_endpoint_success", tags={"endpoint": "capture",},
    )
    return cors_response(request, JsonResponse({"status": 1}))


def capture_internal(event, distinct_id, ip, site_url, now, sent_at, team_id):
    event_uuid = UUIDT()

    if is_clickhouse_enabled():
        log_event(
            distinct_id=distinct_id,
            ip=ip,
            site_url=site_url,
            data=event,
            team_id=team_id,
            now=now,
            sent_at=sent_at,
            event_uuid=event_uuid,
        )
    else:
        task_name = "posthog.tasks.process_event.process_event_with_plugins"
        celery_queue = settings.PLUGINS_CELERY_QUEUE
        celery_app.send_task(
            name=task_name,
            queue=celery_queue,
            args=[distinct_id, ip, site_url, event, team_id, now.isoformat(), sent_at,],
        )
