import structlog
from typing import Optional

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
from posthog.schema import (
    FunnelsQuery,
    HogQLMetadata,
    HogQLQuery,
    EventsQuery,
    TrendsQuery,
    RetentionQuery,
    QuerySchemaRoot,
    LifecycleQuery,
    WebOverviewQuery,
    WebTopClicksQuery,
    WebStatsTableQuery,
    ActorsQuery,
    SessionsTimelineQuery,
    DatabaseSchemaQuery,
    TimeToSeeDataSessionsQuery,
    TimeToSeeDataQuery,
    StickinessQuery,
    PathsQuery,
    InsightActorsQueryOptions,
)

logger = structlog.get_logger(__name__)

QUERY_WITH_RUNNER = (
    TrendsQuery
    | FunnelsQuery
    | RetentionQuery
    | PathsQuery
    | StickinessQuery
    | LifecycleQuery
    | WebOverviewQuery
    | WebTopClicksQuery
    | WebStatsTableQuery
)
QUERY_WITH_RUNNER_NO_CACHE = HogQLQuery | EventsQuery | ActorsQuery | SessionsTimelineQuery | InsightActorsQueryOptions


def process_query(
    team: Team,
    query_json: dict,
    limit_context: Optional[LimitContext] = None,
    refresh_requested: Optional[bool] = False,
) -> dict:
    model = QuerySchemaRoot.model_validate(query_json)
    tag_queries(query=query_json)
    return process_query_model(
        team,
        model.root,
        limit_context=limit_context,
        refresh_requested=refresh_requested,
    )


def process_query_model(
    team: Team,
    query: BaseModel,  # mypy has problems with unions and isinstance
    limit_context: Optional[LimitContext] = None,
    refresh_requested: Optional[bool] = False,
) -> dict:
    result: dict | BaseModel

    if isinstance(query, QUERY_WITH_RUNNER):  # type: ignore
        query_runner = get_query_runner(query, team, limit_context=limit_context)
        result = query_runner.run(refresh_requested=refresh_requested)
    elif isinstance(query, QUERY_WITH_RUNNER_NO_CACHE):  # type: ignore
        query_runner = get_query_runner(query, team, limit_context=limit_context)
        result = query_runner.calculate()
    elif isinstance(query, HogQLMetadata):
        metadata_query = HogQLMetadata.model_validate(query)
        metadata_response = get_hogql_metadata(query=metadata_query, team=team)
        result = metadata_response
    elif isinstance(query, DatabaseSchemaQuery):
        database = create_hogql_database(team.pk, modifiers=create_default_modifiers_for_team(team))
        result = serialize_database(database)
    elif isinstance(query, TimeToSeeDataSessionsQuery):
        sessions_query_serializer = SessionsQuerySerializer(data=query)
        sessions_query_serializer.is_valid(raise_exception=True)
        result = {"results": get_sessions(sessions_query_serializer).data}
    elif isinstance(query, TimeToSeeDataQuery):
        serializer = SessionEventsQuerySerializer(
            data={
                "team_id": team.pk,
                "session_start": query.sessionStart,
                "session_end": query.sessionEnd,
                "session_id": query.sessionId,
            }
        )
        serializer.is_valid(raise_exception=True)
        result = get_session_events(serializer) or {}
    elif hasattr(query, "source") and isinstance(query.source, BaseModel):
        result = process_query_model(team, query.source)
    else:
        raise ValidationError(f"Unsupported query kind: {query.__class__.__name__}")

    if isinstance(result, BaseModel):
        return result.model_dump()
    return result
