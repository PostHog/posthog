import datetime
from datetime import timedelta
from typing import TypeVar
from zoneinfo import ZoneInfo

import structlog
from dateutil.relativedelta import relativedelta

from posthog.constants import NON_TIME_SERIES_DISPLAY_TYPES, UNIQUE_GROUPS
from posthog.models.entity import Entity
from posthog.models.filters import Filter
from posthog.models.filters.properties_timeline_filter import PropertiesTimelineFilter
from posthog.models.team import Team

logger = structlog.get_logger(__name__)

PROPERTY_MATH_FUNCTIONS = {
    "sum": "sum",
    "avg": "avg",
    "min": "min",
    "max": "max",
    "median": "quantile(0.50)",
    "p75": "quantile(0.75)",
    "p90": "quantile(0.90)",
    "p95": "quantile(0.95)",
    "p99": "quantile(0.99)",
}

COUNT_PER_ACTOR_MATH_FUNCTIONS = {
    "avg_count_per_actor": "avg",
    "min_count_per_actor": "min",
    "max_count_per_actor": "max",
    "median_count_per_actor": "quantile(0.50)",
    "p75_count_per_actor": "quantile(0.75)",
    "p90_count_per_actor": "quantile(0.90)",
    "p95_count_per_actor": "quantile(0.95)",
    "p99_count_per_actor": "quantile(0.99)",
}

ALL_SUPPORTED_MATH_FUNCTIONS = [
    *list(PROPERTY_MATH_FUNCTIONS.keys()),
    *list(COUNT_PER_ACTOR_MATH_FUNCTIONS.keys()),
]


def is_series_group_based(entity: Entity) -> bool:
    return entity.math == UNIQUE_GROUPS or (
        entity.math in COUNT_PER_ACTOR_MATH_FUNCTIONS and entity.math_group_type_index is not None
    )


F = TypeVar("F", Filter, PropertiesTimelineFilter)


def offset_time_series_date_by_interval(date: datetime.datetime, *, filter: F, team: Team) -> datetime.datetime:
    """If the insight is time-series, offset date according to the interval of the filter."""
    if filter.display in NON_TIME_SERIES_DISPLAY_TYPES:
        return date
    if filter.interval == "month":
        date = (date + relativedelta(months=1) - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    elif filter.interval == "week":
        date = (date + timedelta(weeks=1) - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    elif filter.interval == "hour":
        date = date + timedelta(hours=1)
    else:  # "day" is the default interval
        date = date.replace(hour=23, minute=59, second=59, microsecond=999999)
    if date.tzinfo is None:
        date = date.replace(tzinfo=ZoneInfo(team.timezone))
    return date
