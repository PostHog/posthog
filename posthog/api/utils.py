import json
import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, List, Optional, Tuple, Union, cast

from ratelimit import limits
from rest_framework import request, status
from sentry_sdk import capture_exception
from statshog.defaults.django import statsd

from posthog.exceptions import RequestParsingError, generate_exception_response
from posthog.models import Entity
from posthog.models.entity import MATH_TYPE
from posthog.models.filters.filter import Filter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.team import Team
from posthog.models.user import User
from posthog.utils import cors_response, load_data_from_request


class PaginationMode(Enum):
    next = auto()
    previous = auto()


def get_target_entity(filter: Union[Filter, StickinessFilter]) -> Entity:
    if not filter.target_entity_id:
        raise ValueError("An entity id and the entity type must be provided to determine an entity")

    entity_math = filter.target_entity_math or "total"  # make math explicit
    possible_entity = entity_from_order(filter.target_entity_order, filter.entities)

    if possible_entity:
        return possible_entity

    possible_entity = retrieve_entity_from(
        filter.target_entity_id, filter.target_entity_type, entity_math, filter.events, filter.actions
    )
    if possible_entity:
        return possible_entity
    elif filter.target_entity_type:
        return Entity({"id": filter.target_entity_id, "type": filter.target_entity_type, "math": entity_math})
    else:
        raise ValueError("An entity must be provided for target entity to be determined")


def entity_from_order(order: Optional[str], entities: List[Entity]) -> Optional[Entity]:
    if not order:
        return None

    for entity in entities:
        if entity.index == int(order):
            return entity
    return None


def retrieve_entity_from(
    entity_id: str, entity_type: Optional[str], entity_math: MATH_TYPE, events: List[Entity], actions: List[Entity]
) -> Optional[Entity]:
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
            if action.id == entity_id and (action.math or "total") == entity_math:
                return action
    else:
        for event in events:
            if event.id == entity_id and (event.math or "total") == entity_math:
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


@limits(calls=10, period=1)
def capture_as_common_error_to_sentry_ratelimited(common_message, error):
    try:
        raise Exception(common_message) from error
    except Exception as error_for_sentry:
        capture_exception(error_for_sentry)


def get_data(request):
    data = None
    try:
        data = load_data_from_request(request)
    except RequestParsingError as error:
        capture_as_common_error_to_sentry_ratelimited(
            "Invalid payload", error
        )  # We still capture this on Sentry to identify actual potential bugs
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


@dataclass(frozen=True)
class EventIngestionContext:
    """
    Specifies the data needed to process inbound `Event`s. Specifically we need
    to know which team_id to attach to an event, and if we should exclude ip
    address information.

    Prior to this structure we were pulling in the entirety of
    `posthog.models.Team`, which includes many variables that are not specific
    to the context of ingestion. With this structure we can be deliberate about
    our ingestion interfaces.

    The initial driver for this was to reduce the amount of data we were
    fetching from postgresql db.
    """

    team_id: int
    anonymize_ips: bool


def get_event_ingestion_context(
    request, data, token
) -> Tuple[Optional[EventIngestionContext], Optional[str], Optional[Any]]:
    db_error = None
    ingestion_context = None
    error_response = None

    try:
        ingestion_context = get_event_ingestion_context_for_token(token)
    except Exception as e:
        capture_exception(e)
        statsd.incr("capture_endpoint_fetch_team_fail")

        db_error = getattr(e, "message", repr(e))

        return None, db_error, error_response

    if ingestion_context is None:
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

        ingestion_context = get_event_ingestion_context_for_personal_api_key(
            personal_api_key=token, project_id=project_id
        )
        if ingestion_context is None:
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

    # if we still haven't found a ingestion_context, return an error to the client
    if not ingestion_context:
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

    return ingestion_context, db_error, error_response


def get_event_ingestion_context_for_token(token: str) -> Optional[EventIngestionContext]:
    """
    Based on a token associated with a Team, retrieve the context that is
    required to ingest events.
    """
    try:
        team_id, anonymize_ips = Team.objects.values_list("id", "anonymize_ips").get(api_token=token)
        # NOTE: Not sure why, but I needed to do this cast otherwise I got
        # `Optional[bool]` instead of `bool` from mypy, even though
        # anonymize_ips is non-null in the model
        anonymize_ips = cast(bool, anonymize_ips)
        return EventIngestionContext(team_id=team_id, anonymize_ips=anonymize_ips)
    except Team.DoesNotExist:
        return None


def get_event_ingestion_context_for_personal_api_key(
    personal_api_key: str, project_id: int
) -> Optional[EventIngestionContext]:
    """
    Some events use the personal_api_key on a `User` for authentication, along
    with a `project_id`.
    """
    user = User.objects.get_from_personal_api_key(personal_api_key)

    if user is None:
        return None

    try:
        team_id, anonymize_ips = user.teams.values_list("id", "anonymize_ips").get(id=project_id)
        return EventIngestionContext(team_id=team_id, anonymize_ips=anonymize_ips)
    except Team.DoesNotExist:
        return None


def check_definition_ids_inclusion_field_sql(
    raw_included_definition_ids: Optional[str], is_property: bool, named_key: str
):

    # Create conditional field based on whether id exists in included_properties
    if is_property:
        included_definitions_sql = f"(posthog_propertydefinition.id = ANY (%({named_key})s::uuid[]))"
    else:
        included_definitions_sql = f"(posthog_eventdefinition.id = ANY (%({named_key})s::uuid[]))"

    if not raw_included_definition_ids:
        return included_definitions_sql, []

    return included_definitions_sql, list(set(json.loads(raw_included_definition_ids)))


# keep in sync with posthog/plugin-server/src/utils/db/utils.ts::safeClickhouseString
def safe_clickhouse_string(s: str) -> str:
    surrogate_regex = re.compile("([\ud800-\udfff])")
    matches = re.findall(surrogate_regex, s or "")
    for match in matches:
        s = s.replace(match, match.encode("unicode_escape").decode("utf8"))
    return s
