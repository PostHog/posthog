from posthog.client import sync_execute
from posthog.settings import CLICKHOUSE_DATABASE


def analyze_enough_disk_space_free_for_table(table_name: str, required_ratio: float):
    """
    Analyzes whether there's enough disk space free for given async migration operation.

    This is done by checking whether there's at least ratio times space free to resize table_name with.
    """

    current_ratio, _, required_space_pretty = sync_execute(
        f"""
        WITH (
            SELECT free_space
            FROM system.disks WHERE name = 'default'
        ) AS free_disk_space,(
            SELECT total_space
            FROM system.disks WHERE name = 'default'
        ) AS total_disk_space,(
            SELECT sum(bytes) as size
            FROM system.parts
            WHERE table = %(table_name)s AND database = %(database)s
        ) AS table_size
        SELECT
            free_disk_space / greatest(table_size, 1),
            total_disk_space - (free_disk_space - %(ratio)s * table_size) AS required,
            formatReadableSize(required)
        """,
        {"database": CLICKHOUSE_DATABASE, "table_name": table_name, "ratio": required_ratio,},
    )[0]

    if current_ratio >= required_ratio:
        return (True, None)
    else:
        return (False, f"Upgrade your ClickHouse storage to at least {required_space_pretty}.")
