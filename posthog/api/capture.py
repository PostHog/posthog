import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from dateutil import parser
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from posthog.auth import PersonalAPIKeyAuthentication
from posthog.ee import check_ee_enabled
from posthog.models import Team
from posthog.tasks.process_event import process_event
from posthog.utils import cors_response, get_ip_address, load_data_from_request

if settings.EE_AVAILABLE:
    from ee.clickhouse.process_event import process_event_ee


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


def _get_token(data, request) -> Optional[str]:
    if request.POST.get("api_key"):
        return request.POST["api_key"]
    if isinstance(data, list) and len(data) > 0:
        return data[0]["properties"]["token"]  # Mixpanel Swift SDK
    if data.get("$token"):
        return data["$token"]  # JS identify call
    if data.get("api_key"):
        return data["api_key"]  # server-side libraries like posthog-python and posthog-ruby
    if data.get("properties") and data["properties"].get("token"):
        return data["properties"]["token"]  # JS capture call
    return None


def _get_distinct_id(data: Dict[str, Any]) -> str:
    try:
        return str(data["$distinct_id"])[0:200]
    except KeyError:
        try:
            return str(data["properties"]["distinct_id"])[0:200]
        except KeyError:
            return str(data["distinct_id"])[0:200]


@csrf_exempt
def get_event(request):
    now = timezone.now()
    try:
        data_from_request = load_data_from_request(request)
        data = data_from_request["data"]
    except TypeError:
        return cors_response(
            request,
            JsonResponse(
                {"code": "validation", "message": "Malformed request data. Make sure you're sending valid JSON.",},
                status=400,
            ),
        )
    if not data:
        return cors_response(
            request,
            JsonResponse(
                {
                    "code": "validation",
                    "message": "No data found. Make sure to use a POST request when sending the payload in the body of the request.",
                },
                status=400,
            ),
        )
    sent_at = _get_sent_at(data, request)

    token = _get_token(data, request)
    is_personal_api_key = False
    if not token:
        token = PersonalAPIKeyAuthentication.find_key(
            request, data_from_request["body"], data if isinstance(data, dict) else None
        )
        is_personal_api_key = True
    if not token:
        return cors_response(
            request,
            JsonResponse(
                {
                    "code": "validation",
                    "message": "Neither api_key nor personal_api_key set. You can find your API key in the /setup page in PostHog.",
                },
                status=400,
            ),
        )

    team = Team.objects.get_team_from_token(token, is_personal_api_key)
    if team is None:
        return cors_response(
            request,
            JsonResponse(
                {
                    "code": "validation",
                    "message": "Team or personal API key invalid. You can find your team API key in the /setup page in PostHog.",
                },
                status=400,
            ),
        )

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

    for event in events:
        try:
            distinct_id = _get_distinct_id(event)
        except KeyError:
            return cors_response(
                request,
                JsonResponse(
                    {
                        "code": "validation",
                        "message": "You need to set user distinct ID field `distinct_id`.",
                        "item": event,
                    },
                    status=400,
                ),
            )
        if "event" not in event:
            return cors_response(
                request,
                JsonResponse(
                    {"code": "validation", "message": "You need to set event name field `event`.", "item": event,},
                    status=400,
                ),
            )

        process_event.delay(
            distinct_id=distinct_id,
            ip=get_ip_address(request),
            site_url=request.build_absolute_uri("/")[:-1],
            data=event,
            team_id=team.id,
            now=now,
            sent_at=sent_at,
        )
        if check_ee_enabled():
            process_event_ee.delay(
                distinct_id=distinct_id,
                ip=get_ip_address(request),
                site_url=request.build_absolute_uri("/")[:-1],
                data=event,
                team_id=team.id,
                now=now,
                sent_at=sent_at,
            )

    return cors_response(request, JsonResponse({"status": 1}))
