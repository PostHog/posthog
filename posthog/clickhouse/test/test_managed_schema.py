import pytest

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.managed_schema import ClickHouseDatabase


@pytest.mark.django_db
def test_new_process_rebuilds_schema_after_fixture_restore(monkeypatch: pytest.MonkeyPatch) -> None:
    database = ClickHouseDatabase()
    database.restore()
    sync_execute("DROP TABLE trace_spans")
    monkeypatch.setattr(ClickHouseDatabase, "_snapshot", {})
    database.create_test_tables(kafka=False)

    assert sync_execute("SELECT count() FROM exchange_rate")[0][0] > 0


@pytest.mark.django_db
def test_logs_kafka_metrics_counts_rows_toward_source_partition() -> None:
    database = ClickHouseDatabase()
    select = sync_execute(
        "SELECT as_select FROM system.tables WHERE database = %(database)s AND name = %(name)s",
        {"database": database.name, "name": "kafka_logs_avro_kafka_metrics_mv"},
    )[0][0]
    source = f"FROM {database.name}.logs34"
    assert source in select
    select = select.replace(source, "FROM metrics_input")
    rows = sync_execute(
        """
        WITH metrics_input AS (
            SELECT
                source_row.1 AS _topic,
                toUInt32(source_row.2) AS _partition,
                toUInt64(source_row.3) AS _offset,
                source_row.4 AS _source_topic,
                toUInt32(source_row.5) AS _source_partition,
                toDateTime64('2026-01-02 12:00:00', 6, 'UTC') AS observed_timestamp,
                observed_timestamp AS timestamp
            FROM (
                SELECT arrayJoin([
                    ('clickhouse_logs', 3, 10, 'logs_ingestion', 7),
                    ('clickhouse_logs', 5, 11, '', 0)
                ]) AS source_row
            )
        )
        SELECT _topic, _partition, max_offset FROM ("""
        + select
        + ") ORDER BY _topic, _partition",
    )
    assert rows == [("clickhouse_logs", 3, 10), ("clickhouse_logs", 5, 11), ("logs_ingestion", 7, 0)]
