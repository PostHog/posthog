import json
import re
import uuid
from typing import Dict

from django.http import JsonResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ParseError, ValidationError, NotAuthenticated
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from sentry_sdk import capture_exception

from posthog import schema
from posthog.api.documentation import extend_schema
from posthog.api.services.query import process_query
from posthog.api.routing import StructuredViewSetMixin
from posthog.clickhouse.client.execute_async import (
    cancel_query,
    enqueue_process_query_task,
    get_query_status,
)
from posthog.clickhouse.query_tagging import tag_queries
from posthog.errors import ExposedCHQueryError
from posthog.hogql.ai import PromptUnclear, write_sql_from_prompt
from posthog.hogql.errors import HogQLException

from posthog.models.user import User
from posthog.permissions import (
    ProjectMembershipNecessaryPermissions,
    TeamMemberAccessPermission,
)
from posthog.rate_limit import (
    AIBurstRateThrottle,
    AISustainedRateThrottle,
    TeamRateThrottle,
)
from posthog.utils import refresh_requested_by_client


class QueryThrottle(TeamRateThrottle):
    scope = "query"
    rate = "120/hour"


class QuerySchemaParser(JSONParser):
    """
    A query schema parser that ensures a valid query is present in the request
    """

    @staticmethod
    def validate_query(data) -> Dict:
        try:
            schema.QuerySchema.model_validate(data)
            # currently we have to return data not the parsed Model
            # because pydantic doesn't know to discriminate on 'kind'
            # if we can get this correctly typed we can return the parsed model
            return data
        except Exception as error:
            raise ParseError(detail=str(error))

    def parse(self, stream, media_type=None, parser_context=None):
        data = super(QuerySchemaParser, self).parse(stream, media_type, parser_context)
        QuerySchemaParser.validate_query(data.get("query"))
        return data


class QueryViewSet(StructuredViewSetMixin, viewsets.ViewSet):
    permission_classes = [
        IsAuthenticated,
        ProjectMembershipNecessaryPermissions,
        TeamMemberAccessPermission,
    ]

    parser_classes = (QuerySchemaParser,)

    def get_throttles(self):
        if self.action == "draft_sql":
            return [AIBurstRateThrottle(), AISustainedRateThrottle()]
        else:
            return [QueryThrottle()]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "query",
                OpenApiTypes.STR,
                description=(
                    "Submit a JSON string representing a query for PostHog data analysis,"
                    " for example a HogQL query.\n\nExample payload:\n"
                    '```\n{"query": {"kind": "HogQLQuery", "query": "select * from events limit 100"}}\n```'
                    "\n\nFor more details on HogQL queries"
                    ", see the [PostHog HogQL documentation](/docs/hogql#api-access). "
                ),
            ),
            OpenApiParameter(
                "client_query_id",
                OpenApiTypes.STR,
                description="Client provided query ID. Can be used to retrieve the status or cancel the query.",
            ),
            OpenApiParameter(
                "async",
                OpenApiTypes.BOOL,
                description=(
                    "(Experimental) "
                    "Whether to run the query asynchronously. Defaults to False."
                    " If True, the `id` of the query can be used to check the status and to cancel it."
                ),
            ),
        ],
        responses={
            200: OpenApiResponse(description="Query results"),
        },
    )
    def create(self, request, *args, **kwargs) -> JsonResponse:
        request_json = request.data
        query_json = request_json.get("query")
        query_async = request_json.get("async", False)
        refresh_requested = refresh_requested_by_client(request)

        client_query_id = request_json.get("client_query_id") or uuid.uuid4().hex
        self._tag_client_query_id(client_query_id)

        if query_async:
            query_status = enqueue_process_query_task(
                team_id=self.team.pk,
                query_json=query_json,
                query_id=client_query_id,
                refresh_requested=refresh_requested,
            )
            return JsonResponse(query_status.model_dump(), safe=False)

        try:
            result = process_query(self.team, query_json, refresh_requested=refresh_requested)
            return JsonResponse(result, safe=False)
        except (HogQLException, ExposedCHQueryError) as e:
            raise ValidationError(str(e), getattr(e, "code_name", None))
        except Exception as e:
            self.handle_column_ch_error(e)
            capture_exception(e)
            raise e

    @extend_schema(
        description="(Experimental)",
        responses={
            200: OpenApiResponse(description="Query status"),
        },
    )
    @extend_schema(
        description="(Experimental)",
        responses={
            200: OpenApiResponse(description="Query status"),
        },
    )
    def retrieve(self, request: Request, pk=None, *args, **kwargs) -> JsonResponse:
        status = get_query_status(team_id=self.team.pk, query_id=pk)
        return JsonResponse(status.__dict__, safe=False)

    @extend_schema(
        description="(Experimental)",
    )
    def destroy(self, request, pk=None, *args, **kwargs):
        cancel_query(self.team.pk, pk)
        return Response(status=204)

    @action(methods=["GET"], detail=False)
    def draft_sql(self, request: Request, *args, **kwargs) -> Response:
        if not isinstance(request.user, User):
            raise NotAuthenticated()
        prompt = request.GET.get("prompt")
        current_query = request.GET.get("current_query")
        if not prompt:
            raise ValidationError({"prompt": ["This field is required."]}, code="required")
        if len(prompt) > 400:
            raise ValidationError({"prompt": ["This field is too long."]}, code="too_long")
        try:
            result = write_sql_from_prompt(prompt, current_query=current_query, user=request.user, team=self.team)
        except PromptUnclear as e:
            raise ValidationError({"prompt": [str(e)]}, code="unclear")
        return Response({"sql": result})

    def handle_column_ch_error(self, error):
        if getattr(error, "message", None):
            match = re.search(r"There's no column.*in table", error.message)
            if match:
                # TODO: remove once we support all column types
                raise ValidationError(
                    match.group(0) + ". Note: While in beta, not all column types may be fully supported"
                )
        return

    def _tag_client_query_id(self, query_id: str | None):
        if query_id is None:
            return

        tag_queries(client_query_id=query_id)

    def _query_json_from_request(self, request):
        if request.method == "POST":
            if request.content_type in ["", "text/plain", "application/json"]:
                query_source = request.body
            else:
                query_source = request.POST.get("query")
        else:
            query_source = request.GET.get("query")

        if query_source is None:
            raise ValidationError("Please provide a query in the request body or as a query parameter.")

        # TODO with improved pydantic validation we don't need the validation here
        try:

            def parsing_error(ex):
                raise ValidationError(ex)

            query = json.loads(
                query_source,
                parse_constant=lambda x: parsing_error(f"Unsupported constant found in JSON: {x}"),
            )
        except (json.JSONDecodeError, UnicodeDecodeError) as error_main:
            raise ValidationError("Invalid JSON: %s" % (str(error_main)))
        return query
