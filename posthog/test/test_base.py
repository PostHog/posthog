import pytest
from posthog.test.base import (
    run_clickhouse_statement_in_parallel,
    skip_clickhouse_query_snapshots,
    snapshot_clickhouse_queries,
)

from django.conf import settings

from clickhouse_driver.errors import ServerException

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.events_json import DISTRIBUTED_EVENTS_JSON_TABLE, WRITABLE_EVENTS_JSON_TABLE
from posthog.models.event.sql import EVENTS_DATA_TABLE, EVENTS_JSON_DATA_TABLE, WRITABLE_EVENTS_DATA_TABLE


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
def test_test_database_has_both_events_table_families(django_db_setup) -> None:
    table_names = {
        "events",
        WRITABLE_EVENTS_DATA_TABLE(),
        EVENTS_DATA_TABLE(),
        DISTRIBUTED_EVENTS_JSON_TABLE,
        WRITABLE_EVENTS_JSON_TABLE,
        EVENTS_JSON_DATA_TABLE,
    }

    rows = sync_execute(
        "SELECT name FROM system.tables WHERE database = %(database)s AND name IN %(names)s",
        {"database": settings.CLICKHOUSE_DATABASE, "names": tuple(sorted(table_names))},
    )

    assert {row[0] for row in rows} == table_names
