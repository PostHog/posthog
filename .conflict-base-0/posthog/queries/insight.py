from typing import Optional

from rest_framework.exceptions import ValidationError

from posthog.clickhouse.client import query_with_columns, sync_execute
from posthog.clickhouse.query_tagging import tag_queries
from posthog.errors import ExposedCHQueryError
from posthog.types import FilterType


# Wrapper around sync_execute, adding query tags for insights performance
def insight_sync_execute(
    query,
    args=None,
    *,
    team_id: int,
    query_type: str,
    filter: Optional["FilterType"] = None,
    **kwargs,
):
    tag_queries(team_id=team_id)
    _tag_query(query, query_type, filter)
    try:
        return sync_execute(query, args=args, team_id=team_id, **kwargs)
    except ExposedCHQueryError as e:
        raise ValidationError(str(e), e.code_name)


# Wrapper around `query_with_columns`
def insight_query_with_columns(
    query,
    args=None,
    *,
    query_type: str,
    filter: Optional["FilterType"] = None,
    team_id: int,
    **kwargs,
):
    _tag_query(query, query_type, filter)

    return query_with_columns(query, args=args, team_id=team_id, **kwargs)


def _tag_query(query, query_type, filter: Optional["FilterType"]):
    tag_queries(
        query_type=query_type,
        has_joins="JOIN" in query,
        has_json_operations="JSONExtract" in query or "JSONHas" in query,
    )

    if filter is not None:
        tag_queries(filter=filter.to_dict(), **filter.query_tags())
