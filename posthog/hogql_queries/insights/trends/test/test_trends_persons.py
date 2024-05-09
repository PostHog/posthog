from typing import Any, Optional, Union, cast

from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
from posthog.models import Team
from posthog.schema import ActorsQuery, Compare, InsightActorsQuery, TrendsQuery


def get_actors(
    filters: dict[str, Any],
    team: Team,
    breakdown: Optional[Union[str, int]] = None,
    compare: Optional[Compare] = None,
    day: Optional[Union[str, int]] = None,
    interval: Optional[int] = None,
    series: Optional[int] = None,
    status: Optional[str] = None,
    offset: Optional[int] = None,
    includeRecordings: Optional[bool] = None,
):
    trends_query = cast(TrendsQuery, filter_to_query(filters))
    insight_actors_query = InsightActorsQuery(
        source=trends_query,
        breakdown=breakdown,
        compare=compare,
        day=day,
        interval=interval,
        series=series,
        status=status,
        includeRecordings=includeRecordings,
    )
    actors_query = ActorsQuery(
        source=insight_actors_query,
        offset=offset,
        select=[
            "id",
            "actor",
            "created_at",
            "event_count",
            *(["matched_recordings"] if includeRecordings else []),
        ],
        orderBy=["event_count DESC"],
    )
    response = ActorsQueryRunner(query=actors_query, team=team).calculate()
    return response.results
