from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from django.conf import settings
from django.core.cache import cache
from typing import Union

from posthog.hogql import ast
from posthog.hogql.ast import SelectQuery
from posthog.hogql.query import execute_hogql_query
from posthog.models import Team
from posthog.schema import DataWarehouseNode, ActionsNode, EventsNode
from posthog.utils import get_safe_cache

EARLIEST_TIMESTAMP_CACHE_TTL = 24 * 60 * 60


def _get_data_warehouse_earliest_timestamp_query(node: DataWarehouseNode) -> SelectQuery:
    """
    Get the select query for the earliest timestamp from a DataWarehouseNode.

    :param node: The DataWarehouseNode
    :return: A SelectQuery object that retrieves the earliest timestamp from the specified data warehouse table.
    """
    return ast.SelectQuery(
        select=[ast.Call(name="min", args=[ast.Field(chain=[node.timestamp_field])])],
        select_from=ast.JoinExpr(table=ast.Field(chain=[node.table_name])),
    )


def _get_events_earliest_timestamp_query() -> SelectQuery:
    """
    Get the select query for the earliest timestamp from the events table.

    :return: A SelectQuery object that retrieves the earliest timestamp from the events table.
    """
    return ast.SelectQuery(
        select=[ast.Call(name="min", args=[ast.Field(chain=["timestamp"])])],
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
    )


def _get_earliest_timestamp_cache_key(team: Team, node: Union[EventsNode, ActionsNode, DataWarehouseNode]) -> str:
    """
    Generate a cache key for the earliest timestamp
    :param team: The team
    :param node: The series node
    :return: A string representing the cache key.
    """
    if isinstance(node, DataWarehouseNode):
        return f"earliest_timestamp_data_warehouse_{team.pk}_{node.table_name}_{node.timestamp_field}"
    elif isinstance(node, EventsNode) or isinstance(node, ActionsNode):
        return f"earliest_timestamp_events_{team.pk}"
    else:
        raise ValueError(f"Unsupported node type: {type(node)}")


def _get_earliest_timestamp_from_node(team: Team, node: Union[EventsNode, ActionsNode, DataWarehouseNode]) -> datetime:
    """
    Get the earliest timestamp from a single series node

    :param team: The team
    :param node: The series node
    :return: The earliest timestamp as a datetime object.
    """
    cache_key = _get_earliest_timestamp_cache_key(team, node)
    cached_result = get_safe_cache(cache_key)
    if cached_result is not None:
        return cached_result

    if isinstance(node, DataWarehouseNode):
        query = _get_data_warehouse_earliest_timestamp_query(node)
    else:
        query = _get_events_earliest_timestamp_query()

    earliest_timestamp = datetime.fromisoformat("2015-01-01T00:00:00Z")  # Default to a reasonable fallback
    result = execute_hogql_query(query=query, team=team)
    if result and len(result.results) > 0 and len(result.results[0]) > 0:
        earliest_timestamp = result.results[0][0]

    cache.set(cache_key, earliest_timestamp, timeout=EARLIEST_TIMESTAMP_CACHE_TTL)

    return earliest_timestamp


def get_earliest_timestamp_from_series(
    team: Team, series: list[Union[EventsNode, ActionsNode, DataWarehouseNode]]
) -> datetime:
    """
    Get the earliest timestamp from a list of series nodes, which can include DataWarehouseNode, EventsNode, and ActionsNode.
    It defaults to the earliest timestamp from the events table.

    :param team: The team for which to get the earliest timestamp.
    :param series: A list of series nodes which can be EventsNode, ActionsNode, or DataWarehouseNode.
    :return: The earliest timestamp as a datetime object.
    """

    timestamps = []
    if len(series) == 1 or settings.IN_UNIT_TESTING:
        timestamps = [_get_earliest_timestamp_from_node(team, node) for node in series]

    else:
        with ThreadPoolExecutor(max_workers=min(len(series), 4)) as executor:
            futures = [executor.submit(_get_earliest_timestamp_from_node, team, node) for node in series]
            timestamps = [future.result() for future in futures]

    return min(timestamps)
