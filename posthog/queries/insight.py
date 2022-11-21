from typing import Optional

from posthog.clickhouse.query_tagging import tag_queries
from posthog.client import sync_execute
from posthog.models import Filter


# Wrapper around sync_execute, adding query tags for insights performance
def insight_sync_execute(
    query,
    args=None,
    *,
    query_type: str,
    filters: Filter,
    settings=None,
    client_query_id: Optional[str] = None,
    client_query_team_id: Optional[int] = None,
):
    tag_queries(
        query_type=query_type,
        has_joins="JOIN" in query,
        has_json_operations="JSONExtract" in query or "JSONHas" in query,
        **filters.query_tags(),
    )

    return sync_execute(
        query, args=args, settings=settings, client_query_id=client_query_id, client_query_team_id=client_query_team_id
    )
