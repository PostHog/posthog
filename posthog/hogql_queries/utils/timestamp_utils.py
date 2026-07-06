import contextvars
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager
from datetime import date, datetime, timedelta, tzinfo
from typing import Any, Optional, Union

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from dateutil.parser import parse as parse_datetime
from dateutil.relativedelta import MO, SU, relativedelta

from posthog.schema import (
    ActionsNode,
    DataWarehouseNode,
    EventsNode,
    FunnelsDataWarehouseNode,
    GroupNode,
    LifecycleDataWarehouseNode,
)

from posthog.hogql import ast
from posthog.hogql.ast import SelectQuery
from posthog.hogql.property import action_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, get_query_tags, tags_context
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models import Team, User
from posthog.models.event import DEFAULT_EARLIEST_TIME_DELTA
from posthog.models.team import WeekStartDay
from posthog.utils import get_safe_cache

from products.actions.backend.models.action import Action

EARLIEST_TIMESTAMP_CACHE_TTL = 24 * 60 * 60
EARLIEST_EVENT_TIMESTAMP = datetime.fromisoformat("1980-01-01T00:00:00Z")
# Floor for the team-wide unfiltered earliest timestamp: events before 2015 are treated as corrupt.
UNFILTERED_EARLIEST_TIMESTAMP_FLOOR = datetime.fromisoformat("2015-01-01T00:00:00Z")


def _get_data_warehouse_earliest_timestamp_query(
    node: Union[DataWarehouseNode, FunnelsDataWarehouseNode, LifecycleDataWarehouseNode],
) -> SelectQuery:
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
    team: Team,
    node: Union[
        EventsNode, ActionsNode, DataWarehouseNode, FunnelsDataWarehouseNode, LifecycleDataWarehouseNode, None
    ] = None,
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
    elif isinstance(node, FunnelsDataWarehouseNode):
        return f"earliest_timestamp_funnels_data_warehouse_{team.pk}_{node.table_name}_{node.timestamp_field}"
    elif isinstance(node, LifecycleDataWarehouseNode):
        return f"earliest_timestamp_lifecycle_data_warehouse_{team.pk}_{node.table_name}_{node.timestamp_field}"
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


def _coerce_to_datetime(value: Any, tz: tzinfo) -> datetime:
    """Normalize a min(timestamp) result to a timezone-aware ``datetime``.

    Data warehouse tables may declare their timestamp field as a String or Date
    column, so the query can return a ``str`` or ``date`` instead of a ``datetime``.
    Leaving those unconverted breaks downstream date math (``.strftime()`` and
    ``<`` comparisons), so we resolve them to a concrete ``datetime`` here.

    The result must be timezone-aware: this value becomes the "all time" date_from,
    which is compared against the timezone-aware date_to. A naive datetime would
    raise "can't compare offset-naive and offset-aware datetimes". Naive values
    (e.g. from a ``Date`` column) are interpreted in the team's timezone — the same
    timezone QueryDateRange buckets in — so the lower bound lines up with the day
    boundaries the rest of the range uses, rather than UTC midnight.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=tz)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=tz)
    if isinstance(value, str):
        try:
            parsed = parse_datetime(value)
        except (ValueError, TypeError, OverflowError):
            return EARLIEST_EVENT_TIMESTAMP
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=tz)
    return EARLIEST_EVENT_TIMESTAMP


def _earliest_timestamp_query_tags() -> AbstractContextManager[None]:
    """Ensure the earliest-timestamp resolution query carries product/feature tags.

    Resolving "all time" date_from runs this query while setting up a date range —
    often before the main query runner has tagged its execution context. An untagged
    ClickHouse query raises UntaggedQueryError in local dev. Inherit whatever the
    caller already set and only fill product/feature when missing, so callers like
    marketing analytics keep their own attribution.
    """
    current = get_query_tags()
    overrides: dict[str, Any] = {}
    if current.product is None:
        overrides["product"] = Product.PRODUCT_ANALYTICS
    if current.feature is None:
        overrides["feature"] = Feature.INSIGHT
    return tags_context(**overrides)


def _get_earliest_timestamp_from_node(
    team: Team,
    node: Union[EventsNode, ActionsNode, DataWarehouseNode, FunnelsDataWarehouseNode, LifecycleDataWarehouseNode],
    user: Optional[User] = None,
) -> datetime:
    """
    Get the earliest timestamp from a single series node

    :param team: The team
    :param node: The series node
    :param user: The user the query runs as, for warehouse table access control
    :return: The earliest timestamp as a datetime object.
    """
    # The cache is team-wide (keyed by team + node, not user): the value is table metadata, and row
    # access is still enforced on the insight's main query, so per-user entries aren't worth the misses.
    cache_key = _get_earliest_timestamp_cache_key(team, node)
    cached_result = get_safe_cache(cache_key)
    if cached_result is not None:
        # Coerce on read too: entries cached before the coercion fix shipped hold a raw
        # str/date for up to the TTL window. Passing them through is idempotent for the
        # datetime values written after the fix and repairs the stale ones.
        return _coerce_to_datetime(cached_result, team.timezone_info)

    if (
        isinstance(node, DataWarehouseNode)
        or isinstance(node, FunnelsDataWarehouseNode)
        or isinstance(node, LifecycleDataWarehouseNode)
    ):
        query = _get_data_warehouse_earliest_timestamp_query(node)
    else:
        query = _get_event_earliest_timestamp_query(team, node)

    earliest_timestamp = EARLIEST_EVENT_TIMESTAMP
    with _earliest_timestamp_query_tags():
        result = execute_hogql_query(query=query, team=team, user=user)
    if result and len(result.results) > 0 and len(result.results[0]) > 0 and result.results[0][0] is not None:
        earliest_timestamp = _coerce_to_datetime(result.results[0][0], team.timezone_info)

    cache.set(cache_key, earliest_timestamp, timeout=EARLIEST_TIMESTAMP_CACHE_TTL)
    return earliest_timestamp


def get_earliest_timestamp_from_series(
    team: Team,
    series: Sequence[
        Union[
            EventsNode, ActionsNode, DataWarehouseNode, FunnelsDataWarehouseNode, LifecycleDataWarehouseNode, GroupNode
        ]
    ],
    user: Optional[User] = None,
) -> datetime:
    """
    Get the earliest timestamp for specific events/actions in a series.
    This is used for "All time" date filtering - each event/action is queried
    for its own earliest timestamp, and the minimum is returned.

    :param team: The team
    :param series: A list of series nodes (EventsNode, ActionsNode, DataWarehouseNode, or GroupNode)
    :param user: The user the queries run as, for warehouse table access control
    :return: The earliest timestamp across all series
    """
    # Expand GroupNode nodes into individual nodes
    nodes: list[
        Union[EventsNode, ActionsNode, DataWarehouseNode, FunnelsDataWarehouseNode, LifecycleDataWarehouseNode]
    ] = []
    for node in series:
        if isinstance(node, GroupNode):
            nodes.extend(node.nodes)
        else:
            nodes.append(node)

    timestamps = []
    if len(nodes) == 1 or settings.IN_UNIT_TESTING:
        timestamps = [_get_earliest_timestamp_from_node(team, node, user) for node in nodes]

    else:
        with ThreadPoolExecutor(max_workers=min(len(nodes), 4)) as executor:
            # ThreadPoolExecutor does not inherit contextvars (query tags) by default; copy the
            # current context into each worker so tagged sync_execute calls don't fail untagged.
            futures = [
                executor.submit(contextvars.copy_context().run, _get_earliest_timestamp_from_node, team, node, user)
                for node in nodes
            ]
            timestamps = [future.result() for future in futures]

    return min(timestamps)


def get_earliest_timestamp_unfiltered(team: Team) -> datetime:
    """
    Get the team-wide, unfiltered earliest event timestamp (the earliest event of any kind).

    Used for "all time" date filtering when no specific series is given. Mirrors the value of the
    legacy raw-SQL earliest-timestamp helper: floored at 2015-01-01, falling back to
    now - DEFAULT_EARLIEST_TIME_DELTA when the team has no events.
    """
    cache_key = f"earliest_timestamp_unfiltered_{team.pk}"
    cached_result = get_safe_cache(cache_key)
    if cached_result is not None:
        return _coerce_to_datetime(cached_result, team.timezone_info)

    query = ast.SelectQuery(
        select=[ast.Field(chain=["timestamp"])],
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        where=ast.CompareOperation(
            op=ast.CompareOperationOp.Gt,
            left=ast.Field(chain=["timestamp"]),
            right=ast.Constant(value=UNFILTERED_EARLIEST_TIMESTAMP_FLOOR),
        ),
        order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="ASC")],
        limit=ast.Constant(value=1),
    )

    with _earliest_timestamp_query_tags():
        result = execute_hogql_query(query=query, team=team)
    if result and len(result.results) > 0 and len(result.results[0]) > 0 and result.results[0][0] is not None:
        earliest_timestamp = _coerce_to_datetime(result.results[0][0], team.timezone_info)
        # Only cache real results: a team with no events yet should keep re-checking rather than
        # pinning a "now - delta" fallback for the full TTL.
        cache.set(cache_key, earliest_timestamp, timeout=EARLIEST_TIMESTAMP_CACHE_TTL)
        return earliest_timestamp

    return timezone.now() - DEFAULT_EARLIEST_TIME_DELTA


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
