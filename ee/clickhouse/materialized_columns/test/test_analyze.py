import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import call, patch

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.property_groups import property_groups
from posthog.clickhouse.query_tagging import tags_context

from ee.clickhouse.materialized_columns.analyze import _analyze, materialize_properties_task


class TestMaterializedColumnsAnalyze(ClickhouseTestMixin, BaseTest):
    def test_property_group_reads_suggest_materialization(self):
        # Real queries against events whose log entries read via property group map columns. Inserting
        # synthetic rows into system.query_log is silently ignored on current ClickHouse versions, so the
        # analyzer is exercised against genuine query log entries with the gating thresholds opened up.
        # Every probed key must exist on at least one event: the map-key bloom filter otherwise prunes the
        # scan to zero rows read, which fails the analyzer's read_rows/read_bytes gates even when opened to 0.
        _create_event(
            team=self.team,
            distinct_id="d1",
            event="e",
            properties={"materialize_me_group": "x", "mat_group_ternary": "y2", "$feature/my-flag": "true"},
            person_properties={"mat_person_group": "z"},
        )
        flush_persons_and_events()

        group_read_queries = [
            f"SELECT count() FROM events WHERE team_id = {self.team.pk} AND properties_group_custom['materialize_me_group'] = 'x'",
            f"SELECT count() FROM events WHERE team_id = {self.team.pk} AND if(has(properties_group_custom, 'mat_group_ternary'), properties_group_custom['mat_group_ternary'], NULL) != 'y'",
            f"SELECT count() FROM events WHERE team_id = {self.team.pk} AND person_properties_map_custom['mat_person_group'] = 'z'",
            f"SELECT count() FROM events WHERE team_id = {self.team.pk} AND properties_group_feature_flags['$feature/my-flag'] = 'true'",
        ]
        with tags_context(team_id=self.team.pk):
            for query in group_read_queries:
                for _ in range(10):
                    sync_execute(query)
        sync_execute("SYSTEM FLUSH LOGS")

        suggestions = set(
            _analyze(since_hours_ago=1, min_query_time=-1, team_id=self.team.pk, min_bytes_read=0, min_read_rows=0)
        )

        assert ("events", "properties", "materialize_me_group") in suggestions
        assert ("events", "properties", "mat_group_ternary") in suggestions
        assert ("events", "person_properties", "mat_person_group") in suggestions
        assert ("events", "properties", "$feature/my-flag") in suggestions

    def test_group_columns_to_source_columns(self):
        mapping = property_groups.get_group_columns_to_source_columns("events")
        assert mapping["properties_group_custom"] == "properties"
        assert mapping["person_properties_map_custom"] == "person_properties"

    @pytest.mark.skip(reason="Test is failing for some reason")
    @patch("ee.clickhouse.materialized_columns.analyze.materialize")
    @patch("ee.clickhouse.materialized_columns.analyze.backfill_materialized_columns")
    def test_mat_columns(self, patch_backfill, patch_materialize):
        sync_execute("SYSTEM FLUSH LOGS")
        sync_execute("TRUNCATE TABLE system.query_log")

        queries_to_insert = [
            "SELECT * FROM events WHERE JSONExtractRaw(properties, \\'materialize_me\\')",
            "SELECT * FROM events WHERE JSONExtractRaw(properties, \\'materialize_me\\')",
            "SELECT * FROM events WHERE JSONExtractRaw(properties, \\'materialize_me2\\')",
            "SELECT * FROM events WHERE JSONExtractRaw(`e`.properties, \\'materialize_me3\\')",
            "SELECT * FROM events WHERE JSONExtractRaw(person_properties, \\'materialize_person_prop\\')",
            "SELECT * FROM groups WHERE JSONExtractRaw(group.group_properties, \\'materialize_person_prop\\')",  # this should not appear
            "SELECT * FROM groups WHERE JSONExtractRaw(group.group_properties, \\'nested\\', \\'property\\')",  # this should not appear
        ]

        for query in queries_to_insert:
            sync_execute(
                """
            INSERT INTO system.query_log (
                query,
                query_start_time,
                type,
                is_initial_query,
                log_comment,
                exception_code,
                read_bytes,
                read_rows
            ) VALUES (
                '{query}',
                now(),
                3,
                1,
                '{log_comment}',
                159,
                40000000000,
                10000000
            )
            """.format(query=query, log_comment='{"team_id": 2}')
            )
        materialize_properties_task()
        patch_materialize.assert_has_calls(
            [
                call("events", "materialize_me", table_column="properties", is_nullable=False),
                call("events", "materialize_me2", table_column="properties", is_nullable=False),
                call("events", "materialize_person_prop", table_column="person_properties", is_nullable=False),
                call("events", "materialize_me3", table_column="properties", is_nullable=False),
            ]
        )
