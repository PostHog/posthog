from ee.clickhouse.system_status import system_status


def test_system_status(db):
    results = list(system_status())
    assert [row["key"] for row in results] == [
        "clickhouse_alive",
        "clickhouse_event_count",
        "clickhouse_event_count_last_month",
        "clickhouse_event_count_month_to_date",
        "clickhouse_disk_0_free_space",
        "clickhouse_disk_0_total_space",
        "clickhouse_table_sizes",
        "clickhouse_system_metrics",
        "last_event_ingested_timestamp",
        "dead_letter_queue_size",
        "dead_letter_queue_events_last_day",
        "dead_letter_queue_ratio_ok",
    ]
    assert len(results[6]["subrows"]["rows"]) > 0
    assert len(results[7]["subrows"]["rows"]) > 0
