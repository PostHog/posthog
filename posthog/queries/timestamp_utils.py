from datetime import datetime
from typing import Union, Optional

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.models import Team
from posthog.queries.util import get_earliest_timestamp
from posthog.schema import DataWarehouseNode, ActionsNode, EventsNode


def _get_earliest_timestamp_from_data_warehouse(team: Team, node: DataWarehouseNode) -> Optional[datetime]:
    """
    Get the earliest timestamp from a DataWarehouseNode.

    :param team: The team for which to get the earliest timestamp.
    :param node: The DataWarehouseNode containing the table name and timestamp field.
    :return: The earliest timestamp as a datetime object, or None if no results are found.
    """
    ts_field = ast.Field(chain=[node.timestamp_field])
    query = ast.SelectQuery(
        select=[ts_field],
        distinct=True,
        select_from=ast.JoinExpr(table=ast.Field(chain=[node.table_name])),
        order_by=[ast.OrderExpr(expr=ts_field, order="ASC")],
        limit=ast.Constant(value=1),
    )

    result = execute_hogql_query(query=query, team=team)
    if result and len(result.results) > 0:
        return result.results[0][0]

    return None


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
    earliest_timestamps = [
        _get_earliest_timestamp_from_data_warehouse(team=team, node=series_node)
        for series_node in series
        if isinstance(series_node, DataWarehouseNode)
    ]

    has_other_nodes = any(isinstance(series_node, EventsNode | ActionsNode) for series_node in series)
    if has_other_nodes:
        earliest_timestamps.append(get_earliest_timestamp(team_id=team.pk))

    # keep non-null timestamps only
    earliest_timestamps = [ts for ts in earliest_timestamps if ts is not None]

    if earliest_timestamps:
        return min(earliest_timestamps)

    # default to the earliest timestamp from the events table
    return get_earliest_timestamp(team_id=team.pk)
