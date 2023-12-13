import structlog
from typing import Any, Dict, List, Optional, cast

from pydantic import BaseModel
from rest_framework.exceptions import ValidationError

from posthog.clickhouse.query_tagging import tag_queries
from posthog.hogql.constants import LimitContext
from posthog.hogql.database.database import create_hogql_database, serialize_database
from posthog.hogql.metadata import get_hogql_metadata
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import Team
from posthog.queries.time_to_see_data.serializers import SessionEventsQuerySerializer, SessionsQuerySerializer
from posthog.queries.time_to_see_data.sessions import get_session_events, get_sessions
from posthog.schema import HogQLMetadata

logger = structlog.get_logger(__name__)

QUERY_WITH_RUNNER = [
    "LifecycleQuery",
    "RetentionQuery",
    "TrendsQuery",
    "WebOverviewQuery",
    "WebTopSourcesQuery",
    "WebTopClicksQuery",
    "WebTopPagesQuery",
    "WebStatsTableQuery",
]
QUERY_WITH_RUNNER_NO_CACHE = [
    "HogQLQuery",
    "EventsQuery",
    "PersonsQuery",
    "SessionsTimelineQuery",
]


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
    team: Team,
    query_json: Dict,
    limit_context: Optional[LimitContext] = None,
    refresh_requested: Optional[bool] = False,
) -> Dict:
    # query_json has been parsed by QuerySchemaParser
    # it _should_ be impossible to end up in here with a "bad" query
    query_kind = query_json.get("kind")
    tag_queries(query=query_json)

    if query_kind in QUERY_WITH_RUNNER:
        query_runner = get_query_runner(query_json, team, limit_context=limit_context)
        return _unwrap_pydantic_dict(query_runner.run(refresh_requested=refresh_requested))
    elif query_kind in QUERY_WITH_RUNNER_NO_CACHE:
        query_runner = get_query_runner(query_json, team, limit_context=limit_context)
        return _unwrap_pydantic_dict(query_runner.calculate())
    elif query_kind == "HogQLMetadata":
        metadata_query = HogQLMetadata.model_validate(query_json)
        metadata_response = get_hogql_metadata(query=metadata_query, team=team)
        return _unwrap_pydantic_dict(metadata_response)
    elif query_kind == "DatabaseSchemaQuery":
        database = create_hogql_database(team.pk, modifiers=create_default_modifiers_for_team(team))
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
