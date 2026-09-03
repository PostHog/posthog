import importlib

from posthog.test.base import ClickhouseDestroyTablesMixin, _create_event, flush_persons_and_events

from posthog.hogql.test.test_property_skip_indexes import _run_explain_and_get_skip_indexes

from posthog.clickhouse.client import sync_execute

module = importlib.import_module("posthog.clickhouse.migrations.0314_session_id_bloom_filter_on_bare_column")

INDEX_FROM_0293 = """
ALTER TABLE sharded_events
ADD INDEX IF NOT EXISTS `bloom_filter_$session_id` nullIf(nullIf(`$session_id`, ''), 'null')
TYPE bloom_filter GRANULARITY 1
"""
SESSION_ID = "019f9a50-0000-7000-8000-000000000001"


def _apply_migration() -> None:
    sync_execute(module.DROP_EXPRESSION_BLOOM_FILTER_INDEX)
    sync_execute(module.ADD_BARE_COLUMN_BLOOM_FILTER_INDEX)


def _session_id_bloom_filter_indexes() -> list[tuple[str, str]]:
    return sync_execute(
        "SELECT name, expr FROM system.data_skipping_indices "
        "WHERE database = currentDatabase() AND table = 'sharded_events' AND type = 'bloom_filter' "
        "AND position(expr, '$session_id') > 0"
    )


class Test0314(ClickhouseDestroyTablesMixin):
    def test_replaces_the_expression_index_with_one_on_the_bare_column_and_can_be_reapplied(self):
        sync_execute(INDEX_FROM_0293)
        _apply_migration()
        _apply_migration()
        assert _session_id_bloom_filter_indexes() == [("bloom_filter_$session_id", "`$session_id`")]

    def test_bare_column_index_engages_for_equals_and_has_under_default_hogql_settings(self):
        _apply_migration()
        _create_event(team=self.team, distinct_id="d", event="$pageview", properties={"$session_id": SESSION_ID})
        flush_persons_and_events()
        values = {"team_id": self.team.pk, "session_ids": [SESSION_ID], "session_id": SESSION_ID}
        for predicate in ("has(%(session_ids)s, `$session_id`)", "equals(`$session_id`, %(session_id)s)"):
            skip_indexes = _run_explain_and_get_skip_indexes(
                f"SELECT count() FROM events WHERE team_id = %(team_id)s AND {predicate}", values
            )
            assert "bloom_filter_$session_id" in skip_indexes, predicate
