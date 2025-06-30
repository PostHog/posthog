from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta, MO, SU
from django.utils import timezone
from typing import Union

from posthog.hogql import ast
from posthog.hogql.ast import SelectQuery
from posthog.hogql.query import execute_hogql_query
from posthog.models import Team
from posthog.models.event import DEFAULT_EARLIEST_TIME_DELTA
from posthog.models.team import WeekStartDay
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
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


def _get_week_boundaries(date: datetime.date, week_start_day: WeekStartDay) -> tuple[datetime.date, datetime.date]:
    """
    Get the start and end dates of the week for a given date, considering the week start day.

    :param date: The date for which to find the week boundaries.
    :param week_start_day: The day that the week starts on (e.g., Sunday or Monday).
    :return: A tuple containing the start and end dates of the week.
    """
    if week_start_day == WeekStartDay.MONDAY:
        week_start = MO
    else:
        week_start = SU

    start_date = date + relativedelta(weekday=week_start(-1))
    end_date = start_date + timedelta(days=6)

    return start_date, end_date


def _format_date_range(start_date: datetime.date, end_date: datetime.date) -> str:
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


def _format_week_label(date: datetime, query_date_range: QueryDateRange, week_start_day: WeekStartDay) -> str:
    """
    Format a date to be used as a label for a week.

    :param date: The date in the week to format.
    :param query_date_range: The query date range containing the date_from and date_to.
    :param week_start_day: The day that the week starts on (e.g., Sunday or Monday).
    :return: A formatted string representing the week label.
    """
    date = date.date() if isinstance(date, datetime) else date
    start_date, end_date = _get_week_boundaries(date, week_start_day)

    # Ensure the start and end dates are within the query date range
    start_date = max(start_date, query_date_range.date_from().date())
    end_date = min(end_date, query_date_range.date_to().date())

    # Ensure the end date is not before the start date
    end_date = max(end_date, start_date)

    return _format_date_range(start_date, end_date)


def format_label_date(date: datetime, query_date_range: QueryDateRange, week_start_day=WeekStartDay.SUNDAY) -> str:
    """
    Format a date to be used as a label.

    :param date: The date to format.
    :param query_date_range: The query date range containing the date_from and date_to.
    :param week_start_day: The day that the week starts on (e.g., Sunday or Monday).
    :return: A formatted string representing the date label.
    """
    interval = query_date_range.interval_name or "default"

    if interval == "week":
        return _format_week_label(date, query_date_range, week_start_day)

    date_formats = {
        "default": "%-d-%b-%Y",
        "minute": "%-d-%b %H:%M",
        "hour": "%-d-%b %H:%M",
        "month": "%b %Y",
    }
    labels_format = date_formats.get(interval, date_formats["default"])

    return date.strftime(labels_format)
