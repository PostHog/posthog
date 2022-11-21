from typing import TYPE_CHECKING, Optional

from posthog.clickhouse.query_tagging import tag_queries
from posthog.client import sync_execute

if TYPE_CHECKING:
    from posthog.models import Filter

# Wrapper around sync_execute, adding query tags for insights performance
def insight_sync_execute(
    query,
    args=None,
    *,
    query_type: str,
    filter: "Filter" = None,
    settings=None,
    client_query_id: Optional[str] = None,
    client_query_team_id: Optional[int] = None,
):
    tag_queries(
        query_type=query_type,
        has_joins="JOIN" in query,
        has_json_operations="JSONExtract" in query or "JSONHas" in query,
    )

    if filter is not None:
        tag_queries(**filter.query_tags())

    return sync_execute(
        query, args=args, settings=settings, client_query_id=client_query_id, client_query_team_id=client_query_team_id
    )
