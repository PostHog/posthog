from datetime import datetime
from typing import Optional

from posthog.schema import DateRange, IntervalType

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team import Team
from posthog.utils import get_compare_period_dates, relative_date_parse_with_delta_mapping


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
            self._team.timezone_info,
            now=self.now_with_timezone,
        )[1]
        return delta_mapping

    def date_to_delta_mappings(self) -> dict[str, int] | None:
        if self._date_range and self._date_range.date_to:
            delta_mapping = relative_date_parse_with_delta_mapping(
                self._date_range.date_to,
                self._team.timezone_info,
                always_truncate=True,
                now=self.now_with_timezone,
            )[1]
            return delta_mapping
        return None

    def dates(self) -> tuple[datetime, datetime]:
        current_period_date_from = super().date_from()
        current_period_date_to = super().date_to()

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
