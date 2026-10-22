"""How wide each bounded window of an incremental build is, and whether a team builds in windows at all."""

import dataclasses
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from typing import Any, Generic, Optional, TypeVar

import structlog

from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.ph_client import feature_enabled_or_false

LOGGER = structlog.get_logger(__name__)

WINDOWED_MATERIALIZATION_FLAG = "data-modeling-windowed-materialization"

TEMPORAL_INITIAL_SPAN = timedelta(days=1)
DATETIME_MINIMUM_SPAN = timedelta(minutes=1)
DATE_MINIMUM_SPAN = timedelta(days=1)
INTEGER_INITIAL_SPLITS = 16
INTEGER_MINIMUM_SPAN = 1
MAXIMUM_SPAN_MULTIPLE = 32
FAST_WINDOW = timedelta(seconds=60)
LOWER_BOUND_SEARCH_DOUBLINGS = 16

Size = TypeVar("Size", timedelta, int)


@frozen
class WindowSpan(Generic[Size]):
    size: Size
    minimum: Size
    maximum: Size

    def halved(self) -> Optional["WindowSpan[Size]"]:
        if self.size <= self.minimum:
            return None
        return dataclasses.replace(self, size=max(self.size // 2, self.minimum))

    def grown(self) -> "WindowSpan[Size]":
        return dataclasses.replace(self, size=min(self.size * 2, self.maximum))


def initial_span(key_min: Any, key_max: Any) -> Optional[WindowSpan[Any]]:
    if isinstance(key_min, datetime):
        return _temporal_span(DATETIME_MINIMUM_SPAN)
    if isinstance(key_min, date):
        return _temporal_span(DATE_MINIMUM_SPAN)
    if _is_integer(key_min) and _is_integer(key_max):
        return integer_span(max(-(-(key_max - key_min) // INTEGER_INITIAL_SPLITS), INTEGER_MINIMUM_SPAN))
    return None


def integer_span(initial_size: int) -> WindowSpan[int]:
    return WindowSpan(size=initial_size, minimum=INTEGER_MINIMUM_SPAN, maximum=initial_size * MAXIMUM_SPAN_MULTIPLE)


def temporal_span_for(key: Any) -> Optional[WindowSpan[timedelta]]:
    if isinstance(key, datetime):
        return _temporal_span(DATETIME_MINIMUM_SPAN)
    if isinstance(key, date):
        return _temporal_span(DATE_MINIMUM_SPAN)
    return None


def fits_in_one_window(start: Any, end: Any, span: WindowSpan[Any]) -> bool:
    return start + span.size >= end


async def search_lower_bound(has_rows_below: Callable[[Any], Awaitable[bool]], end: Any) -> Optional[Any]:
    offset = TEMPORAL_INITIAL_SPAN
    for _ in range(LOWER_BOUND_SEARCH_DOUBLINGS + 1):
        bound = end - offset
        if not await has_rows_below(bound):
            return bound
        offset *= 2
    return None


async def skip_empty_ranges(
    has_rows_between: Callable[[Any, Any], Awaitable[bool]], start: Any, step: Any, end: Any
) -> Any:
    while start + step < end and not await has_rows_between(start, start + step):
        start = start + step
        step = step * 2
    return start


def windowed_materialization_enabled(team_id: int) -> bool:
    try:
        team = Team.objects.only("organization_id").get(id=team_id)
        return feature_enabled_or_false(
            WINDOWED_MATERIALIZATION_FLAG,
            str(team_id),
            groups={"organization": str(team.organization_id), "project": str(team_id)},
            group_properties={
                "organization": {"id": str(team.organization_id)},
                "project": {"id": str(team_id)},
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    except Exception:
        LOGGER.warning("Failed to evaluate windowed materialization flag; building in one query", team_id=team_id)
        return False


def _temporal_span(minimum: timedelta) -> WindowSpan[timedelta]:
    return WindowSpan(
        size=TEMPORAL_INITIAL_SPAN,
        minimum=minimum,
        maximum=TEMPORAL_INITIAL_SPAN * MAXIMUM_SPAN_MULTIPLE,
    )


def _is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
