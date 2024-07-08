from datetime import datetime
from typing import Optional

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team import Team
from posthog.schema import DateRange, IntervalType, InsightDateRange
from posthog.utils import (
    relative_date_parse,
)


class QueryCompareToDateRange(QueryDateRange):
    """Moves the start of a date range back by the compare_to interval and sets the end to have the same delta as the original"""

    _team: Team
    _date_range: Optional[InsightDateRange | DateRange]
    _interval: Optional[IntervalType]
    _now_without_timezone: datetime
    _compare_to: str

    def __init__(
        self,
        date_range: Optional[InsightDateRange | DateRange],
        team: Team,
        interval: Optional[IntervalType],
        now: datetime,
        compare_to: str,
    ) -> None:
        super().__init__(date_range, team, interval, now)
        self.compare_to = compare_to

    def dates(self) -> tuple[datetime, datetime]:
        current_period_date_from = super().date_from()
        current_period_date_to = super().date_to()

        start_date = relative_date_parse(self.compare_to, self._team.timezone_info, now=current_period_date_from)

        return (
            start_date,
            start_date + (current_period_date_to - current_period_date_from),
        )

    def date_to(self) -> datetime:
        previous_period_date_to = self.dates()[1]
        return previous_period_date_to

    def date_from(self) -> datetime:
        previous_period_date_from = self.dates()[0]
        return previous_period_date_from
