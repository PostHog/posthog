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
    ]
    assert len(results[-2]["subrows"]["rows"]) > 0
    assert len(results[-1]["subrows"]["rows"]) > 0
