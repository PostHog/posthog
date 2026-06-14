import pytest
from posthog.test.base import run_clickhouse_statement_in_parallel

from django.conf import settings

from clickhouse_driver.errors import ServerException

from posthog.clickhouse.client import sync_execute
from posthog.models.event.sql import (
    DISTRIBUTED_EVENTS_JSON_TABLE,
    EVENTS_DATA_TABLE,
    EVENTS_JSON_DATA_TABLE,
    WRITABLE_EVENTS_DATA_TABLE,
    WRITABLE_EVENTS_JSON_TABLE,
)


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
        assert legacy_table_names.isdisjoint(actual_table_names)
    else:
        assert legacy_table_names <= actual_table_names
