from typing import Dict, Generator, List

from ee.clickhouse.client import sync_execute

SystemStatusRow = Dict


def system_status() -> Generator[SystemStatusRow, None, None]:
    alive = is_alive()
    yield {"key": "clickhouse_alive", "metric": "Clickhouse database alive", "value": alive}

    if not alive:
        return

    disk_status = sync_execute(
        "SELECT formatReadableSize(total_space), formatReadableSize(free_space) FROM system.disks"
    )

    for index, (total_space, free_space) in enumerate(disk_status):
        metric = "Clickhouse disk" if len(disk_status) == 1 else f"Clickhouse disk {index}"
        yield {"key": f"clickhouse_disk_{index}_free_space", "metric": f"{metric} free space", "value": free_space}
        yield {"key": f"clickhouse_disk_{index}_total_space", "metric": f"{metric} total space", "value": total_space}

    table_sizes = sync_execute(
        """
        SELECT
            table,
            formatReadableSize(sum(bytes)) AS size,
            sum(rows) AS rows
        FROM system.parts
        WHERE active
        GROUP BY table
        ORDER BY rows DESC
    """
    )

    yield {
        "key": "clickhouse_table_sizes",
        "metric": "Clickhouse table sizes",
        "value": "",
        "subrows": {"columns": ["Table", "Size", "Rows"], "rows": table_sizes},
    }

    system_metrics = sync_execute("SELECT * FROM system.asynchronous_metrics")
    system_metrics += sync_execute("SELECT * FROM system.metrics")

    yield {
        "key": "clickhouse_system_metrics",
        "metric": "Clickhouse system metrics",
        "value": "",
        "subrows": {"columns": ["Metric", "Value", "Description"], "rows": list(sorted(system_metrics))},
    }


def is_alive() -> bool:
    try:
        sync_execute("SELECT 1")
        return True
    except:
        return False


def get_clickhouse_running_queries() -> List[Dict]:
    return query_with_columns(
        "SELECT elapsed as duration, query, * FROM system.processes", ["address", "initial_address"]
    )


def query_with_columns(query, columns_to_remove=[]) -> List[Dict]:
    *metrics, types = sync_execute(query, with_column_types=True)
    type_names = [key for key, _type in types]

    rows = [dict(zip(type_names, row[0])) for row in metrics]
    for row in rows:
        for key in columns_to_remove:
            row.pop(key)

    return rows
