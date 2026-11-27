from datetime import datetime

from pydantic import Field

from posthog.dataclasses import frozen
from posthog.enums import LabeledStrEnum
from posthog.paging import Page

from .contracts import Contract, TraceMetricChangeTone


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
    next: str | None = Field(description="The URL of the next page, or null on the last one.")
    previous: str | None = Field(description="The URL of the previous page, or null on the first one.")
    results: list[ErrorListItem] = Field(description="A page of errors.")
    counts: ErrorListCounts = Field(
        description="How many errors the selection holds, and how many of them are increasing or decreasing."
    )
    bucket_starts: list[datetime] = Field(
        description="The start of each hour or day of the date range in the project's time zone, oldest first."
    )
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
    bucket_starts: list[datetime] = Field(
        description="The start of each hour or day of the date range in the project's time zone, oldest first."
    )
    previous_series: list[int] = Field(
        description="The occurrences in each bucket of the period of the same length before the date range, one per "
        "bucket of `bucketStarts` in the same position. When the period's bounds give it a bucket more, its last bucket "
        "is left out. Empty when the range has no previous period."
    )
