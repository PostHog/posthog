from datetime import datetime, timedelta
from typing import Optional

from dateutil.relativedelta import relativedelta

from posthog.schema import DateRange, IntervalType

from posthog.hogql_queries.utils.query_date_range import DateRangeBounds, QueryDateRange
from posthog.models.team import Team
from posthog.utils import get_compare_period_dates, relative_date_parse_with_delta_mapping

# Calendar-anchored ranges that run to now ("This week/month/quarter/year"). Their previous period
# is the full prior calendar unit, so the length is a calendar delta rather than a fixed span of
# days — months, quarters and years vary in length, so sizing by elapsed days can't express them.
_FULL_PREVIOUS_CALENDAR_UNITS = {
    "wStart": {"weeks": 1},
    "mStart": {"months": 1},
    "qStart": {"months": 3},
    "yStart": {"years": 1},
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
        if self._date_range and self._date_range.date_from == "all":
            # "All time" resolves to the earliest event rather than a relative offset, so there is no
            # delta to report. Reporting a 7-day one triggers the "-7d is really 8 days" correction in
            # get_compare_period_dates, which shifts the whole previous period a day later.
            return None

        if self._date_range and isinstance(self._date_range.date_from, str):
            date_from = self._date_range.date_from
        else:
            # No date_from means the default range, which is DEFAULT_DATE_FROM_DAYS long.
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

    def full_previous_calendar_period(self, current_period_date_from: datetime) -> Optional[DateRangeBounds]:
        """The full prior calendar unit for a "This week/month/quarter/year" range that runs to now.

        A partial current period (e.g. this month so far) is then charted against the complete
        previous one, matching how hour/minute day-anchored ranges already behave. The end is the
        moment before the current period starts and the start is one calendar unit before that, so
        months, quarters and years come back whole regardless of their varying lengths.
        """
        if not self._date_range or self._date_range.date_to:
            return None
        unit = _FULL_PREVIOUS_CALENDAR_UNITS.get(self._date_range.date_from) if self._date_range.date_from else None
        if unit is None:
            return None
        return DateRangeBounds(
            date_from=current_period_date_from - relativedelta(**unit),  # type: ignore[arg-type]
            date_to=current_period_date_from - timedelta(microseconds=1),
        )

    def dates(self) -> DateRangeBounds:
        current_period_date_from = super().date_from()
        current_period_date_to = super().date_to()

        full_previous = self.full_previous_calendar_period(current_period_date_from)
        if full_previous is not None:
            return full_previous

        if self._date_range and self._date_range.date_from == "all":
            # "All time" starts at the earliest event, whose time of day is arbitrary, while
            # get_compare_period_dates ends the previous period at date_to's time of day. Those two
            # land on the same calendar day here, so the generic path leaves the rest of the first
            # day inside both periods. Size the previous period directly instead, ending it just
            # before the first event.
            previous_period_date_to = current_period_date_from - timedelta(microseconds=1)
            return DateRangeBounds(
                date_from=previous_period_date_to - (current_period_date_to - current_period_date_from),
                date_to=previous_period_date_to,
            )

        previous_period_date_from, previous_period_date_to = get_compare_period_dates(
            current_period_date_from,
            self.nominal_comparison_date_to(current_period_date_to),
            self.date_from_delta_mappings(),
            self.date_to_delta_mappings(),
            self.interval_name,
            exclude_incomplete_periods=bool(self._date_range and self._date_range.excludeIncompletePeriods),
        )

        return DateRangeBounds(date_from=previous_period_date_from, date_to=previous_period_date_to)

    def date_to(self) -> datetime:
        return self.dates().date_to

    def date_from(self) -> datetime:
        return self.dates().date_from
