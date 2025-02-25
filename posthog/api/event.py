import json
import urllib
from datetime import datetime
from typing import Any, List, Optional, Union  # noqa: UP035
from posthog.hogql.query import execute_hogql_query
from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP
from posthog.hogql import ast
from django.utils import timezone
from posthog.utils import relative_date_parse

from django.db.models.query import Prefetch
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from rest_framework import mixins, request, response, serializers, viewsets
from posthog.api.utils import action
from rest_framework.exceptions import NotFound
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.settings import api_settings
from rest_framework_csv import renderers as csvrenderers
from posthog.exceptions_capture import capture_exception

from posthog.api.documentation import PropertiesSerializer, extend_schema
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.client import query_with_columns
from posthog.hogql.constants import DEFAULT_RETURNED_ROWS, MAX_SELECT_RETURNED_ROWS
from posthog.models import Element, Filter, Person
from posthog.models.event.query_event_list import query_events_list
from posthog.models.event.sql import SELECT_ONE_EVENT_SQL
from posthog.models.event.util import ClickhouseEventSerializer
from posthog.models.person.util import get_persons_by_distinct_ids
from posthog.models.team import Team
from posthog.models.utils import UUIDT
from posthog.rate_limit import (
    ClickHouseBurstRateThrottle,
    ClickHouseSustainedRateThrottle,
)
from posthog.utils import convert_property_value, flatten
from posthog.hogql.property_utils import create_property_conditions

QUERY_DEFAULT_EXPORT_LIMIT = 3_500


class ElementSerializer(serializers.ModelSerializer):
    event = serializers.CharField()

    class Meta:
        model = Element
        fields = [
            "event",
            "text",
            "tag_name",
            "attr_class",
            "href",
            "attr_id",
            "nth_child",
            "nth_of_type",
            "attributes",
            "order",
        ]


class UncountedLimitOffsetPagination(LimitOffsetPagination):
    """
    the events api works with the default LimitOffsetPagination, but the
    results don't have a count, so we need to override the pagination class
    to remove the count from the response schema
    """

    def get_paginated_response_schema(self, schema):
        return {
            "type": "object",
            "properties": {
                "next": {
                    "type": "string",
                    "nullable": True,
                    "format": "uri",
                    "example": "http://api.example.org/accounts/?{offset_param}=400&{limit_param}=100".format(
                        offset_param=self.offset_query_param, limit_param=self.limit_query_param
                    ),
                },
                "results": schema,
            },
        }


class EventViewSet(
    TeamAndOrgViewSetMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "query"
    renderer_classes = (*tuple(api_settings.DEFAULT_RENDERER_CLASSES), csvrenderers.PaginatedCSVRenderer)
    serializer_class = ClickhouseEventSerializer
    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]
    pagination_class = UncountedLimitOffsetPagination

    def _build_next_url(
        self,
        request: request.Request,
        last_event_timestamp: datetime,
        order_by: list[str],
    ) -> str:
        params = request.GET.dict()
        reverse = "-timestamp" in order_by
        timestamp = last_event_timestamp.astimezone().isoformat()
        if reverse:
            params["before"] = timestamp
        else:
            params["after"] = timestamp
        return request.build_absolute_uri(f"{request.path}?{urllib.parse.urlencode(params)}")

    @extend_schema(
        description="""
        This endpoint allows you to list and filter events.
        It is effectively deprecated and is kept only for backwards compatibility.
        If you ever ask about it you will be advised to not use it...
        If you want to ad-hoc list or aggregate events, use the Query endpoint instead.
        If you want to export all events or many pages of events you should use our CDP/Batch Exports products instead.
        """,
        parameters=[
            OpenApiParameter(
                "event",
                OpenApiTypes.STR,
                description="Filter list by event. For example `user sign up` or `$pageview`.",
            ),
            OpenApiParameter(
                "select",
                OpenApiTypes.STR,
                description="(Experimental) JSON-serialized array of HogQL expressions to return",
                many=True,
            ),
            OpenApiParameter(
                "where",
                OpenApiTypes.STR,
                description="(Experimental) JSON-serialized array of HogQL expressions that must pass",
                many=True,
            ),
            OpenApiParameter("person_id", OpenApiTypes.INT, description="Filter list by person id."),
            OpenApiParameter(
                "distinct_id",
                OpenApiTypes.INT,
                description="Filter list by distinct id.",
            ),
            OpenApiParameter(
                "before",
                OpenApiTypes.DATETIME,
                description="Only return events with a timestamp before this time.",
            ),
            OpenApiParameter(
                "after",
                OpenApiTypes.DATETIME,
                description="Only return events with a timestamp after this time.",
            ),
            OpenApiParameter(
                "limit",
                OpenApiTypes.INT,
                description="The maximum number of results to return",
            ),
            PropertiesSerializer(required=False),
        ],
    )
    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        try:
            is_csv_request = self.request.accepted_renderer.format == "csv"

            if self.request.GET.get("limit", None):
                limit = int(self.request.GET.get("limit"))  # type: ignore
            elif is_csv_request:
                limit = QUERY_DEFAULT_EXPORT_LIMIT
            else:
                limit = DEFAULT_RETURNED_ROWS

            limit = min(limit, MAX_SELECT_RETURNED_ROWS)

            try:
                offset = int(request.GET["offset"]) if request.GET.get("offset") else 0
            except ValueError:
                offset = 0

            team = self.team
            filter = Filter(request=request, team=self.team)
            order_by: list[str] = (
                list(json.loads(request.GET["orderBy"])) if request.GET.get("orderBy") else ["-timestamp"]
            )

            query_result = query_events_list(
                filter=filter,
                team=team,
                limit=limit,
                offset=offset,
                request_get_query_dict=request.GET.dict(),
                order_by=order_by,
                action_id=request.GET.get("action_id"),
            )

            # Retry the query without the 1 day optimization
            if len(query_result) < limit:
                query_result = query_events_list(
                    unbounded_date_from=True,  # only this changed from the query above
                    filter=filter,
                    team=team,
                    limit=limit,
                    offset=offset,
                    request_get_query_dict=request.GET.dict(),
                    order_by=order_by,
                    action_id=request.GET.get("action_id"),
                )

            result = ClickhouseEventSerializer(
                query_result[0:limit],
                many=True,
                context={"people": self._get_people(query_result, team)},
            ).data

            next_url: Optional[str] = None
            if not is_csv_request and len(query_result) > limit:
                next_url = self._build_next_url(request, query_result[limit - 1]["timestamp"], order_by)
            return response.Response({"next": next_url, "results": result})

        except Exception as ex:
            capture_exception(ex)
            raise

    def _get_people(self, query_result: List[dict], team: Team) -> dict[str, Any]:  # noqa: UP006
        distinct_ids = [event["distinct_id"] for event in query_result]
        persons = get_persons_by_distinct_ids(team.pk, distinct_ids)
        persons = persons.prefetch_related(Prefetch("persondistinctid_set", to_attr="distinct_ids_cache"))
        distinct_to_person: dict[str, Person] = {}
        for person in persons:
            for distinct_id in person.distinct_ids:
                distinct_to_person[distinct_id] = person
        return distinct_to_person

    def retrieve(
        self,
        request: request.Request,
        pk: Optional[Union[int, str]] = None,
        *args: Any,
        **kwargs: Any,
    ) -> response.Response:
        if not isinstance(pk, str) or not UUIDT.is_valid_uuid(pk):
            return response.Response(
                {
                    "detail": "Invalid UUID",
                    "code": "invalid",
                    "type": "validation_error",
                },
                status=400,
            )
        query_result = query_with_columns(
            SELECT_ONE_EVENT_SQL,
            {"team_id": self.team.pk, "event_id": pk.replace("-", "")},
            team_id=self.team.pk,
        )
        if len(query_result) == 0:
            raise NotFound(detail=f"No events exist for event UUID {pk}")

        query_context = {}
        if request.query_params.get("include_person", False):
            query_context["people"] = self._get_people(query_result, self.team)

        res = ClickhouseEventSerializer(query_result[0], many=False, context=query_context).data
        return response.Response(res)

    @action(methods=["GET"], detail=False, required_scopes=["query:read"])
    def values(self, request: request.Request, **kwargs) -> response.Response:
        team = self.team

        key = request.GET.get("key")
        event_names = request.GET.getlist("event_name", None)

        if key == "custom_event":
            system_events = [
                event_name
                for event_name in CORE_FILTER_DEFINITIONS_BY_GROUP["events"].keys()
                if event_name != "All Events"  # Skip the wildcard
            ]

            query = ast.SelectQuery(
                select=[ast.Field(chain=["event"])],
                distinct=True,
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                where=ast.CompareOperation(
                    op=ast.CompareOperationOp.NotIn,
                    left=ast.Field(chain=["event"]),
                    right=ast.Constant(value=system_events),
                ),
                order_by=[ast.OrderExpr(expr=ast.Field(chain=["event"]), order="ASC")],
            )

            result = execute_hogql_query(query, team=team)
            return response.Response([{"name": event[0]} for event in result.results])
        elif key:
            date_from = relative_date_parse("-7d", team.timezone_info).strftime("%Y-%m-%d 00:00:00")
            date_to = timezone.now().strftime("%Y-%m-%d 23:59:59")

            conditions: list[ast.Expr] = [
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Constant(value=date_from),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Constant(value=date_to),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.NotEq,
                    left=ast.Field(chain=["properties", key]),
                    right=ast.Constant(value=None),
                ),
            ]

            # Handle property filters from query parameters
            for param_key, param_value in request.GET.items():
                if param_key.startswith("properties_"):
                    property_key = param_key.replace("properties_", "", 1)
                    try:
                        # Expect properly encoded JSON from frontend
                        property_values = (
                            json.loads(param_value) if isinstance(param_value, str | bytes | bytearray) else param_value
                        )
                        conditions.append(create_property_conditions(property_key, property_values))
                    except json.JSONDecodeError:
                        # If not JSON, treat as single value
                        conditions.append(create_property_conditions(property_key, param_value))

            if event_names and len(event_names) > 0:
                event_conditions: list[ast.Expr] = [
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["event"]),
                        right=ast.Constant(value=event_name),
                    )
                    for event_name in event_names
                ]
                if len(event_conditions) > 1:
                    conditions.append(ast.Or(exprs=event_conditions))
                else:
                    conditions.append(event_conditions[0])

            if request.GET.get("value"):
                conditions.append(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.ILike,
                        left=ast.Call(name="toString", args=[ast.Field(chain=["properties", key])]),
                        right=ast.Constant(value=f"%{request.GET.get('value')}%"),
                    )
                )

            order_by = []
            if request.GET.get("value"):
                order_by = [
                    ast.OrderExpr(
                        expr=ast.Call(
                            name="length", args=[ast.Call(name="toString", args=[ast.Field(chain=["properties", key])])]
                        ),
                        order="ASC",
                    )
                ]

            query = ast.SelectQuery(
                select=[ast.Field(chain=["properties", key])],
                distinct=True,
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                where=ast.And(exprs=conditions),
                order_by=order_by,
                limit=ast.Constant(value=10),
            )

            result = execute_hogql_query(query, team=team)
            values = []
            for value in result.results:
                try:
                    values.append(json.loads(value[0]))
                except json.JSONDecodeError:
                    values.append(value[0])

        return response.Response([{"name": convert_property_value(value)} for value in flatten(values)])


class LegacyEventViewSet(EventViewSet):
    param_derived_from_user_current_team = "team_id"
