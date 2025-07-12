from datetime import datetime

from posthog.constants import PropertyOperatorType
from posthog.hogql import ast
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models import Team
from posthog.schema import RecordingsQuery, DateRange
from posthog.session_recordings.queries_to_replace.session_replay_events import ttl_days


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
        return QueryDateRange(
            date_range=DateRange(date_from=self._query.date_from, date_to=self._query.date_to, explicitDate=True),
            team=self._team,
            interval=None,
            now=datetime.now(),
        )
