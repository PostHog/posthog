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
from posthog.hogql.modifiers import create_default_modifiers_for_team

from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import Team
from posthog.models.user import User
from posthog.permissions import (
    ProjectMembershipNecessaryPermissions,
    TeamMemberAccessPermission,
)
from posthog.queries.time_to_see_data.serializers import (
    SessionEventsQuerySerializer,
    SessionsQuerySerializer,
)
from posthog.queries.time_to_see_data.sessions import get_session_events, get_sessions
from posthog.rate_limit import (
    AIBurstRateThrottle,
    AISustainedRateThrottle,
    TeamRateThrottle,
)
from posthog.schema import HogQLMetadata
from posthog.utils import refresh_requested_by_client


class RequestParser(JSONParser):
    """
    A query schema parser that ensures a valid query is present in the request
    """

    @staticmethod
    def validate_query(data) -> Dict:
        try:
            schema.WebAnalyticsHealthRequest.model_validate(data)
            # currently we have to return data not the parsed Model
            # because pydantic doesn't know to discriminate on 'kind'
            # if we can get this correctly typed we can return the parsed model
            return data
        except Exception as error:
            raise ParseError(detail=str(error))

    def parse(self, stream, media_type=None, parser_context=None):
        data = super(RequestParser, self).parse(stream, media_type, parser_context)
        RequestParser.validate_query(data)
        return data


class WebAnalyticsHealthViewSet(StructuredViewSetMixin, viewsets.ViewSet):
    permission_classes = [
        IsAuthenticated,
        ProjectMembershipNecessaryPermissions,
        TeamMemberAccessPermission,
    ]

    parser_classes = (RequestParser,)

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
    def post(self, request, *args, **kwargs):
        request_json = request.data
        query_json = request_json.get("query")
        # allow lists as well as dicts in response with safe=False
        try:
            return JsonResponse({}, safe=False)
        except HogQLException as e:
            raise ValidationError(str(e))
        except ExposedCHQueryError as e:
            raise ValidationError(str(e), e.code_name)
        except Exception as e:
            capture_exception(e)
            raise e


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
