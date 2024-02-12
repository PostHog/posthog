from typing import cast

from posthog.hogql import ast
from posthog.hogql.ast import SelectQuery
from posthog.hogql.visitor import clear_locations
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.schema import HogQLQuery
from posthog.test.base import ClickhouseTestMixin, APIBaseTest


class TestSessionReplayEventsHogQLQueries(ClickhouseTestMixin, APIBaseTest):
    def test_session_replay_events_table_is_always_grouped_by_session_id(self):
        # test that the "not raw" table is always grouped by session id
        runner = HogQLQueryRunner(
            team=self.team, query=HogQLQuery(query="select session_id from session_replay_events")
        )

        query: SelectQuery = cast(SelectQuery, clear_locations(runner.to_query()))

        assert query.select == [ast.Field(chain=["session_id"])]
        assert query.select_from == ast.JoinExpr(table=ast.Field(chain=["session_replay_events"]))
        assert query.group_by == [ast.Field(chain=["session_replay_events", "session_id"])]

        # TODO add data so this does something
        response = runner.calculate()
        assert response.results == []
