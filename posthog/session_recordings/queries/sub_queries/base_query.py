from datetime import datetime

from posthog.constants import PropertyOperatorType
from posthog.hogql import ast
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models import Team
from posthog.schema import RecordingsQuery, DateRange
from posthog.session_recordings.queries.session_replay_events import ttl_days
from posthog.utils import relative_date_parse


class SessionRecordingsQueryDateRange(QueryDateRange):
    """Custom QueryDateRange that only applies start/end of day logic when dates don't specify time components."""

    def _has_time_component(self, date_str: str) -> bool:
        """Check if a date string contains a time component."""
        if not date_str:
            return False

        # Check for relative dates (like "-3d", "-1h") - let parent handle these
        if date_str.startswith("-") or date_str.startswith("+"):
            return False

        # Check for time components in absolute dates
        return "T" in date_str or " " in date_str or ":" in date_str

    def date_from(self) -> datetime:
        if self._date_range and isinstance(self._date_range.date_from, str):
            # Check if the date has a time component
            has_time = self._has_time_component(self._date_range.date_from)
            if not has_time:
                # For dates without time components, parse and set to start of day
                parsed = relative_date_parse(
                    self._date_range.date_from,
                    self._timezone_info,
                    now=self.now_with_timezone,
                    always_truncate=False,
                )
                return parsed.replace(hour=0, minute=0, second=0, microsecond=0)

        # Use parent implementation for all other cases
        return super().date_from()

    def date_to(self) -> datetime:
        if self._date_range and self._date_range.date_to:
            # Check if the date has a time component
            has_time = self._has_time_component(self._date_range.date_to)
            if not has_time:
                # For dates without time components, parse and set to end of day
                parsed = relative_date_parse(
                    self._date_range.date_to,
                    self._timezone_info,
                    now=self.now_with_timezone,
                    always_truncate=False,
                )
                return parsed.replace(hour=23, minute=59, second=59, microsecond=999999)

        # Use parent implementation for all other cases
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
