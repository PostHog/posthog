import structlog
from typing import Optional

from pydantic import BaseModel
from rest_framework.exceptions import ValidationError

from posthog.clickhouse.query_tagging import tag_queries
from posthog.hogql.constants import LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import create_hogql_database, serialize_database
from posthog.hogql.autocomplete import get_hogql_autocomplete
from posthog.hogql.metadata import get_hogql_metadata
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql_queries.query_runner import CacheMissResponse, ExecutionMode, get_query_runner
from posthog.models import Team
from posthog.queries.time_to_see_data.serializers import SessionEventsQuerySerializer, SessionsQuerySerializer
from posthog.queries.time_to_see_data.sessions import get_session_events, get_sessions
from posthog.schema import (
    DashboardFilter,
    HogQLAutocomplete,
    HogQLMetadata,
    QuerySchemaRoot,
    DatabaseSchemaQuery,
    TimeToSeeDataSessionsQuery,
    TimeToSeeDataQuery,
)

logger = structlog.get_logger(__name__)


def process_query(
    team: Team,
    query_json: dict,
    *,
    dashboard_filters_json: Optional[dict] = None,
    limit_context: Optional[LimitContext] = None,
    execution_mode: ExecutionMode = ExecutionMode.RECENT_CACHE_CALCULATE_IF_STALE,
) -> dict:
    model = QuerySchemaRoot.model_validate(query_json)
    tag_queries(query=query_json)
    dashboard_filters = DashboardFilter.model_validate(dashboard_filters_json) if dashboard_filters_json else None
    return process_query_model(
        team,
        model.root,
        dashboard_filters=dashboard_filters,
        limit_context=limit_context,
        execution_mode=execution_mode,
    )


def process_query_model(
    team: Team,
    query: BaseModel,  # mypy has problems with unions and isinstance
    *,
    dashboard_filters: Optional[DashboardFilter] = None,
    limit_context: Optional[LimitContext] = None,
    execution_mode: ExecutionMode = ExecutionMode.RECENT_CACHE_CALCULATE_IF_STALE,
) -> dict:
    result: dict | BaseModel

    try:
        query_runner = get_query_runner(query, team, limit_context=limit_context)
    except ValueError:  # This query doesn't run via query runner
        if hasattr(query, "source") and isinstance(query.source, BaseModel):
            result = process_query_model(team, query.source, execution_mode=execution_mode)
        elif execution_mode == ExecutionMode.CACHE_ONLY_NEVER_CALCULATE:
            # Caching is handled by query runners, so in this case we can only return a cache miss
            result = CacheMissResponse(cache_key=None)
        elif isinstance(query, HogQLAutocomplete):
            result = get_hogql_autocomplete(query=query, team=team)
        elif isinstance(query, HogQLMetadata):
            metadata_query = HogQLMetadata.model_validate(query)
            metadata_response = get_hogql_metadata(query=metadata_query, team=team)
            result = metadata_response
        elif isinstance(query, DatabaseSchemaQuery):
            database = create_hogql_database(team.pk, modifiers=create_default_modifiers_for_team(team))
            context = HogQLContext(team_id=team.pk, team=team, database=database)
            result = serialize_database(context)
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
        else:
            raise ValidationError(f"Unsupported query kind: {query.__class__.__name__}")
    else:  # Query runner available - it will handle execution as well as caching
        if dashboard_filters:
            query_runner.apply_dashboard_filters(dashboard_filters)
        result = query_runner.run(execution_mode=execution_mode)

    if isinstance(result, BaseModel):
        return result.model_dump()
    return result
