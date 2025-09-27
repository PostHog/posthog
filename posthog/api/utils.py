import re
import json
import time
import socket
import urllib.parse
from enum import Enum, auto
from functools import wraps
from ipaddress import ip_address
from typing import Any, Optional, Union
from urllib.parse import urlparse
from uuid import UUID

from django.core.exceptions import RequestDataTooBig
from django.db.models import QuerySet
from django.http import HttpRequest

import structlog
from posthoganalytics import capture_exception
from prometheus_client import Counter
from requests.adapters import HTTPAdapter
from rest_framework import request, serializers, status
from rest_framework.decorators import action as drf_action
from rest_framework.exceptions import ValidationError
from rest_framework.fields import Field
from statshog.defaults.django import statsd
from urllib3 import HTTPConnectionPool, HTTPSConnectionPool, PoolManager

from posthog.schema import QueryTiming

from posthog.api.documentation import extend_schema
from posthog.exceptions import (
    RequestParsingError,
    UnspecifiedCompressionFallbackParsingError,
    generate_exception_response,
)
from posthog.models import Entity
from posthog.models.entity import MathType
from posthog.models.filters.filter import Filter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.utils import load_data_from_request
from posthog.utils_cors import cors_response

logger = structlog.get_logger(__name__)


class PaginationMode(Enum):
    next = auto()
    previous = auto()


# This overrides a change in DRF 3.15 that alters our behavior. If the user passes an empty argument,
# the new version keeps it as null vs coalescing it to the default.
# Don't add this to new classes
class ClassicBehaviorBooleanFieldSerializer(serializers.BooleanField):
    def __init__(self, **kwargs):
        Field.__init__(self, allow_null=True, required=False, **kwargs)


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


def entity_from_order(order: Optional[str], entities: list[Entity]) -> Optional[Entity]:
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
    events: list[Entity],
    actions: list[Entity],
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


def is_csp_report(request) -> bool:
    return (
        request.path == "/report"
        or request.path == "/report/"
        or request.headers.get("Content-Type") in {"application/reports+json", "application/csp-report"}
    )


def get_token(data, request) -> Optional[str]:
    token = None

    if request.method == "GET" or is_csp_report(
        request
    ):  # CSPs are actually POST, but the token must be available at the report-uri/to URL
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
        return int(request.GET["project_id"])
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
    except (RequestParsingError, UnspecifiedCompressionFallbackParsingError) as error:
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
def safe_clickhouse_string(s: str, with_counter=True) -> str:
    matches = SURROGATE_REGEX.findall(s or "")
    for match in matches:
        if with_counter:
            SURROGATES_SUBSTITUTED_COUNTER.inc()
        s = s.replace(match, match.encode("unicode_escape").decode("utf8"))
    return s


def get_pk_or_uuid(queryset: QuerySet, key: Union[int, str]) -> QuerySet:
    try:
        # Test if value is a UUID
        UUID(key)
        return queryset.filter(uuid=key)
    except ValueError:
        return queryset.filter(pk=key)


INSIGHT_KINDS = {
    "TrendsQuery",
    "FunnelsQuery",
    "FunnelCorrelationQuery",
    "RetentionQuery",
    "PathsQuery",
    "StickinessQuery",
    "LifecycleQuery",
}

INSIGHT_ACTORS_KINDS = {
    "InsightActorsQuery",
    "FunnelsActorsQuery",
    "FunnelCorrelationActorsQuery",
    "StickinessActorsQuery",
}


def is_insight_query(query: dict) -> bool:
    kind = query.get("kind")
    source = query.get("source")

    if kind in INSIGHT_KINDS:
        return True
    if kind == "HogQLQuery":
        return True
    if kind == "DataTableNode":
        if source and (source.get("kind") or getattr(source, "kind", None)) in INSIGHT_KINDS:
            return True
    if kind == "DataVisualizationNode":
        if source and (source.get("kind") or getattr(source, "kind", None)) in INSIGHT_KINDS:
            return True

    return False


def is_insight_actors_query(query: dict) -> bool:
    kind = query.get("kind")
    source = query.get("source")

    if kind in INSIGHT_ACTORS_KINDS:
        return True
    if kind == "ActorsQuery":
        if source and (source.get("kind") or getattr(source, "kind", None)) in INSIGHT_ACTORS_KINDS:
            return True
    return False


def is_insight_actors_options_query(query: dict) -> bool:
    kind = query.get("kind")
    if kind == "InsightActorsQueryOptions":
        return True
    return False


def parse_bool(value: Union[str, list[str]]) -> bool:
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


def raise_if_connected_to_private_ip(conn):
    """Raise if the HTTPConnection / HTTPSConnection we are given points to a private IP."""
    if not getattr(conn, "sock", None):  # Force the connection open to check the remote IP
        conn.connect()
    addr = ip_address(conn.sock.getpeername()[0])
    if addr.is_private:
        raise ValueError("Internal IP")


class PublicIPOnlyHTTPConnectionPool(HTTPConnectionPool):
    def _validate_conn(self, conn):
        raise_if_connected_to_private_ip(conn)
        super()._validate_conn(conn)


class PublicIPOnlyHTTPSConnectionPool(HTTPSConnectionPool):
    def _validate_conn(self, conn):
        raise_if_connected_to_private_ip(conn)
        super()._validate_conn(conn)


class PublicIPOnlyHttpAdapter(HTTPAdapter):
    """Transport adapter that enforces that we only connect to public IPs

    Due to the lack of a hook after DNS resolution, we override the connection pool classes
    to check the remote IP after we connect to it, but before we send the request.

    Intended as a second line of defense after raise_if_user_provided_url_unsafe.
    """

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            **pool_kwargs,
        )
        self.poolmanager.pool_classes_by_scheme = {
            "http": PublicIPOnlyHTTPConnectionPool,
            "https": PublicIPOnlyHTTPSConnectionPool,
        }


def unparsed_hostname_in_allowed_url_list(allowed_url_list: Optional[list[str]], hostname: Optional[str]) -> bool:
    # if the browser url encodes the hostname, we need to decode it first
    hostname = urlparse(urllib.parse.unquote(hostname)).hostname if hostname else hostname
    return hostname_in_allowed_url_list(allowed_url_list, hostname)


def hostname_in_allowed_url_list(allowed_url_list: Optional[list[str]], hostname: Optional[str]) -> bool:
    if not hostname:
        return False

    permitted_domains = []
    if allowed_url_list:
        for url in allowed_url_list:
            host = parse_domain(url)
            if host:
                permitted_domains.append(host)

    for permitted_domain in permitted_domains:
        if "*" in permitted_domain:
            pattern = "^{}$".format(re.escape(permitted_domain).replace("\\*", "(.*)"))
            if re.search(pattern, hostname):
                return True
        elif permitted_domain == hostname:
            return True

    return False


def parse_domain(url: Any) -> Optional[str]:
    return urlparse(url).hostname


def on_permitted_recording_domain(permitted_domains: list[str], request: HttpRequest) -> bool:
    origin = parse_domain(request.headers.get("Origin"))
    referer = parse_domain(request.headers.get("Referer"))

    user_agent = request.META.get("HTTP_USER_AGENT")

    is_authorized_web_client: bool = hostname_in_allowed_url_list(
        permitted_domains, origin
    ) or hostname_in_allowed_url_list(permitted_domains, referer)
    # TODO this is a short term fix for beta testers
    # TODO we will match on the app identifier in the origin instead and allow users to auth those
    is_authorized_mobile_client: bool = user_agent is not None and any(
        keyword in user_agent
        for keyword in ["posthog-android", "posthog-ios", "posthog-react-native", "posthog-flutter"]
    )

    return is_authorized_web_client or is_authorized_mobile_client


# By default, DRF spectacular uses the serializer of the view as the response format for actions. However, most actions don't return a version of the model, but something custom. This function removes the response from all actions in the documentation.
def action(methods=None, detail=None, url_path=None, url_name=None, responses=None, **kwargs):
    """
    Mark a ViewSet method as a routable action.

    `@action`-decorated functions will be endowed with a `mapping` property,
    a `MethodMapper` that can be used to add additional method-based behaviors
    on the routed action.

    :param methods: A list of HTTP method names this action responds to.
                    Defaults to GET only.
    :param detail: Required. Determines whether this action applies to
                   instance/detail requests or collection/list requests.
    :param url_path: Define the URL segment for this action. Defaults to the
                     name of the method decorated.
    :param url_name: Define the internal (`reverse`) URL name for this action.
                     Defaults to the name of the method decorated with underscores
                     replaced with dashes.
    :param responses: Serializer or pydantic model of the response for documentation
    :param kwargs: Additional properties to set on the view.  This can be used
                   to override viewset-level *_classes settings, equivalent to
                   how the `@renderer_classes` etc. decorators work for function-
                   based API views.
    """

    def decorator(func):
        @extend_schema(responses=responses)
        @drf_action(
            methods=methods,
            detail=detail,
            url_path=url_path,
            url_name=url_name,
            **kwargs,
        )
        @wraps(func)
        def wrapped_function(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapped_function

    return decorator


# context manager for gathering a sequence of server timings
# can be used to then return the timings in the HTTP response headers
# so that browsers and other tools can show them
class ServerTimingsGathered:
    def __init__(self):
        # Instance level dictionary to store timings
        self.timings_dict = {}

    def __call__(self, name):
        self.name = name
        return self

    def __enter__(self):
        # timings are assumed to be in milliseconds when reported
        # but are gathered by time.perf_counter which is fractional seconds 🫠
        # so each value is multiplied by 1000 at collection
        self.start_time = time.perf_counter() * 1000

    def __exit__(self, exc_type, exc_val, exc_tb):
        end_time = time.perf_counter() * 1000
        elapsed_time = end_time - self.start_time
        self.timings_dict[self.name] = elapsed_time

    def get_all_timings(self):
        return self.timings_dict

    def generate_timings(self, hogql_timings: list[QueryTiming] | None = None) -> dict[str, float]:
        timings_dict = self.get_all_timings()
        hogql_timings_dict = {}
        for timing in hogql_timings or []:
            new_key = f"hogql_{timing.k.lstrip('./').replace('/', '_')}"
            # HogQL query timings are in seconds, convert to milliseconds
            hogql_timings_dict[new_key] = timing.t * 1000
        all_timings = {**timings_dict, **hogql_timings_dict}
        return all_timings

    def to_header_string(self, hogql_timings: list[QueryTiming] | None = None) -> str:
        timings = self.generate_timings(hogql_timings).items()
        result: list[str] = []
        current_length = 0

        for key, duration in timings:
            timing_str = f"{key};dur={round(duration, ndigits=2)}"
            # +2 for ", " separator, except for first item
            new_length = current_length + len(timing_str) + (2 if result else 0)

            if new_length > 10000:
                """
                The server timings can grow to arbitrary length - in the case that caused us problems over 33,000 characters
                AWS ALBs have limits on size for both each individual header and for all headers on a request
                If we exceed that limit then the ALB returns a 502 with no other explanation
                leading to confusion and distraction
                So, we limit here to 10k characters to avoid that issue
                The timings header is a debug signal we don't rely on for functionality
                so not receiving all timings is not the worse thing in the world
                """
                capture_exception(
                    Exception(f"Server timing header exceeded 10k limit with {len(timings)} timings"),
                    properties={"generated_so_far": ", ".join(result), "length_of_timings": len(timings)},
                )
                break

            result.append(timing_str)
            current_length = new_length

        return ", ".join(result)
