import json
import re
from typing import Dict, Optional, cast, Any, List

from django.http import HttpResponse, JsonResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from pydantic import BaseModel
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
from posthog.api.routing import StructuredViewSetMixin
from posthog.clickhouse.query_tagging import tag_queries
from posthog.errors import ExposedCHQueryError
from posthog.hogql.ai import PromptUnclear, write_sql_from_prompt
from posthog.hogql.database.database import create_hogql_database, serialize_database
from posthog.hogql.errors import HogQLException
from posthog.hogql.metadata import get_hogql_metadata
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.lifecycle_query_runner import LifecycleQueryRunner
from posthog.hogql_queries.trends_query_runner import TrendsQueryRunner
from posthog.models import Team
from posthog.models.event.events_query import run_events_query
from posthog.models.user import User
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.queries.time_to_see_data.serializers import SessionEventsQuerySerializer, SessionsQuerySerializer
from posthog.queries.time_to_see_data.sessions import get_session_events, get_sessions
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle, TeamRateThrottle
from posthog.schema import EventsQuery, HogQLQuery, HogQLMetadata
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
            schema.Model.model_validate(data)
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
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]

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
                description="Query node JSON string",
            ),
            OpenApiParameter(
                "client_query_id",
                OpenApiTypes.STR,
                description="Client provided query ID. Can be used to cancel queries.",
            ),
        ]
    )
    def list(self, request: Request, **kw) -> HttpResponse:
        self._tag_client_query_id(request.GET.get("client_query_id"))
        query_json = QuerySchemaParser.validate_query(self._query_json_from_request(request))
        # allow lists as well as dicts in response with safe=False
        try:
            return JsonResponse(process_query(self.team, query_json, request=request), safe=False)
        except HogQLException as e:
            raise ValidationError(str(e))
        except ExposedCHQueryError as e:
            raise ValidationError(str(e), e.code_name)

    def post(self, request, *args, **kwargs):
        request_json = request.data
        query_json = request_json.get("query")
        self._tag_client_query_id(request_json.get("client_query_id"))
        # allow lists as well as dicts in response with safe=False
        try:
            return JsonResponse(process_query(self.team, query_json, request=request), safe=False)
        except HogQLException as e:
            raise ValidationError(str(e))
        except ExposedCHQueryError as e:
            raise ValidationError(str(e), e.code_name)
        except Exception as e:
            self.handle_column_ch_error(e)
            capture_exception(e)
            raise e

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
        if query_id is not None:
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
                query_source, parse_constant=lambda x: parsing_error(f"Unsupported constant found in JSON: {x}")
            )
        except (json.JSONDecodeError, UnicodeDecodeError) as error_main:
            raise ValidationError("Invalid JSON: %s" % (str(error_main)))
        return query


def _unwrap_pydantic(response: Any) -> Dict | List:
    if isinstance(response, list):
        return [_unwrap_pydantic(item) for item in response]

    elif isinstance(response, BaseModel):
        resp1: Dict[str, Any] = {}
        for key in response.__fields__.keys():
            resp1[key] = _unwrap_pydantic(getattr(response, key))
        return resp1

    elif isinstance(response, dict):
        resp2: Dict[str, Any] = {}
        for key in response.keys():
            resp2[key] = _unwrap_pydantic(response.get(key))
        return resp2

    return response


def _unwrap_pydantic_dict(response: Any) -> Dict:
    return cast(dict, _unwrap_pydantic(response))


def process_query(
    team: Team, query_json: Dict, default_limit: Optional[int] = None, request: Optional[Request] = None
) -> Dict:
    # query_json has been parsed by QuerySchemaParser
    # it _should_ be impossible to end up in here with a "bad" query
    query_kind = query_json.get("kind")

    tag_queries(query=query_json)

    if query_kind == "EventsQuery":
        events_query = EventsQuery.model_validate(query_json)
        events_response = run_events_query(query=events_query, team=team, default_limit=default_limit)
        return _unwrap_pydantic_dict(events_response)
    elif query_kind == "HogQLQuery":
        hogql_query = HogQLQuery.model_validate(query_json)
        hogql_response = execute_hogql_query(
            query_type="HogQLQuery",
            query=hogql_query.query,
            team=team,
            filters=hogql_query.filters,
            default_limit=default_limit,
        )
        return _unwrap_pydantic_dict(hogql_response)
    elif query_kind == "HogQLMetadata":
        metadata_query = HogQLMetadata.model_validate(query_json)
        metadata_response = get_hogql_metadata(query=metadata_query, team=team)
        return _unwrap_pydantic_dict(metadata_response)
    elif query_kind == "LifecycleQuery":
        refresh_requested = refresh_requested_by_client(request) if request else False
        lifecycle_query_runner = LifecycleQueryRunner(query_json, team)
        return _unwrap_pydantic_dict(lifecycle_query_runner.run(refresh_requested=refresh_requested))
    elif query_kind == "TrendsQuery":
        refresh_requested = refresh_requested_by_client(request) if request else False
        trends_query_runner = TrendsQueryRunner(query_json, team)
        return _unwrap_pydantic_dict(trends_query_runner.run(refresh_requested=refresh_requested))
    elif query_kind == "DatabaseSchemaQuery":
        database = create_hogql_database(team.pk)
        return serialize_database(database)
    elif query_kind == "TimeToSeeDataSessionsQuery":
        sessions_query_serializer = SessionsQuerySerializer(data=query_json)
        sessions_query_serializer.is_valid(raise_exception=True)
        return {"results": get_sessions(sessions_query_serializer).data}
    elif query_kind == "TimeToSeeDataQuery":
        serializer = SessionEventsQuerySerializer(
            data={
                "team_id": team.pk,
                "session_start": query_json["sessionStart"],
                "session_end": query_json["sessionEnd"],
                "session_id": query_json["sessionId"],
            }
        )
        serializer.is_valid(raise_exception=True)
        return get_session_events(serializer) or {}
    else:
        if query_json.get("source"):
            return process_query(team, query_json["source"])

        raise ValidationError(f"Unsupported query kind: {query_kind}")
