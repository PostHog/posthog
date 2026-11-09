from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.query_log_archive import QUERY_LOG_ARCHIVE_V3_BUFFER_TABLE, SHARDED_QUERY_LOG_ARCHIVE_V3_TABLE
from posthog.clickhouse.table_engines import Buffer
from posthog.run_mode import RunMode, run_mode

# Each Buffer layer that holds rows flushes on its own once max_time passes, and each flush writes a
# part into the replicated data table. On an idle hobby install the query_log flushes spread their
# inserts over many of the 16 layers, so every minute brings several small parts where one would do.
# One layer is enough for the query volume of a single install.
#
# Installs that applied 0273 before it built the v3 archive still write through the earlier
# generation's query_log_archive_buffer, so both Buffers get one layer, each only where it exists.
# The copy takes its columns from the Buffer it replaces, because those differ between installs.
# EXCHANGE TABLES swaps the two atomically, so the archive never loses its Buffer.
BUFFERS = [
    ("query_log_archive_buffer", "sharded_query_log_archive"),
    (QUERY_LOG_ARCHIVE_V3_BUFFER_TABLE, SHARDED_QUERY_LOG_ARCHIVE_V3_TABLE),
]


def one_layer_buffer_operations(buffer_table: str, destination_table: str) -> list:
    one_layer_table = f"{buffer_table}_one_layer"
    engine = Buffer(
        destination_table=destination_table,
        num_layers=1,
        min_time=10,
        max_time=60,
        min_rows=10_000,
        max_rows=1_000_000,
        min_bytes=10_000_000,
        max_bytes=100_000_000,
    )
    return [
        run_sql_with_exceptions(f"DROP TABLE IF EXISTS {one_layer_table}", node_roles=[NodeRole.OPS]),
        run_sql_with_exceptions(
            f"CREATE TABLE {one_layer_table} AS {buffer_table} ENGINE = {engine}",
            node_roles=[NodeRole.OPS],
            only_if_table_exists=buffer_table,
        ),
        run_sql_with_exceptions(
            f"EXCHANGE TABLES {buffer_table} AND {one_layer_table}",
            node_roles=[NodeRole.OPS],
            only_if_table_exists=one_layer_table,
        ),
        run_sql_with_exceptions(f"DROP TABLE IF EXISTS {one_layer_table}", node_roles=[NodeRole.OPS]),
    ]


operations = (
    [
        operation
        for buffer_table, destination in BUFFERS
        for operation in one_layer_buffer_operations(buffer_table, destination)
    ]
    if run_mode() is RunMode.HOBBY
    else []
)
