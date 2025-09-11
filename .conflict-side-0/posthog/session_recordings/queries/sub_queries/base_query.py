from datetime import datetime

from posthog.schema import DateRange, RecordingsQuery

from posthog.hogql import ast

from posthog.constants import PropertyOperatorType
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models import Team
from posthog.session_recordings.queries.session_replay_events import ttl_days
from posthog.utils import relative_date_parse


class SessionRecordingsQueryDateRange(QueryDateRange):
    """Custom QueryDateRange that only applies start/end of day logic when dates don't specify time components."""

    def _has_time_component(self, date_str: str) -> bool:
        return "T" in date_str or " " in date_str or ":" in date_str

    def _is_relative_date(self, date_str: str) -> bool:
        return date_str.startswith("-") or date_str.startswith("+")

    def date_from(self) -> datetime:
        if self._date_range and self._date_range.date_from:
            if self._is_relative_date(self._date_range.date_from):
                return super().date_from()
            if not self._has_time_component(
                self._date_range.date_from
            ):  # date_from that is only a date is treated as implicitly the start of the day
                parsed = relative_date_parse(
                    self._date_range.date_from,
                    self._timezone_info,
                    now=self.now_with_timezone,
                    always_truncate=False,
                )
                return parsed.replace(hour=0, minute=0, second=0, microsecond=0)

        return super().date_from()

    def date_to(self) -> datetime:
        if self._date_range and self._date_range.date_to:
            if self._is_relative_date(self._date_range.date_to):
                return super().date_to()

            if not self._has_time_component(
                self._date_range.date_to
            ):  # date_to that is only a date is treated as implicitly the end of the day
                parsed = relative_date_parse(
                    self._date_range.date_to,
                    self._timezone_info,
                    now=self.now_with_timezone,
                    always_truncate=False,
                )
                return parsed.replace(hour=23, minute=59, second=59, microsecond=999999)

        return super().date_to()


class SessionRecordingsListingBaseQuery:
    _team: Team
    _query: RecordingsQuery

    def __init__(self, team: Team, query: RecordingsQuery):
        self._team = team
        self._query = query

    @property
    def ttl_days(self):
        return ttl_days(self._team)

    @property
    def property_operand(self):
        return PropertyOperatorType.AND if self._query.operand == "AND" else PropertyOperatorType.OR

    def wrapped_with_query_operand(self, exprs: list[ast.Expr]) -> ast.Expr:
        return ast.And(exprs=exprs) if self.property_operand == "AND" else ast.Or(exprs=exprs)

    @property
    def query_date_range(self):
        return SessionRecordingsQueryDateRange(
            date_range=DateRange(date_from=self._query.date_from, date_to=self._query.date_to, explicitDate=True),
            team=self._team,
            interval=None,
            now=datetime.now(),
        )
