from datetime import datetime, timedelta

from posthog.hogql import ast
from posthog.hogql.ast import CompareOperation
from posthog.hogql.parser import parse_select
from posthog.models import Team
from posthog.schema import RecordingsQuery
from posthog.session_recordings.queries_to_replace.utils import poe_is_active
from posthog.session_recordings.queries_to_replace.sub_queries.base_query import SessionRecordingsListingBaseQuery


class PersonsIdCompareOperation(SessionRecordingsListingBaseQuery):
    def __init__(self, team: Team, query: RecordingsQuery):
        super().__init__(team, query)

    def get_operation(self) -> CompareOperation | None:
        q = self.get_query()
        if not q:
            return None

        if poe_is_active(self._team):
            return ast.CompareOperation(
                # this hits the distributed events table from the distributed session_replay_events table
                # so we should use GlobalIn
                # see https://clickhouse.com/docs/en/sql-reference/operators/in#distributed-subqueries
                op=ast.CompareOperationOp.GlobalIn,
                left=ast.Field(chain=["session_id"]),
                right=q,
            )
        else:
            return ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=ast.Field(chain=["distinct_id"]),
                right=q,
            )

    def get_query(self) -> ast.SelectQuery | ast.SelectSetQuery | None:
        if not self._query.person_uuid:
            return None

        # anchor to python now so that tests can freeze time
        now = datetime.utcnow()

        if poe_is_active(self._team):
            return parse_select(
                """
                select
                    distinct `$session_id`
                from
                    events
                where
                    person_id = {person_id}
                    and timestamp <= {now}
                    and timestamp >= {ttl_date}
                    and timestamp >= {date_from}
                    and timestamp <= {date_to}
                    and notEmpty(`$session_id`)
                """,
                {
                    "person_id": ast.Constant(value=self._query.person_uuid),
                    "ttl_days": ast.Constant(value=self.ttl_days),
                    "date_from": ast.Constant(value=self.query_date_range.date_from()),
                    "date_to": ast.Constant(value=self.query_date_range.date_to()),
                    "now": ast.Constant(value=now),
                    "ttl_date": ast.Constant(value=now - timedelta(days=self.ttl_days)),
                },
            )
        else:
            return parse_select(
                """
                SELECT distinct_id
                FROM person_distinct_ids
                WHERE person_id = {person_id}
                """,
                {
                    "person_id": ast.Constant(value=self._query.person_uuid),
                },
            )
