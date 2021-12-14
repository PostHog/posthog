import json
from enum import Enum, auto
from typing import (
    Any,
    Dict,
    List,
    Literal,
    Optional,
    Tuple,
    Union,
    cast,
)

from rest_framework import request, status
from sentry_sdk import capture_exception
from statshog.defaults.django import statsd

from posthog.constants import ENTITY_ID, ENTITY_MATH, ENTITY_TYPE
from posthog.exceptions import RequestParsingError, generate_exception_response
from posthog.models import Entity
from posthog.models.entity import MATH_TYPE
from posthog.models.team import Team
from posthog.models.user import User
from posthog.utils import cors_response, is_clickhouse_enabled, load_data_from_request


class PaginationMode(Enum):
    next = auto()
    previous = auto()


def get_target_entity(request: request.Request) -> Entity:
    entity_id: Optional[str] = request.GET.get(ENTITY_ID)
    events = request.GET.get("events", "[]")
    actions = request.GET.get("actions", "[]")
    entity_type = request.GET.get(ENTITY_TYPE)
    entity_math = cast(MATH_TYPE, request.GET.get(ENTITY_MATH, "total"))

    if not entity_id:
        raise ValueError("An entity id and the entity type must be provided to determine an entity")

    possible_entity = retrieve_entity_from(entity_id, entity_type, entity_math, json.loads(events), json.loads(actions))
    if possible_entity:
        return Entity(data=possible_entity)
    elif entity_type:
        return Entity({"id": entity_id, "type": entity_type, "math": entity_math})
    else:
        raise ValueError("An entity must be provided for target entity to be determined")


def retrieve_entity_from(
    entity_id: str, entity_type: Optional[str], entity_math: MATH_TYPE, events: List[Dict], actions: List[Dict]
) -> Optional[Dict]:
    """
    Retrieves the entity from the events and actions.

    NOTE: entity_id here is considered always to be a string. event ids are
    strings, and action ids are ints. Elsewhere we get the `entity_id` from a
    get request, from which we do not get type information, and we do not
    require the entity type to be provided. A more complete solution might be to
    require entity type information, but to resolve the issue we cast the action
    id to a string, such that we can get equality.

    This doesn't preclude ths issue that an event name could be a string that is
    also a valid number however, but this should be an unlikely occurance.
    """

    if entity_type == "actions":
        for action in actions:
            if str(action.get("id")) == entity_id and action.get("math", "total") == entity_math:
                return action
    else:
        for event in events:
            if event.get("id") == entity_id and event.get("math", "total") == entity_math:
                return event
    return None


def format_paginated_url(request: request.Request, offset: int, page_size: int, mode=PaginationMode.next):
    result = request.get_full_path()
    if not result:
        return None

    new_offset = offset - page_size if mode == PaginationMode.previous else offset + page_size

    if new_offset < 0:
        return None

    if "offset" in result:
        result = result[1:]
        result = result.replace(f"offset={offset}", f"offset={new_offset}")
    else:
        result = request.build_absolute_uri("{}{}offset={}".format(result, "&" if "?" in result else "?", new_offset))
    return result


def get_token(data, request) -> Optional[str]:
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
    return token


def get_project_id(data, request) -> Optional[int]:
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
            None,
            cors_response(
                request,
                generate_exception_response("capture", f"Malformed request data: {error}", code="invalid_payload"),
            ),
        )

    if not data:
        return (
            None,
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


def get_team(request, data, token) -> Tuple[Optional[Team], Optional[str], Optional[Any]]:
    db_error = None
    team = None
    error_response = None

    try:
        team = Team.objects.get_team_from_token(token)
    except Exception as e:
        capture_exception(e)
        statsd.incr("capture_endpoint_fetch_team_fail")

        db_error = getattr(e, "message", repr(e))

        if not is_clickhouse_enabled():
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

        return None, db_error, error_response

    if team is None:
        try:
            project_id = get_project_id(data, request)
        except ValueError:
            error_response = cors_response(
                request,
                generate_exception_response(
                    "capture", "Invalid Project ID.", code="invalid_project", attr="project_id"
                ),
            )
            return None, db_error, error_response

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
            return None, db_error, error_response

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
            return None, db_error, error_response

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

    return team, db_error, error_response
