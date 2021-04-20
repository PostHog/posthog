from typing import Dict, Generator

from ee.clickhouse.client import sync_execute

SystemStatusRow = Dict


def system_status() -> Generator[SystemStatusRow, None, None]:
    disk_status = sync_execute(
        "SELECT formatReadableSize(total_space), formatReadableSize(free_space) FROM system.disks"
    )

    for index, (total_space, free_space) in enumerate(disk_status):
        metric = "Clickhouse disk" if len(disk_status) == 1 else f"Clickhouse disk {index}"
        yield {"key": f"clickhouse_disk_{index}_free_space", "metric": f"{metric} free space", "value": free_space}
        yield {"key": f"clickhouse_disk_{index}_total_space", "metric": f"{metric} total space", "value": total_space}

    system_metrics = sync_execute("SELECT * FROM system.asynchronous_metrics")
    system_metrics += sync_execute("SELECT * FROM system.metrics")

    yield {
        "key": "clickhouse_system_metrics",
        "metric": "Clickhouse system metrics",
        "value": "",
        "subrows": list(map(unpack_system_metric, sorted(system_metrics))),
    }


def unpack_system_metric(metric) -> SystemStatusRow:
    return {
        "key": metric[0],
        "metric": metric[0],
        "value": metric[1],
        "description": metric[2] if len(metric) > 2 else "",
    }
