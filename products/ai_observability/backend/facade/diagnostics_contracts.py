from datetime import date, datetime

from pydantic import Field

from posthog.dataclasses import frozen
from posthog.enums import LabeledStrEnum
from posthog.paging import Page

from ..logic.traces.lookback import LOOKBACK
from .contracts import Contract, TraceMetricChangeTone

_BUCKET_STARTS_DESCRIPTION = "The start of each hour or day of the date range in the project's time zone, oldest first."
_NEXT_DESCRIPTION = "The URL of the next page, or null on the last one."
_PREVIOUS_DESCRIPTION = "The URL of the previous page, or null on the first one."


class ErrorOrder(LabeledStrEnum):
    OCCURRENCES = "occurrences"
    CHANGE = "change"
    TRACES = "traces"
    USERS = "users"
    LAST_SEEN = "last_seen", "Last seen"


class ErrorTrend(LabeledStrEnum):
    INCREASING = "increasing"
    DECREASING = "decreasing"
    STEADY = "steady"


class ErrorListItem(Contract):
    key: str = Field(description="The error's id, to read it on its own or ask when it was first seen.")
    message: str = Field(description="The normalized error message every occurrence in the group shares.")
    occurrences: int = Field(description="How many events raised the error in the date range.")
    change_label: str | None = Field(
        description="How far occurrences moved from the period of the same length before the date range, such as "
        "`+40%` or `was 0`. Null when the range has no previous period."
    )
    change_tone: TraceMetricChangeTone = Field(
        description="`bad` when the error is increasing, `good` when it is decreasing, `neutral` otherwise."
    )
    trend: ErrorTrend = Field(
        description="`increasing` or `decreasing` when occurrences moved past the trend thresholds against the "
        "previous period, `steady` otherwise."
    )
    traces: int = Field(description="How many traces raised the error in the date range.")
    users: int = Field(description="How many identified users raised the error in the date range.")
    models: list[str] = Field(description="Up to three models that raised the error most often.")
    last_seen: datetime = Field(description="The latest occurrence in the date range.")
    series: list[int] = Field(description="The occurrences in each bucket of `bucketStarts`.")


class ErrorListCounts(Contract):
    total: int = Field(description="How many errors the selection holds, ignoring the view.")
    increasing: int = Field(description="How many of them are increasing.")
    decreasing: int = Field(description="How many of them are decreasing.")
    max_occurrences: int = Field(
        description="The most occurrences of any one error in the selection, ignoring the view, so every page can "
        "scale its rows against the same largest error. 0 when the selection holds none."
    )


class ErrorList(Contract):
    count: int = Field(description="How many errors the view holds.")
    next: str | None = Field(description=_NEXT_DESCRIPTION)
    previous: str | None = Field(description=_PREVIOUS_DESCRIPTION)
    results: list[ErrorListItem] = Field(description="A page of errors.")
    counts: ErrorListCounts = Field(
        description="How many errors the selection holds, and how many of them are increasing or decreasing."
    )
    bucket_starts: list[datetime] = Field(description=_BUCKET_STARTS_DESCRIPTION)
    nothing_captured: bool = Field(
        description="Whether the project captured no error from 30 days before the date range to its end. Sent on "
        "the first page only, and false on the others."
    )
    order: ErrorOrder = Field(
        description="The order the errors are sorted by: the one the request asked for, or occurrences when it "
        "asked for none."
    )


@frozen
class ErrorPage:
    page: Page[ErrorListItem]
    counts: ErrorListCounts
    bucket_starts: list[datetime]
    nothing_captured: bool
    order: ErrorOrder


class ErrorGroupDetail(Contract):
    item: ErrorListItem = Field(description="The error as the errors list shows it.")
    bucket_starts: list[datetime] = Field(description=_BUCKET_STARTS_DESCRIPTION)
    previous_series: list[int] = Field(
        description="The occurrences in each bucket of the period of the same length before the date range, one per "
        "bucket of `bucketStarts` in the same position. When the period's bounds give it a bucket more, its last bucket "
        "is left out. Empty when the range has no previous period."
    )


class ErrorFirstSeen(Contract):
    key: str = Field(description="The error's id, as requested.")
    first_seen: datetime | None = Field(
        description="The time of the error's earliest occurrence from the checked date to the end of the range, "
        "whatever day it falls on. Null when it has none there."
    )
    is_new: bool = Field(
        description=f"Whether the error is new to the range: it occurred in the range and not in the {LOOKBACK.days} "
        "days before it."
    )


class ErrorFirstSeenList(Contract):
    items: list[ErrorFirstSeen] = Field(
        description="One item per requested key, once each, in the order first requested."
    )
    checked_from: date = Field(
        description=f"The lookback bound: the date {LOOKBACK.days} days before the range starts. Nothing before it was "
        "read, so an error first seen on it may have occurred earlier."
    )


class ErrorNewCount(Contract):
    count: int = Field(
        description=f"How many errors of the selection are new to the range: they occurred in the range and not in "
        f"the {LOOKBACK.days} days before it."
    )


class ToolOrder(LabeledStrEnum):
    CALLS = "calls"
    CHANGE = "change"
    TRACES = "traces"
    FAILURE_RATE = "failure_rate", "Failure rate"
    LAST_SEEN = "last_seen", "Last seen"


class ToolFailureState(LabeledStrEnum):
    CAPTURED = "captured"
    NOT_CAPTURED = "not_captured"


class ToolListItem(Contract):
    key: str = Field(description="The tool's id, to read it on its own.")
    name: str = Field(description="The tool's name, as generations call it.")
    calls: int = Field(description="How many times generations called the tool in the date range.")
    change_label: str | None = Field(
        description="How far calls moved from the period of the same length before the date range, such as `+40%` "
        "or `was 0`. Null when the range has no previous period."
    )
    change_tone: TraceMetricChangeTone = Field(description="Always `neutral`, as more calls are neither good nor bad.")
    traces: int = Field(description="How many traces called the tool in the date range.")
    failure_rate: float | None = Field(
        description="The share of the tool's captured results that failed, from 0 to 1. Null when no result of the "
        "tool was captured in the date range."
    )
    failures: int | None = Field(
        description="How many of the tool's captured results failed in the date range. Null when no result of the "
        "tool was captured."
    )
    failure_state: ToolFailureState = Field(
        description="`captured` when results of the tool were captured in the date range, so failures can be "
        "counted, `not_captured` otherwise."
    )
    is_failing: bool = Field(
        description="Whether enough of the tool's captured results failed to pass the failing thresholds."
    )
    only_tool_share: float = Field(
        description="The share of calls made by a generation that called no other tool, from 0 to 1."
    )
    last_seen: datetime = Field(description="The latest call in the date range.")
    series: list[int] = Field(description="The calls in each bucket of `bucketStarts`.")


class ToolListCounts(Contract):
    total: int = Field(description="How many tools the selection holds, ignoring the view.")
    failing: int = Field(description="How many of them are failing.")
    max_calls: int = Field(
        description="The most calls of any one tool in the selection, ignoring the view, so every page can scale its "
        "rows against the same busiest tool. 0 when the selection holds none."
    )


class ToolList(Contract):
    count: int = Field(description="How many tools the view holds.")
    next: str | None = Field(description=_NEXT_DESCRIPTION)
    previous: str | None = Field(description=_PREVIOUS_DESCRIPTION)
    results: list[ToolListItem] = Field(description="A page of tools.")
    counts: ToolListCounts = Field(description="How many tools the selection holds, and how many of them are failing.")
    bucket_starts: list[datetime] = Field(description=_BUCKET_STARTS_DESCRIPTION)
    nothing_captured: bool = Field(
        description="Whether no generation called a tool from 30 days before the date range to its end. Sent on the "
        "first page only, and false on the others."
    )
    order: ToolOrder = Field(
        description="The order the tools are sorted by: the one the request asked for, or calls when it asked for none."
    )


@frozen
class ToolPage:
    page: Page[ToolListItem]
    counts: ToolListCounts
    bucket_starts: list[datetime]
    nothing_captured: bool
    order: ToolOrder


class ToolGroupDetail(Contract):
    item: ToolListItem = Field(description="The tool as the tools list shows it.")
    bucket_starts: list[datetime] = Field(description=_BUCKET_STARTS_DESCRIPTION)
    previous_series: list[int] = Field(
        description="The calls in each bucket of the period of the same length before the date range, one per bucket "
        "of `bucketStarts` in the same position. When the period's bounds give it a bucket more, its last bucket is "
        "left out. Empty when the range has no previous period."
    )
