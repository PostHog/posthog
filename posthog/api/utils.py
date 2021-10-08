import re
from typing import Any, Optional, Tuple

from rest_framework import request, status
from sentry_sdk import capture_exception
from statshog.defaults.django import statsd

from posthog.constants import ENTITY_ID, ENTITY_MATH, ENTITY_TYPE
from posthog.exceptions import RequestParsingError, generate_exception_response
from posthog.models import Entity
from posthog.models.team import Team
from posthog.models.user import User
from posthog.utils import cors_response, is_clickhouse_enabled, load_data_from_request


def get_target_entity(request: request.Request) -> Entity:
    entity_id = request.GET.get(ENTITY_ID)
    entity_type = request.GET.get(ENTITY_TYPE)
    entity_math = request.GET.get(ENTITY_MATH, None)

    if entity_id and entity_type:
        return Entity({"id": entity_id, "type": entity_type, "math": entity_math})
    else:
        raise ValueError("An entity must be provided for target entity to be determined")


def format_next_url(request: request.Request, offset: int, page_size: int):
    next_url = request.get_full_path()
    if not next_url:
        return None

    new_offset = str(offset + page_size)

    if "offset" in next_url:
        next_url = next_url[1:]
        next_url = next_url.replace(f"offset={str(offset)}", f"offset={new_offset}")
    else:
        next_url = request.build_absolute_uri(
            "{}{}offset={}".format(next_url, "&" if "?" in next_url else "?", offset + page_size)
        )
    return next_url


OFFSET_REGEX = re.compile(r"([&?]offset=)(\d+)")


def format_offset_absolute_url(request: request.Request, offset: int):
    url_to_format = request.get_raw_uri()

    if not url_to_format:
        return None

    if OFFSET_REGEX.match(url_to_format):
        url_to_format = OFFSET_REGEX.sub(fr"\g<1>{offset}", url_to_format)
    else:
        url_to_format = url_to_format + ("&" if "?" in url_to_format else "?") + f"offset={offset}"

    return url_to_format


def get_token(data, request) -> Tuple[Optional[str], bool]:
    token = None
    if request.method == "GET":
        if request.GET.get("token"):
            token = request.GET.get("token")  # token passed as query param
        elif request.GET.get("api_key"):
            token = request.GET.get("api_key")  # api_key passed as query param

    if not token:
        if request.POST.get("api_key"):
            token = request.POST["api_key"]
        elif request.POST.get("token"):
            token = request.POST["token"]
        elif data:
            if isinstance(data, list):
                data = data[0]  # Mixpanel Swift SDK
            if isinstance(data, dict):
                if data.get("$token"):
                    token = data["$token"]  # JS identify call
                elif data.get("token"):
                    token = data["token"]  # JS reloadFeatures call
                elif data.get("api_key"):
                    token = data["api_key"]  # server-side libraries like posthog-python and posthog-ruby
                elif data.get("properties") and data["properties"].get("token"):
                    token = data["properties"]["token"]  # JS capture call

    if token:
        return clean_token(token)
    return None, False


# Support test_[apiKey] for users with multiple environments
def clean_token(token) -> Tuple[str, bool]:
    is_test_environment = token.startswith("test_")
    token = token[5:] if is_test_environment else token
    return token, is_test_environment


def get_project_id_from_request(data, request) -> Optional[int]:
    if request.GET.get("project_id"):
        return int(request.POST["project_id"])
    if request.POST.get("project_id"):
        return int(request.POST["project_id"])
    if isinstance(data, list):
        data = data[0]  # Mixpanel Swift SDK
    if data.get("project_id"):
        return int(data["project_id"])
    return None


def get_data(request):
    data = None
    try:
        data = load_data_from_request(request)
    except RequestParsingError as error:
        capture_exception(error)  # We still capture this on Sentry to identify actual potential bugs
        return (
            data,
            cors_response(
                request,
                generate_exception_response("capture", f"Malformed request data: {error}", code="invalid_payload"),
            ),
        )

    if not data:
        return (
            data,
            cors_response(
                request,
                generate_exception_response(
                    "capture",
                    "No data found. Make sure to use a POST request when sending the payload in the body of the request.",
                    code="no_data",
                ),
            ),
        )

    return data, None


def get_team(request, data, token) -> Tuple[Optional[Team], Optional[Any]]:
    team = None
    error_response = None

    try:
        team = Team.objects.get_team_from_token(token)
    except Exception as e:
        capture_exception(e)
        statsd.incr("capture_endpoint_fetch_team_fail")

        error_response = cors_response(
            request,
            generate_exception_response(
                "capture",
                "Unable to fetch team from database.",
                type="server_error",
                code="fetch_team_fail",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            ),
        )

        return team, error_response

    if team is None:
        try:
            project_id = get_project_id_from_request(data, request)
        except ValueError:
            error_response = cors_response(
                request,
                generate_exception_response(
                    "capture", "Invalid Project ID.", code="invalid_project", attr="project_id"
                ),
            )
            return team, error_response

        if not project_id:
            error_response = cors_response(
                request,
                generate_exception_response(
                    "capture",
                    "Project API key invalid. You can find your project API key in PostHog project settings.",
                    type="authentication_error",
                    code="invalid_api_key",
                    status_code=status.HTTP_401_UNAUTHORIZED,
                ),
            )
            return team, error_response

        user = User.objects.get_from_personal_api_key(token)
        if user is None:
            error_response = cors_response(
                request,
                generate_exception_response(
                    "capture",
                    "Invalid Personal API key.",
                    type="authentication_error",
                    code="invalid_personal_api_key",
                    status_code=status.HTTP_401_UNAUTHORIZED,
                ),
            )
            return team, error_response

        team = user.teams.get(id=project_id)

    # if we still haven't found a team, return an error to the client
    if not team:
        error_response = cors_response(
            request,
            generate_exception_response(
                "capture",
                "No team found for API Key",
                type="authentication_error",
                code="invalid_personal_api_key",
                status_code=status.HTTP_401_UNAUTHORIZED,
            ),
        )

    return team, error_response
