def test_system_status(db):
    from posthog.clickhouse.system_status import system_status

    results = list(system_status())
    assert [row["key"] for row in results] == [
        "clickhouse_alive",
        "clickhouse_event_count",
        "clickhouse_event_count_last_month",
        "clickhouse_event_count_month_to_date",
        "clickhouse_session_recordings_count_month_to_date",
        "clickhouse_session_recordings_events_count_month_to_date",
        "clickhouse_session_recordings_events_size_ingested",
        "clickhouse_disk_0_free_space",
        "clickhouse_disk_0_total_space",
        "clickhouse_table_sizes",
        "clickhouse_system_metrics",
        "last_event_ingested_timestamp",
        "dead_letter_queue_size",
        "dead_letter_queue_events_last_day",
        "dead_letter_queue_ratio_ok",
    ]
    assert len(results[9]["subrows"]["rows"]) > 0
    assert len(results[10]["subrows"]["rows"]) > 0
