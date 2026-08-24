"""Replay's session lookups run with ``transform_null_in`` off so ClickHouse can use ``bloom_filter_$session_id``.

HogQL defaults ``transform_null_in=1``, and under it ClickHouse skips index analysis for ``IN`` on a Nullable key —
which the ``nullIf(nullIf($session_id, ''), 'null')`` sentinel scrub is — so every ``$session_id IN (...)`` lookup
scans the team's whole window. Checked via ``EXPLAIN PLAN indexes=1`` rather than the printed SQL: the SQL is
identical either way, only the plan shows whether the index engaged.
"""

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.conf import settings

from posthog.schema import RecordingsQuery

from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.test.test_property_skip_indexes import _run_explain_and_get_skip_indexes

from posthog.clickhouse.client import sync_execute
from posthog.hogql_queries.insights.paginators import HogQLCursorPaginator
from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingListFromQuery
from posthog.session_recordings.queries.sub_queries.base_query import replay_hogql_settings
from posthog.session_recordings.queries.sub_queries.events_subquery import ReplayFiltersEventsSubQuery

SESSION_ID_BLOOM_FILTER_INDEX = "bloom_filter_$session_id"
PAGEVIEW_FILTER = {"id": "$pageview", "type": "events", "order": 0, "name": "$pageview"}


class _QueryRecorded(Exception):
    pass


class TestReplayHogQLSettings(ClickhouseTestMixin, APIBaseTest):
    def _session_lookup_query(self) -> RecordingsQuery:
        return RecordingsQuery(
            session_ids=["019f9a50-96a1-74d2-8989-da831adb4ce4"], date_from="-7d", events=[PAGEVIEW_FILTER]
        )

    def test_matching_events_for_session_query_runs_with_transform_null_in_off(self) -> None:
        subquery = ReplayFiltersEventsSubQuery(team=self.team, query=self._session_lookup_query())

        with patch(
            "posthog.session_recordings.queries.sub_queries.events_subquery.execute_hogql_query"
        ) as execute_hogql_query:
            execute_hogql_query.return_value.results = []
            execute_hogql_query.return_value.timings = []
            subquery.get_event_ids_for_session()

        self.assertIs(execute_hogql_query.call_args.kwargs["settings"].transform_null_in, False)

    def test_session_recording_list_query_runs_with_transform_null_in_off(self) -> None:
        recorded: list[HogQLGlobalSettings] = []

        def record_settings(*args: object, **kwargs: object) -> None:
            recorded.append(kwargs["settings"])  # type: ignore[arg-type]
            raise _QueryRecorded()

        with patch.object(HogQLCursorPaginator, "execute_hogql_query", side_effect=record_settings):
            with self.assertRaises(_QueryRecorded):
                SessionRecordingListFromQuery(
                    team=self.team, query=self._session_lookup_query(), max_execution_time=42
                ).run()

        self.assertIs(recorded[0].transform_null_in, False)
        # The runner's own settings still ride along.
        self.assertEqual(recorded[0].max_execution_time, 42)

    def test_session_id_lookup_engages_bloom_filter_only_with_replay_settings(self) -> None:
        if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
            self.skipTest("the new events schema table does not carry the sharded_events skip indexes")
        # The test schema is built from CREATE TABLE statements, so migration 0293's index has to be added here.
        sync_execute(
            f"ALTER TABLE sharded_events ADD INDEX IF NOT EXISTS `{SESSION_ID_BLOOM_FILTER_INDEX}` "
            "nullIf(nullIf(`$session_id`, ''), 'null') TYPE bloom_filter GRANULARITY 1"
        )
        self.addCleanup(
            sync_execute, f"ALTER TABLE sharded_events DROP INDEX IF EXISTS `{SESSION_ID_BLOOM_FILTER_INDEX}`"
        )
        # Index analysis only runs over existing parts, so the team needs at least one event on disk.
        _create_event(team=self.team, event="$pageview", distinct_id="someone", properties={"$session_id": "other"})
        flush_persons_and_events()
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        query = ReplayFiltersEventsSubQuery(team=self.team, query=self._session_lookup_query())
        sql, _ = prepare_and_print_ast(query.get_query_for_event_id_matching(), context, "clickhouse")

        with_defaults = _run_explain_and_get_skip_indexes(sql, context.values, HogQLGlobalSettings())
        with_replay_settings = _run_explain_and_get_skip_indexes(sql, context.values, replay_hogql_settings())

        self.assertNotIn(SESSION_ID_BLOOM_FILTER_INDEX, with_defaults)
        self.assertIn(SESSION_ID_BLOOM_FILTER_INDEX, with_replay_settings)
