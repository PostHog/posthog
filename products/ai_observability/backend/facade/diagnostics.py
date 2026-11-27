from collections.abc import Callable, Sequence
from typing import Final

from posthog.models import Team, User
from posthog.paging import Page, PageRequest

from ..logic.diagnostics.entity_keys import (
    MalformedEntityKeyError as MalformedEntityKeyError,
    decode_entity_key,
    encode_entity_key,
)
from ..logic.diagnostics.error_group_queries import (
    ErrorPageRead,
    count_new_errors as count_new_error_rows,
    has_any_error,
    load_error_first_seen as load_error_first_seen_rows,
    load_error_group,
    load_error_page,
)
from ..logic.diagnostics.error_groups import (
    ErrorGroupRow,
    ErrorView as ErrorView,
    first_seen_in_range,
)
from ..logic.diagnostics.group_page_queries import MAX_SORTED_GROUPS
from ..logic.diagnostics.tool_group_queries import (
    ToolPageRead,
    has_any_tool_call,
    load_tool_group,
    load_tool_page,
    load_tool_traces,
)
from ..logic.diagnostics.tool_groups import (
    ToolView as ToolView,
    tool_item,
    trace_share,
)
from ..logic.diagnostics.trends import change_label, error_change_tone, paired_with_range
from ..logic.traces.lookback import has_no_lookback, seen_before
from ..logic.traces.trace_metrics import bucket_size_for, bucket_starts, has_too_many_buckets, zoned_selection
from ..logic.traces.trace_metrics_store import cached_trace_count
from ..logic.traces.trace_selection import (
    InvalidTraceWindowError as InvalidTraceWindowError,
    TraceSelection,
)
from ..logic.traces.trace_selection_queries import load_trace_count
from .contracts import TraceMetricChangeTone
from .diagnostics_contracts import (
    ErrorFirstSeen,
    ErrorFirstSeenList,
    ErrorGroupDetail,
    ErrorListCounts,
    ErrorListItem,
    ErrorNewCount,
    ErrorOrder as ErrorOrder,
    ErrorPage as ErrorPage,
    ErrorTrend,
    ToolGroupDetail,
    ToolListCounts,
    ToolOrder as ToolOrder,
    ToolPage as ToolPage,
    ToolTraceShare,
    ToolTraceShareList,
)

DIAGNOSTICS_PAGE_MAX_LIMIT: Final = 100
DIAGNOSTICS_PAGE_MAX_OFFSET: Final = MAX_SORTED_GROUPS - DIAGNOSTICS_PAGE_MAX_LIMIT
# The errors list asks when each error of a page was first seen, so one request takes a page of keys.
ERROR_FIRST_SEEN_MAX_KEYS: Final = DIAGNOSTICS_PAGE_MAX_LIMIT
TOOL_TRACE_SHARES_MAX_KEYS: Final = DIAGNOSTICS_PAGE_MAX_LIMIT


class DiagnosticsRangeTooLongError(Exception):
    pass


class ErrorNotFoundError(Exception):
    pass


class ErrorFirstSeenTooManyKeysError(ValueError):
    pass


class ToolTraceSharesTooManyKeysError(ValueError):
    pass


class ToolNotFoundError(Exception):
    pass


def load_error_list(
    team: Team,
    user: User | None,
    selection: TraceSelection,
    *,
    search: str | None,
    view: ErrorView | None,
    order: ErrorOrder | None,
    page: PageRequest,
) -> Callable[[], ErrorPage]:
    """Reads a page of the selection's errors, grouped by normalized message, and returns the step that builds it.
    `search` narrows the errors and the counts, and `view` only the page. Without an `order` the page is sorted by the
    default one, and it says which order it applied. Raises `DiagnosticsRangeTooLongError` and
    `InvalidTraceWindowError` for a range it cannot read.

    On an empty first page, a second read checks for any error since the lookback start, so the client can tell a quiet
    range from a project that sends no errors. The step runs no ClickHouse query."""
    zoned = _readable(team, selection)
    read = load_error_page(team, user, zoned, search=search, view=view, order=order, page=page)
    nothing_captured = page.offset == 0 and read.counts.total == 0 and not has_any_error(team, user, zoned)
    return lambda: _to_error_page(read, nothing_captured)


def get_error(team: Team, user: User | None, selection: TraceSelection, key: str) -> Callable[[], ErrorGroupDetail]:
    """Reads the error `key` names over the selection, with its series over the previous period, and returns the step
    that builds it. Raises `MalformedEntityKeyError` for a key that names no message, `ErrorNotFoundError` when the
    message has no occurrence in the selection, and the range errors of `load_error_list`."""
    message = decode_entity_key(key)
    zoned = _readable(team, selection)
    detail = load_error_group(team, user, zoned, message)
    if detail is None:
        raise ErrorNotFoundError(key)
    starts = bucket_starts(zoned.window, bucket_size_for(zoned.window))
    return lambda: ErrorGroupDetail(
        item=_to_list_item(detail.row),
        bucket_starts=starts,
        previous_series=list(paired_with_range(detail.previous_series, len(starts))),
    )


def load_error_first_seen(
    team: Team, user: User | None, selection: TraceSelection, keys: Sequence[str]
) -> ErrorFirstSeenList:
    """When each error first occurred, checked from the lookback start to the range end, one entry per distinct key in
    request order. Raises `ErrorFirstSeenTooManyKeysError` past `ERROR_FIRST_SEEN_MAX_KEYS` keys,
    `MalformedEntityKeyError` for a key that names no message, and the range errors of `load_error_list`."""
    requested = list(dict.fromkeys(keys))
    if len(requested) > ERROR_FIRST_SEEN_MAX_KEYS:
        raise ErrorFirstSeenTooManyKeysError(f"Send at most {ERROR_FIRST_SEEN_MAX_KEYS} keys.")
    messages = {key: decode_entity_key(key) for key in requested}
    zoned = _readable(team, selection)
    earliest = load_error_first_seen_rows(team, user, zoned, list(messages.values()))
    return ErrorFirstSeenList(
        items=[
            ErrorFirstSeen(
                key=key,
                first_seen=earliest.get(message),
                is_new=first_seen_in_range(earliest.get(message), zoned.window.start),
            )
            for key, message in messages.items()
        ],
        checked_from=seen_before(zoned.window).date(),
    )


def count_new_errors(team: Team, user: User | None, selection: TraceSelection, *, search: str | None) -> ErrorNewCount:
    """How many of the selection's errors, narrowed by `search`, are new to the range. Raises as `load_error_list`."""
    zoned = _readable(team, selection)
    return ErrorNewCount(count=count_new_error_rows(team, user, zoned, search=search))


def load_tool_list(
    team: Team,
    user: User | None,
    selection: TraceSelection,
    *,
    search: str | None,
    view: ToolView | None,
    order: ToolOrder | None,
    page: PageRequest,
) -> Callable[[], ToolPage]:
    """Reads a page of the tools the selection's generations call, and returns the step that builds it. `search`
    narrows the tools and the counts, and `view` only the page. Without an `order` the page is sorted by the default
    one, and it says which order it applied. Raises the range errors of `load_error_list`.

    On an empty first page, a second read checks for any tool call since the lookback start, so the client can tell a
    quiet range from a project that sends no tool calls. The step runs no ClickHouse query."""
    zoned = _readable(team, selection)
    read = load_tool_page(team, user, zoned, search=search, view=view, order=order, page=page)
    nothing_captured = page.offset == 0 and read.counts.total == 0 and not has_any_tool_call(team, user, zoned)
    return lambda: _to_tool_page(read, nothing_captured)


def get_tool(team: Team, user: User | None, selection: TraceSelection, key: str) -> Callable[[], ToolGroupDetail]:
    """Reads the tool `key` names over the selection, with its series over the previous period, and returns the step
    that builds it. Raises `MalformedEntityKeyError` for a key that names no tool, `ToolNotFoundError` when no
    generation in the selection calls the tool, and the range errors of `load_error_list`."""
    name = decode_entity_key(key)
    zoned = _readable(team, selection)
    detail = load_tool_group(team, user, zoned, name)
    if detail is None:
        raise ToolNotFoundError(key)
    starts = bucket_starts(zoned.window, bucket_size_for(zoned.window))
    return lambda: ToolGroupDetail(
        item=tool_item(detail.row),
        bucket_starts=starts,
        previous_series=list(paired_with_range(detail.previous_series, len(starts))),
    )


def _readable(team: Team, selection: TraceSelection) -> TraceSelection:
    # Buckets start at midnight in the project's zone, so every step works on the window in that zone.
    zoned = zoned_selection(selection, team.timezone_info)
    if has_too_many_buckets(zoned.window, bucket_size_for(zoned.window)):
        raise DiagnosticsRangeTooLongError()
    if has_no_lookback(zoned.window):
        raise InvalidTraceWindowError("The date range is outside the dates that can be read")
    return zoned


def load_tool_trace_shares(
    team: Team, user: User | None, selection: TraceSelection, keys: Sequence[str]
) -> ToolTraceShareList:
    """The share of the traces list's traces that call each tool, one entry per distinct key in request order. Both
    counts hold a trace by the events the traces list keeps. The range's trace count comes through a short cache, so
    it can be as old as the cache allows. Raises `ToolTraceSharesTooManyKeysError` past `TOOL_TRACE_SHARES_MAX_KEYS`
    keys, `MalformedEntityKeyError`, and the range errors of `load_error_list`."""
    requested = list(dict.fromkeys(keys))
    if len(requested) > TOOL_TRACE_SHARES_MAX_KEYS:
        raise ToolTraceSharesTooManyKeysError(f"Send at most {TOOL_TRACE_SHARES_MAX_KEYS} keys.")
    names = {key: decode_entity_key(key) for key in requested}
    zoned = _readable(team, selection)
    total_traces = _range_traces(team, user, zoned)
    traces = load_tool_traces(team, user, zoned, list(names.values()))
    return ToolTraceShareList(
        items=[
            ToolTraceShare(key=key, trace_share=trace_share(traces.get(name, 0), total_traces))
            for key, name in names.items()
        ]
    )


def _range_traces(team: Team, user: User | None, zoned: TraceSelection) -> int:
    if user is None:
        return load_trace_count(team, None, zoned)
    return cached_trace_count(team, user, zoned, bucket_size_for(zoned.window))


def _to_error_page(read: ErrorPageRead, nothing_captured: bool) -> ErrorPage:
    return ErrorPage(
        page=Page(results=[_to_list_item(row) for row in read.rows], count=read.count),
        counts=ErrorListCounts(
            total=read.counts.total,
            increasing=read.counts.increasing,
            decreasing=read.counts.decreasing,
            max_occurrences=read.counts.max_occurrences,
        ),
        bucket_starts=list(read.bucket_starts),
        nothing_captured=nothing_captured,
        order=read.order,
    )


def _to_list_item(row: ErrorGroupRow) -> ErrorListItem:
    return ErrorListItem(
        key=encode_entity_key(row.message),
        message=row.message,
        occurrences=row.occurrences,
        change_label=change_label(row.occurrences, row.previous_occurrences),
        change_tone=TraceMetricChangeTone(error_change_tone(row.trend).value),
        trend=ErrorTrend(row.trend.value),
        traces=row.traces,
        users=row.users,
        models=list(row.models),
        last_seen=row.last_seen,
        series=list(row.series),
    )


def _to_tool_page(read: ToolPageRead, nothing_captured: bool) -> ToolPage:
    return ToolPage(
        page=Page(results=[tool_item(row) for row in read.rows], count=read.count),
        counts=ToolListCounts(total=read.counts.total, failing=read.counts.failing, max_calls=read.counts.max_calls),
        bucket_starts=list(read.bucket_starts),
        nothing_captured=nothing_captured,
        order=read.order,
    )
