from ee.clickhouse.system_status import system_status


def test_system_status(db):
    results = list(system_status())
    assert [row["key"] for row in results] == [
        "clickhouse_disk_0_free_space",
        "clickhouse_disk_0_total_space",
        "clickhouse_system_metrics",
    ]
    assert len(results[-1]["subrows"]) > 0
