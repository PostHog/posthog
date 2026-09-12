import importlib
from collections.abc import Callable

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.schema import RecordingsQuery

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.test.test_property_skip_indexes import _run_explain_and_get_skip_indexes

from posthog.clickhouse.client import sync_execute
from posthog.session_recordings.queries.sub_queries.events_subquery import ReplayFiltersEventsSubQuery

migration_0314 = importlib.import_module("posthog.clickhouse.migrations.0314_session_id_bloom_filter_on_bare_column")

SESSION_ID = "019f9a50-0000-7000-8000-000000000001"


class TestSessionIdBloomFilter(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        sync_execute(migration_0314.ADD_BARE_COLUMN_BLOOM_FILTER_INDEX)
        self.addCleanup(sync_execute, "ALTER TABLE sharded_events DROP INDEX IF EXISTS `bloom_filter_$session_id`")
        _create_event(team=self.team, distinct_id="d", event="$pageview", properties={"$session_id": SESSION_ID})
        flush_persons_and_events()

    @parameterized.expand(
        [
            ("matching_events", lambda subquery: subquery.get_query_for_event_id_matching()),
            ("list_with_session_ids", lambda subquery: subquery.get_queries_for_session_id_matching()[0]),
        ]
    )
    def test_session_id_filter_engages_the_bloom_filter(
        self, _name: str, build: Callable[[ReplayFiltersEventsSubQuery], ast.SelectQuery | ast.SelectSetQuery]
    ) -> None:
        query = RecordingsQuery(
            session_ids=[SESSION_ID],
            date_from="-7d",
            events=[{"id": "$pageview", "type": "events", "order": 0, "name": "$pageview"}],
        )
        select = build(ReplayFiltersEventsSubQuery(self.team, query))
        context = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
        sql, _ = prepare_and_print_ast(select, context, "clickhouse")

        assert "bloom_filter_$session_id" in _run_explain_and_get_skip_indexes(sql, context.values)
