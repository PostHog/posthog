from typing import Any, Dict, Optional

from posthog.clickhouse.query_tagging import tag_queries
from posthog.client import query_with_columns, sync_execute
from posthog.models.instance_setting import get_instance_setting
from posthog.settings.utils import get_list
from posthog.types import FilterType


# Wrapper around sync_execute, adding query tags for insights performance
def insight_sync_execute(query, args=None, *, query_type: str, filter: Optional["FilterType"] = None, **kwargs):

    kwargs["settings"] = add_team_specific_settings(settings=kwargs.get("settings", {}), filter=filter)

    _tag_query(query, query_type, filter, settings=kwargs["settings"])

    return sync_execute(query, args=args, **kwargs)


def add_team_specific_settings(settings: Dict[str, Any], filter: Optional["FilterType"] = None) -> Dict[str, Any]:
    team_specific_settings = {}
    if filter and filter.team:
        if str(filter.team.pk) in get_list(get_instance_setting("PARALLEL_HASH_ENABLED_TEAMS")):
            team_specific_settings.update({"join_algorithm": "parallel_hash"})

    return {**settings, **team_specific_settings}


# Wrapper around `query_with_columns`
def insight_query_with_columns(
    query,
    args=None,
    *,
    query_type: str,
    filter: Optional["FilterType"] = None,
    **kwargs,
):
    _tag_query(query, query_type, filter)

    return query_with_columns(query, args=args, **kwargs)


def _tag_query(query, query_type, filter: Optional["FilterType"], settings: Optional[Dict[str, Any]]):
    tag_queries(
        query_type=query_type,
        has_joins="JOIN" in query,
        has_json_operations="JSONExtract" in query or "JSONHas" in query,
    )

    if settings is not None:
        tag_queries(join_algorithm=settings.get("join_algorithm", "default"))

    if filter is not None:
        tag_queries(filter=filter.to_dict(), **filter.query_tags())
