from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from typing import Union

from django.conf import settings
from django.core.cache import cache

from dateutil.relativedelta import MO, SU, relativedelta

from posthog.schema import ActionsNode, DataWarehouseNode, EventsNode

from posthog.hogql import ast
from posthog.hogql.ast import SelectQuery
from posthog.hogql.property import action_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models import Team
from posthog.models.action.action import Action
from posthog.models.team import WeekStartDay
from posthog.utils import get_safe_cache

EARLIEST_TIMESTAMP_CACHE_TTL = 24 * 60 * 60
EARLIEST_EVENT_TIMESTAMP = datetime.fromisoformat("1980-01-01T00:00:00Z")


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


def _get_event_earliest_timestamp_query(team: Team, node: Union[EventsNode, ActionsNode]) -> SelectQuery:
    """
    Get the select query for the earliest timestamp for a specific event or action.
    This is used for "All time" date filtering.

    :param team: The team
    :param node: The EventsNode or ActionsNode to filter by
            - EventsNode with event="pageview": earliest timestamp for $pageview events after 1980
            - EventsNode with event=None: earliest timestamp across ANY event after 1980
            - ActionsNode: earliest timestamp matching the action's criteria after 1980
    :return: A SelectQuery object that retrieves the earliest timestamp for the specific event/action.
    """

    where_exprs: list[ast.Expr] = [
        # Always filter out events before 1980 to exclude corrupted/invalid timestamps
        ast.CompareOperation(
            op=ast.CompareOperationOp.Gt,
            left=ast.Field(chain=["timestamp"]),
            right=ast.Constant(value=EARLIEST_EVENT_TIMESTAMP),
        )
    ]

    if isinstance(node, ActionsNode):
        action = Action.objects.get(pk=node.id, team=team)
        where_exprs.append(action_to_expr(action))
    elif isinstance(node, EventsNode) and node.event is not None:
        where_exprs.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["event"]),
                right=ast.Constant(value=node.event),
            )
        )

    return ast.SelectQuery(
        select=[ast.Field(chain=["timestamp"])],
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        where=ast.And(exprs=where_exprs),
        order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="ASC")],
        limit=ast.Constant(value=1),
    )


def _get_earliest_timestamp_cache_key(
    team: Team, node: Union[EventsNode, ActionsNode, DataWarehouseNode, None] = None
) -> str:
    """
    Generate a cache key for the earliest timestamp
    :param team: The team
    :param node: The series node (optional). If None, returns team-level global cache key.
    :return: A string representing the cache key.
    """
    if node is None:
        # Global team-level earliest timestamp (for "all time" date filter)
        # Use the same cache key as EventsNode(event=None) since they return the same result
        return f"earliest_timestamp_event_{team.pk}"
    elif isinstance(node, DataWarehouseNode):
        return f"earliest_timestamp_data_warehouse_{team.pk}_{node.table_name}_{node.timestamp_field}"
    elif isinstance(node, ActionsNode):
        return f"earliest_timestamp_action_{team.pk}_{node.id}"
    elif isinstance(node, EventsNode):
        # node.event can be None, meaning "any event" (no event filter in WHERE clause)
        # This is the same as the global team earliest
        if node.event is not None:
            return f"earliest_timestamp_event_{team.pk}_{node.event}"
        return f"earliest_timestamp_event_{team.pk}"
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
        query = _get_event_earliest_timestamp_query(team, node)

    earliest_timestamp = EARLIEST_EVENT_TIMESTAMP
    result = execute_hogql_query(query=query, team=team)
    if result and len(result.results) > 0 and len(result.results[0]) > 0:
        earliest_timestamp = result.results[0][0]

    cache.set(cache_key, earliest_timestamp, timeout=EARLIEST_TIMESTAMP_CACHE_TTL)
    return earliest_timestamp


def get_earliest_timestamp_from_series(
    team: Team, series: list[Union[EventsNode, ActionsNode, DataWarehouseNode]]
) -> datetime:
    """
    Get the earliest timestamp for specific events/actions in a series.
    This is used for "All time" date filtering - each event/action is queried
    for its own earliest timestamp, and the minimum is returned.

    :param team: The team
    :param series: A list of series nodes (EventsNode, ActionsNode, or DataWarehouseNode)
    :return: The earliest timestamp across all series
    """
    timestamps = []
    if len(series) == 1 or settings.IN_UNIT_TESTING:
        timestamps = [_get_earliest_timestamp_from_node(team, node) for node in series]

    else:
        with ThreadPoolExecutor(max_workers=min(len(series), 4)) as executor:
            futures = [executor.submit(_get_earliest_timestamp_from_node, team, node) for node in series]
            timestamps = [future.result() for future in futures]

    return min(timestamps)


def _get_week_boundaries(input_date: date, week_start_day: WeekStartDay) -> tuple[date, date]:
    """
    Get the start and end dates of the week for a given date, considering the week start day.

    :param input_date: The date for which to find the week boundaries.
    :param week_start_day: The day that the week starts on (e.g., Sunday or Monday).
    :return: A tuple containing the start and end dates of the week.
    """
    if week_start_day == WeekStartDay.MONDAY:
        week_start = MO
    else:
        week_start = SU

    start_date = input_date + relativedelta(weekday=week_start(-1))
    end_date = start_date + timedelta(days=6)

    return start_date, end_date


def _format_date_range(start_date: date, end_date: date) -> str:
    """
    Format the date range based on the start and end dates, considering the query date range.

    :param start_date: The start date of the range.
    :param end_date: The end date of the range.
    :return: A formatted string representing the date range.
    """
    if start_date == end_date:
        return start_date.strftime("%-d-%b-%Y")

    if start_date.year != end_date.year:
        return f"{start_date.strftime('%-d-%b-%Y')} – {end_date.strftime('%-d-%b-%Y')}"
    if start_date.month != end_date.month:
        return f"{start_date.strftime('%-d-%b')} – {end_date.strftime('%-d-%b')}"

    return f"{start_date.strftime('%-d')}–{end_date.strftime('%-d %b')}"


def _format_week_label(input_date: date, query_date_range: QueryDateRange, week_start_day: WeekStartDay) -> str:
    """
    Format a date to be used as a label for a week.

    :param input_date: The date in the week to format.
    :param query_date_range: The query date range containing the date_from and date_to.
    :param week_start_day: The day that the week starts on (e.g., Sunday or Monday).
    :return: A formatted string representing the week label.
    """
    start_date, end_date = _get_week_boundaries(input_date, week_start_day)

    # Ensure the start and end dates are within the query date range
    start_date = max(start_date, query_date_range.date_from().date())
    end_date = min(end_date, query_date_range.date_to().date())

    # Ensure the end date is not before the start date
    end_date = max(end_date, start_date)

    return _format_date_range(start_date, end_date)


def format_label_date(
    input_date: datetime, query_date_range: QueryDateRange, week_start_day=WeekStartDay.SUNDAY
) -> str:
    """
    Format a date to be used as a label.

    :param input_date: The date to format.
    :param query_date_range: The query date range containing the date_from and date_to.
    :param week_start_day: The day that the week starts on (e.g., Sunday or Monday).
    :return: A formatted string representing the date label.
    """
    interval = query_date_range.interval_name

    if interval == "week":
        return _format_week_label(
            input_date.date() if isinstance(input_date, datetime) else input_date, query_date_range, week_start_day
        )

    date_formats = {
        "day": "%-d-%b-%Y",
        "minute": "%-d-%b %H:%M",
        "hour": "%-d-%b %H:%M",
        "month": "%b %Y",
    }
    labels_format = date_formats.get(interval, date_formats["day"])

    return input_date.strftime(labels_format)
