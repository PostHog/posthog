import importlib

from posthog.test.base import ClickhouseDestroyTablesMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.hogql.test.test_property_skip_indexes import _run_explain_and_get_skip_indexes

from posthog.clickhouse.client import sync_execute

module = importlib.import_module("posthog.clickhouse.migrations.0314_add_bare_session_id_bloom_filter")

EXPRESSION_INDEX_FROM_0293 = """
ALTER TABLE sharded_events
ADD INDEX IF NOT EXISTS `bloom_filter_$session_id` nullIf(nullIf(`$session_id`, ''), 'null')
TYPE bloom_filter GRANULARITY 1
"""
SESSION_ID = "019f9a50-0000-7000-8000-000000000001"


def _session_id_bloom_filter_indexes() -> dict[str, str]:
    return dict(
        sync_execute(
            "SELECT name, expr FROM system.data_skipping_indices "
            "WHERE database = currentDatabase() AND table = 'sharded_events' AND type = 'bloom_filter' "
            "AND position(expr, '$session_id') > 0"
        )
    )


class Test0314(ClickhouseDestroyTablesMixin):
    def test_adds_a_bare_column_index_next_to_the_expression_index_and_can_be_reapplied(self):
        sync_execute(EXPRESSION_INDEX_FROM_0293)
        sync_execute(module.ADD_BARE_COLUMN_BLOOM_FILTER_INDEX)
        sync_execute(module.ADD_BARE_COLUMN_BLOOM_FILTER_INDEX)

        indexes = _session_id_bloom_filter_indexes()
        assert set(indexes) == {"bloom_filter_$session_id", "bloom_filter_$session_id_column"}
        assert indexes["bloom_filter_$session_id_column"] == "`$session_id`"

    @parameterized.expand(
        [
            ("has", "has(%(session_ids)s, `$session_id`)"),
            ("equals", "equals(`$session_id`, %(session_id)s)"),
        ]
    )
    def test_bare_column_index_engages_under_default_hogql_settings(self, _name: str, predicate: str):
        sync_execute(module.ADD_BARE_COLUMN_BLOOM_FILTER_INDEX)
        _create_event(team=self.team, distinct_id="d", event="$pageview", properties={"$session_id": SESSION_ID})
        flush_persons_and_events()
        values = {"team_id": self.team.pk, "session_ids": [SESSION_ID], "session_id": SESSION_ID}
        skip_indexes = _run_explain_and_get_skip_indexes(
            f"SELECT count() FROM events WHERE team_id = %(team_id)s AND {predicate}", values
        )
        assert "bloom_filter_$session_id_column" in skip_indexes
