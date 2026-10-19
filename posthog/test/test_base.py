import pytest
from posthog.test.base import (
    QueryMatchingTest,
    run_clickhouse_statement_in_parallel,
    skip_clickhouse_query_snapshots,
    snapshot_clickhouse_queries,
    snapshot_postgres_queries_context,
)

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import reset_queries
from django.test import TestCase

from clickhouse_driver.errors import ServerException

from posthog.clickhouse.client import sync_execute
from posthog.models.event.sql import (
    DISTRIBUTED_EVENTS_JSON_TABLE,
    EVENTS_DATA_TABLE,
    EVENTS_JSON_DATA_TABLE,
    WRITABLE_EVENTS_DATA_TABLE,
    WRITABLE_EVENTS_JSON_TABLE,
)
from posthog.models.team.team import Team


def test_snapshot_clickhouse_queries_skips_marked_methods() -> None:
    class ExampleTests:
        @skip_clickhouse_query_snapshots
        def test_behavior(self) -> None:
            pass

    test_behavior = ExampleTests.test_behavior

    snapshot_clickhouse_queries(ExampleTests)

    assert ExampleTests.test_behavior is test_behavior


def test_run_clickhouse_statement_in_parallel_propagates_errors():
    with pytest.raises(ServerException):
        run_clickhouse_statement_in_parallel(["SELECT invalid syntax!!!"])


@pytest.mark.django_db
def test_events_schema_setting_controls_legacy_table_availability(django_db_setup) -> None:
    legacy_table_names = {"events", WRITABLE_EVENTS_DATA_TABLE(), EVENTS_DATA_TABLE()}
    json_table_names = {DISTRIBUTED_EVENTS_JSON_TABLE, WRITABLE_EVENTS_JSON_TABLE, EVENTS_JSON_DATA_TABLE}
    table_names_sql = ", ".join(f"'{table_name}'" for table_name in sorted(legacy_table_names | json_table_names))

    rows = sync_execute(
        f"""
        SELECT name
        FROM system.tables
        WHERE database = %(database)s
        AND name IN ({table_names_sql})
        """,
        {"database": settings.CLICKHOUSE_DATABASE},
    )
    actual_table_names = {row[0] for row in rows}

    if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
        assert json_table_names <= actual_table_names
    else:
        assert legacy_table_names <= actual_table_names


class TestSnapshotPostgresQueriesContext(TestCase, QueryMatchingTest):
    def test_cold_content_type_cache_fill_is_neither_captured_nor_counted(self) -> None:
        ContentType.objects.clear_cache()

        with self.assertNumQueries(1) as counted:
            with snapshot_postgres_queries_context(self, custom_query_matcher=lambda query: False) as context:
                ContentType.objects.get_for_model(Team)
                Team.objects.exists()

        assert context.captured_queries == [{"sql": query["sql"]} for query in counted.captured_queries]

    def test_capture_keeps_queries_that_ran_before_a_query_log_clear(self) -> None:
        with snapshot_postgres_queries_context(self, custom_query_matcher=lambda query: False) as context:
            Team.objects.exists()
            reset_queries()
            Team.objects.exists()

        assert len(context.captured_queries) == 2
