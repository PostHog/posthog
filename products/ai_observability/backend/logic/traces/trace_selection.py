import re
import json
import base64
import binascii
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from posthog.schema import (
    AnyPropertyFilterDiscriminated,
    CohortPropertyFilter,
    DataWarehousePersonPropertyFilter,
    DataWarehousePropertyFilter,
    DateRange,
    ElementPropertyFilter,
    EventMetadataPropertyFilter,
    EventPropertyFilter,
    GroupPropertyFilter,
    HogQLPropertyFilter,
    IntervalType,
    PersonPropertyFilter,
    SessionPropertyFilter,
)

from posthog.dataclasses import frozen
from posthog.hogql_queries.ai.utils import HEAVY_PROPERTY_NAMES
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models import Team
from posthog.utils import get_delta_mapping_for, relative_date_parse_with_delta_mapping

QuickFilter = Literal["errors", "feedback"]
QUICK_FILTERS: tuple[QuickFilter, ...] = ("errors", "feedback")

TraceOrder = Literal["newest_first", "oldest_first"]
TRACE_ORDERS: tuple[TraceOrder, ...] = ("newest_first", "oldest_first")

CAPTURE_BUFFER = timedelta(minutes=10)
DEFAULT_WINDOW = timedelta(days=7)
ALL_TIME_LOOKBACK = timedelta(days=365)
MAX_PROPERTY_FILTERS = 50

_TRACE_EVENT_FILTERS = (
    EventPropertyFilter,
    EventMetadataPropertyFilter,
    PersonPropertyFilter,
    SessionPropertyFilter,
    GroupPropertyFilter,
    CohortPropertyFilter,
    ElementPropertyFilter,
)
# A custom expression can name any table, and a warehouse filter reads one, so neither is bounded by the traces' scope.
QUERY_SCOPED_FILTERS = (HogQLPropertyFilter, DataWarehousePropertyFilter, DataWarehousePersonPropertyFilter)
SUPPORTED_FILTERS = (*_TRACE_EVENT_FILTERS, *QUERY_SCOPED_FILTERS)

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_RELATIVE_DATE = re.compile(r"-?(?P<number>\d+)?(?P<kind>[hdwmqysHDWMQY])(?P<position>Start|End)?")
# The date parser snaps these kinds to their Start or End outside the delta it computes.
_KINDS_POSITIONED_OUTSIDE_THE_DELTA = frozenset({"w", "q"})


class InvalidTraceWindowError(ValueError):
    pass


class InvalidTraceCursorError(ValueError):
    pass


class InvalidTraceSelectionError(ValueError):
    pass


def _shift(moment: datetime, delta: timedelta) -> datetime:
    # Python adds a timedelta to the wall-clock time and resets fold, so in a repeated DST hour the result lands an
    # hour off. UTC has no repeated hour. The result goes back to the moment's zone because HogQL prints a bound in the
    # project's zone, and a bound past the last datetime there must fail here, not while the query is built.
    return (moment.astimezone(UTC) + delta).astimezone(moment.tzinfo)


@frozen
class TraceWindow:
    start: datetime
    end: datetime

    def read_bounds(self) -> "TraceWindow":
        return TraceWindow(start=_shift(self.start, -CAPTURE_BUFFER), end=_shift(self.end, CAPTURE_BUFFER))

    def may_read_a_suffix_of(self, first_timestamp: datetime) -> bool:
        """Whether a trace whose earliest event inside the read bounds is at `first_timestamp` may have started before
        those bounds, so a read starting from that timestamp may miss its first events."""
        return first_timestamp.astimezone(UTC) - self.read_bounds().start.astimezone(UTC) < CAPTURE_BUFFER


@frozen
class TraceGroupScope:
    key: str
    type_index: int


@frozen
class TraceSelection:
    window: TraceWindow
    properties: tuple[AnyPropertyFilterDiscriminated, ...] = ()
    filter_test_accounts: bool | None = None
    include_support_traces: bool = False
    search: str | None = None
    person_id: str | None = None
    group: TraceGroupScope | None = None
    quick_filter: QuickFilter | None = None
    session_id: str | None = None
    order: TraceOrder = "newest_first"

    def __post_init__(self) -> None:
        _check_filters(self.properties)
        self._check_session_scope()

    def _check_session_scope(self) -> None:
        if self.session_id is None:
            return
        narrowed_by_list_filters = (
            self.properties
            or self.search
            or self.person_id
            or self.group
            or self.quick_filter
            or self.filter_test_accounts
        )
        if narrowed_by_list_filters:
            raise InvalidTraceSelectionError("A session reads on its own. Remove the list filters.")


@frozen
class TracePosition:
    trace_id: str
    first_timestamp: datetime

    @property
    def sort_key(self) -> int:
        return _microseconds_since_epoch(self.first_timestamp) // 1000


@frozen
class TracePageBounds:
    """Positions strictly after or strictly before, in the selection's order. Both None reads the first page."""

    after: TracePosition | None
    before: TracePosition | None


def filters_test_accounts(team: Team, selection: TraceSelection) -> bool:
    if selection.filter_test_accounts is None:
        return bool(team.test_account_filters_default_checked)
    return selection.filter_test_accounts


def _check_filters(filters: Sequence[AnyPropertyFilterDiscriminated]) -> None:
    if len(filters) > MAX_PROPERTY_FILTERS:
        raise InvalidTraceSelectionError(f"Send at most {MAX_PROPERTY_FILTERS} property filters.")
    for prop in filters:
        if not isinstance(prop, SUPPORTED_FILTERS):
            raise InvalidTraceSelectionError(f"Filters of type {prop.type} don't apply to traces. Remove them.")
        # The key is split into a person table join and a property, and anything else fails deep inside the query build.
        if isinstance(prop, DataWarehousePersonPropertyFilter) and prop.key.count(".") != 1:
            raise InvalidTraceSelectionError(
                "A data warehouse person property filter needs a key of the form table.property, with one dot."
            )
        if isinstance(prop, GroupPropertyFilter) and prop.group_type_index is None:
            raise InvalidTraceSelectionError("A group property filter needs a group type index.")
        # Traces are selected on the shared events table, which ingestion stores without these properties.
        if isinstance(prop, EventPropertyFilter) and prop.key in HEAVY_PROPERTY_NAMES:
            raise InvalidTraceSelectionError(f"Filters on the {prop.key} property don't apply to traces. Remove them.")


class _CalendarDayInclusiveDateRange(QueryDateRange):
    CALENDAR_DAY_DATE_TO_IS_INCLUSIVE = True


def _names_a_date(bound: str) -> bool:
    # QueryDateRange reads any bound its parser cannot place as "now", so only bounds the parser places get through.
    try:
        _, delta_mapping, _ = relative_date_parse_with_delta_mapping(bound, ZoneInfo("UTC"))
    except (ValueError, OverflowError):
        return False
    if delta_mapping is None:
        return True
    relative = _RELATIVE_DATE.fullmatch(bound)
    if relative is None:
        return False
    kind, number, position = relative["kind"], relative["number"], relative["position"]
    return bool(get_delta_mapping_for(kind=kind, number=number, position=position)) or (
        position is not None and kind in _KINDS_POSITIONED_OUTSIDE_THE_DELTA
    )


def resolve_window(team: Team, date_from: str | None, date_to: str | None, now: datetime) -> TraceWindow:
    reaches_back_to_all_time = date_from == "all"
    checked_bounds = (None if reaches_back_to_all_time else date_from, date_to)
    for bound in checked_bounds:
        if bound is not None and not _names_a_date(bound):
            raise InvalidTraceWindowError(f"The date bound {bound!r} could not be parsed")
    date_range = DateRange(
        date_from=None if reaches_back_to_all_time else (date_from or f"-{DEFAULT_WINDOW.days}d"),
        date_to=date_to,
    )
    try:
        parsed = _CalendarDayInclusiveDateRange(date_range, team, IntervalType.MINUTE, now)
        end = parsed.date_to()
        start = end - ALL_TIME_LOOKBACK if reaches_back_to_all_time else parsed.date_from()
        window = TraceWindow(start=start, end=end)
        # A window at the edge of the datetime range overflows here rather than while the query is built.
        window.read_bounds()
    except (ValueError, OverflowError) as error:
        raise InvalidTraceWindowError("The date range is outside the dates that can be read") from error
    if end < start:
        raise InvalidTraceWindowError("The date range ends before it starts")
    return window


def _microseconds_since_epoch(moment: datetime) -> int:
    return (moment.astimezone(UTC) - _EPOCH) // timedelta(microseconds=1)


def encode_cursor(position: TracePosition) -> str:
    payload = json.dumps(
        [_microseconds_since_epoch(position.first_timestamp), position.trace_id], separators=(",", ":")
    )
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> TracePosition:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        microseconds, trace_id = payload
        if type(microseconds) is not int or not isinstance(trace_id, str):
            raise ValueError("Unexpected cursor contents")
        return TracePosition(trace_id=trace_id, first_timestamp=_EPOCH + timedelta(microseconds=microseconds))
    except (ValueError, TypeError, binascii.Error, OverflowError) as error:
        raise InvalidTraceCursorError("The cursor is not valid") from error
