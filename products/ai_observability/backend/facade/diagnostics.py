from collections.abc import Callable
from typing import Final

from posthog.models import Team, User
from posthog.paging import Page, PageRequest

from ..logic.diagnostics.entity_keys import (
    MalformedEntityKeyError as MalformedEntityKeyError,
    decode_entity_key,
    encode_entity_key,
)
from ..logic.diagnostics.error_group_queries import ErrorPageRead, has_any_error, load_error_group, load_error_page
from ..logic.diagnostics.error_groups import (
    ErrorGroupRow,
    ErrorView as ErrorView,
)
from ..logic.diagnostics.group_page_queries import MAX_SORTED_GROUPS
from ..logic.diagnostics.trends import change_label, error_change_tone, paired_with_range
from ..logic.traces.lookback import has_no_lookback
from ..logic.traces.trace_metrics import bucket_size_for, bucket_starts, has_too_many_buckets, zoned_selection
from ..logic.traces.trace_selection import (
    InvalidTraceWindowError as InvalidTraceWindowError,
    TraceSelection,
)
from .contracts import TraceMetricChangeTone
from .diagnostics_contracts import (
    ErrorGroupDetail,
    ErrorListCounts,
    ErrorListItem,
    ErrorOrder as ErrorOrder,
    ErrorPage as ErrorPage,
    ErrorTrend,
)

DIAGNOSTICS_PAGE_MAX_LIMIT: Final = 100
DIAGNOSTICS_PAGE_MAX_OFFSET: Final = MAX_SORTED_GROUPS - DIAGNOSTICS_PAGE_MAX_LIMIT


class DiagnosticsRangeTooLongError(Exception):
    pass


class ErrorNotFoundError(Exception):
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


def _readable(team: Team, selection: TraceSelection) -> TraceSelection:
    # Buckets start at midnight in the project's zone, so every step works on the window in that zone.
    zoned = zoned_selection(selection, team.timezone_info)
    if has_too_many_buckets(zoned.window, bucket_size_for(zoned.window)):
        raise DiagnosticsRangeTooLongError()
    if has_no_lookback(zoned.window):
        raise InvalidTraceWindowError("The date range is outside the dates that can be read")
    return zoned


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
