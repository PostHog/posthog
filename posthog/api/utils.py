import json
import re
import socket
import urllib.parse
from enum import Enum, auto
from ipaddress import ip_address
from typing import List, Literal, Optional, Union, Tuple
from uuid import UUID

import structlog
from django.core.exceptions import RequestDataTooBig
from django.db.models import QuerySet
from prometheus_client import Counter
from rest_framework import request, status
from rest_framework.exceptions import ValidationError
from statshog.defaults.django import statsd

from posthog.constants import EventDefinitionType
from posthog.exceptions import RequestParsingError, generate_exception_response
from posthog.models import Entity, EventDefinition
from posthog.models.entity import MathType
from posthog.models.filters.filter import Filter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.utils import load_data_from_request
from posthog.utils_cors import cors_response

logger = structlog.get_logger(__name__)


class PaginationMode(Enum):
    next = auto()
    previous = auto()


def get_target_entity(filter: Union[Filter, StickinessFilter]) -> Entity:
    # Except for "events", we require an entity id and type to be provided
    if not filter.target_entity_id and filter.target_entity_type != "events":
        raise ValidationError("An entity id and the entity type must be provided to determine an entity")

    entity_math = filter.target_entity_math or "total"  # make math explicit
    possible_entity = entity_from_order(filter.target_entity_order, filter.entities)

    if possible_entity:
        return possible_entity

    possible_entity = retrieve_entity_from(
        filter.target_entity_id,
        filter.target_entity_type,
        entity_math,
        filter.events,
        filter.actions,
    )
    if possible_entity:
        return possible_entity
    elif filter.target_entity_type:
        return Entity(
            {
                "id": filter.target_entity_id,
                "type": filter.target_entity_type,
                "math": entity_math,
            }
        )
    else:
        raise ValidationError("An entity must be provided for target entity to be determined")


def entity_from_order(order: Optional[str], entities: List[Entity]) -> Optional[Entity]:
    if not order:
        return None

    for entity in entities:
        if entity.index == int(order):
            return entity
    return None


def retrieve_entity_from(
    entity_id: Optional[str],
    entity_type: Optional[str],
    entity_math: MathType,
    events: List[Entity],
    actions: List[Entity],
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


def get_data(request):
    data = None
    try:
        data = load_data_from_request(request)
    except RequestParsingError as error:
        statsd.incr("capture_endpoint_invalid_payload")
        logger.exception(f"Invalid payload", error=error)
        return (
            None,
            cors_response(
                request,
                generate_exception_response(
                    "capture",
                    f"Malformed request data: {error}",
                    code="invalid_payload",
                ),
            ),
        )

    except RequestDataTooBig:
        return (
            None,
            cors_response(
                request,
                generate_exception_response(
                    endpoint="capture",
                    detail="Request too large.",
                    type="client_error",
                    code="request_too_large",
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                ),
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


def check_definition_ids_inclusion_field_sql(
    raw_included_definition_ids: Optional[str], is_property: bool, named_key: str
):
    # Create conditional field based on whether id exists in included_properties
    if is_property:
        included_definitions_sql = f"(id = ANY (%({named_key})s::uuid[]))"
    else:
        included_definitions_sql = f"(id = ANY (%({named_key})s::uuid[]))"

    if not raw_included_definition_ids:
        return included_definitions_sql, []

    return included_definitions_sql, list(set(json.loads(raw_included_definition_ids)))


SURROGATE_REGEX = re.compile("([\ud800-\udfff])")

SURROGATES_SUBSTITUTED_COUNTER = Counter(
    "surrogates_substituted_total",
    "Stray UTF16 surrogates detected and removed from user input.",
)


# keep in sync with posthog/plugin-server/src/utils/db/utils.ts::safeClickhouseString
def safe_clickhouse_string(s: str) -> str:
    matches = SURROGATE_REGEX.findall(s or "")
    for match in matches:
        SURROGATES_SUBSTITUTED_COUNTER.inc()
        s = s.replace(match, match.encode("unicode_escape").decode("utf8"))
    return s


def create_event_definitions_sql(
    event_type: EventDefinitionType,
    is_enterprise: bool = False,
    conditions: str = "",
    order_expressions: List[Tuple[str, Literal["ASC", "DESC"]]] = [],
) -> str:
    if is_enterprise:
        from ee.models import EnterpriseEventDefinition

        ee_model = EnterpriseEventDefinition
    else:
        ee_model = EventDefinition  # type: ignore

    event_definition_fields = {
        f'"{f.column}"'  # type: ignore
        for f in ee_model._meta.get_fields()
        if hasattr(f, "column") and f.column not in ["deprecated_tags", "tags"]  # type: ignore
    }

    enterprise_join = (
        "FULL OUTER JOIN ee_enterpriseeventdefinition ON posthog_eventdefinition.id=ee_enterpriseeventdefinition.eventdefinition_ptr_id"
        if is_enterprise
        else ""
    )

    if event_type == EventDefinitionType.EVENT_CUSTOM:
        conditions += " AND posthog_eventdefinition.name NOT LIKE %(is_posthog_event)s"
    if event_type == EventDefinitionType.EVENT_POSTHOG:
        conditions += " AND posthog_eventdefinition.name LIKE %(is_posthog_event)s"

    additional_ordering = ""
    for order_expression, order_direction in order_expressions:
        additional_ordering += (
            f"{order_expression} {order_direction} NULLS {'FIRST' if order_direction == 'ASC' else 'LAST'}, "
            if order_expression
            else ""
        )

    return f"""
            SELECT {",".join(event_definition_fields)}
            FROM posthog_eventdefinition
            {enterprise_join}
            WHERE team_id = %(team_id)s {conditions}
            ORDER BY {additional_ordering}name ASC
        """


def get_pk_or_uuid(queryset: QuerySet, key: Union[int, str]) -> QuerySet:
    try:
        # Test if value is a UUID
        UUID(key)  # type: ignore
        return queryset.filter(uuid=key)
    except ValueError:
        return queryset.filter(pk=key)


def parse_bool(value: Union[str, List[str]]) -> bool:
    if value == "true":
        return True
    return False


def raise_if_user_provided_url_unsafe(url: str):
    """Raise if the provided URL seems unsafe, otherwise do nothing.

    Equivalent of plugin server raiseIfUserProvidedUrlUnsafe.
    """
    parsed_url: urllib.parse.ParseResult = urllib.parse.urlparse(url)  # urlparse never raises errors
    if not parsed_url.hostname:
        raise ValueError("No hostname")
    if parsed_url.scheme not in ("http", "https"):
        raise ValueError("Scheme must be either HTTP or HTTPS")
    # Disallow if hostname resolves to a private (internal) IP address
    try:
        addrinfo = socket.getaddrinfo(parsed_url.hostname, None)
    except socket.gaierror:
        raise ValueError("Invalid hostname")
    for _, _, _, _, sockaddr in addrinfo:
        if ip_address(sockaddr[0]).is_private:  # Prevent addressing internal services
            raise ValueError("Internal hostname")
