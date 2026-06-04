from datetime import datetime
from typing import Optional

from dateutil.relativedelta import relativedelta

from posthog.schema import DateRange, IntervalType

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team import Team
from posthog.utils import get_compare_period_dates, relative_date_parse_with_delta_mapping

# Calendar-relative "to date" presets describe a partial, ongoing period. Comparing them to the
# "previous period" should align to the same window one calendar unit earlier (this month
# June 1–3 → May 1–3), not shift back by the partial window length. Maps each preset's `date_from`
# token to the shift that anchors that window.
_TO_DATE_PRESET_SHIFTS: dict[str, relativedelta] = {
    "dStart": relativedelta(days=1),  # Today
    "wStart": relativedelta(weeks=1),  # This week
    "mStart": relativedelta(months=1),  # This month
    "yStart": relativedelta(years=1),  # Year to date
}


# Originally similar to posthog/queries/query_date_range.py but rewritten to be used in HogQL queries
class QueryPreviousPeriodDateRange(QueryDateRange):
    """Translation of the raw `date_from` and `date_to` filter values to datetimes."""

    _team: Team
    _date_range: Optional[DateRange]
    _interval: Optional[IntervalType]
    _now_without_timezone: datetime

    def __init__(
        self,
        date_range: Optional[DateRange],
        team: Team,
        interval: Optional[IntervalType],
        now: datetime,
        **kwargs,
    ) -> None:
        super().__init__(date_range, team, interval, now, **kwargs)

    def date_from_delta_mappings(self) -> dict[str, int] | None:
        if self._date_range and isinstance(self._date_range.date_from, str) and self._date_range.date_from != "all":
            date_from = self._date_range.date_from
        else:
            date_from = "-7d"

        delta_mapping = relative_date_parse_with_delta_mapping(
            date_from,
            self._timezone_info,
            now=self.now_with_timezone,
        )[1]
        return delta_mapping

    def date_to_delta_mappings(self) -> dict[str, int] | None:
        if self._date_range and self._date_range.date_to:
            delta_mapping = relative_date_parse_with_delta_mapping(
                self._date_range.date_to,
                self._timezone_info,
                always_truncate=True,
                now=self.now_with_timezone,
            )[1]
            return delta_mapping
        return None

    def to_date_preset_shift(self) -> relativedelta | None:
        if not self._date_range or not isinstance(self._date_range.date_from, str) or self._date_range.date_to:
            return None
        return _TO_DATE_PRESET_SHIFTS.get(self._date_range.date_from)

    def dates(self) -> tuple[datetime, datetime]:
        current_period_date_from = super().date_from()
        current_period_date_to = super().date_to()

        # For "to date" presets, align to the same window one calendar unit earlier instead of
        # shifting back by the (partial) window length.
        shift = self.to_date_preset_shift()
        if shift is not None:
            previous_period_date_from = current_period_date_from - shift
            return (
                previous_period_date_from,
                previous_period_date_from + (current_period_date_to - current_period_date_from),
            )

        previous_period_date_from, previous_period_date_to = get_compare_period_dates(
            current_period_date_from,
            current_period_date_to,
            self.date_from_delta_mappings(),
            self.date_to_delta_mappings(),
            self.interval_name,
        )

        return previous_period_date_from, previous_period_date_to

    def date_to(self) -> datetime:
        previous_period_date_to = self.dates()[1]
        return previous_period_date_to

    def date_from(self) -> datetime:
        previous_period_date_from = self.dates()[0]
        return previous_period_date_from
