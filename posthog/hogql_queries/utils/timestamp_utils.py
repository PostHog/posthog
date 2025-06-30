from datetime import datetime
from django.utils import timezone
from typing import Union

from posthog.hogql import ast
from posthog.hogql.ast import SelectQuery
from posthog.hogql.query import execute_hogql_query
from posthog.models import Team
from posthog.models.event import DEFAULT_EARLIEST_TIME_DELTA
from posthog.schema import DataWarehouseNode, ActionsNode, EventsNode


def _get_data_warehouse_earliest_timestamp_query(node: DataWarehouseNode) -> SelectQuery:
    """
    Get the select query for the earliest timestamp from a DataWarehouseNode.

    :param node: The DataWarehouseNode containing the table name and timestamp field.
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
    timestamp_queries: list[ast.Expr] = [
        _get_data_warehouse_earliest_timestamp_query(series_node)
        for series_node in series
        if isinstance(series_node, DataWarehouseNode)
    ]

    if not timestamp_queries or any(isinstance(series_node, EventsNode | ActionsNode) for series_node in series):
        timestamp_queries.append(_get_events_earliest_timestamp_query())

    query = ast.SelectQuery(
        select=[ast.Call(name="arrayMin", args=[ast.Array(exprs=timestamp_queries)])],
    )

    result = execute_hogql_query(query=query, team=team)
    if result and len(result.results) > 0:
        return result.results[0][0]

    return timezone.now() - DEFAULT_EARLIEST_TIME_DELTA
