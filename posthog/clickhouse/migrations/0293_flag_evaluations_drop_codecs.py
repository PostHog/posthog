from infi.clickhouse_orm import RunPython

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.flag_evaluations.sql import (
    FLAG_EVALUATIONS_DATA_TABLE,
    FLAG_EVALUATIONS_TABLE,
    FLAG_EVALUATIONS_WRITABLE_TABLE,
)

# Reverts the explicit per-column CODECs that 0292 created to the server-level
# compression default: compression is tuned centrally at the ClickHouse server
# level, and an explicit codec pins a column out of that cluster-wide tuning.
#
# Each table gets two ALTERs: first set the codecs 0292 declared, then REMOVE
# CODEC. The set step exists because REMOVE CODEC errors on a column that has
# no codec, and environments that run 0292 after this change create the tables
# codec-free already (0292 renders the current, codec-free sql.py). Setting and
# removing are both metadata-only, so the pair is an idempotent no-op wherever
# the codecs are already gone and a plain removal where they still exist.
_STRING_CODEC_COLUMNS = (
    "distinct_id",
    "session_id",
    "device_id",
    "flag_key",
    "request_id",
    "error",
    "current_url",
    "pathname",
    "group_0",
    "group_1",
    "group_2",
    "group_3",
    "group_4",
)
_DATETIME_CODEC_COLUMNS = ("timestamp", "inserted_at", "evaluated_at")


def _set_codecs_sql(table: str) -> str:
    actions = ", ".join(
        [f"MODIFY COLUMN IF EXISTS {column} CODEC(DoubleDelta, ZSTD(1))" for column in _DATETIME_CODEC_COLUMNS]
        + [f"MODIFY COLUMN IF EXISTS {column} CODEC(ZSTD(1))" for column in _STRING_CODEC_COLUMNS]
    )
    return f"ALTER TABLE {table} {actions}"


def _remove_codecs_sql(table: str) -> str:
    columns = _DATETIME_CODEC_COLUMNS + _STRING_CODEC_COLUMNS
    actions = ", ".join(f"MODIFY COLUMN IF EXISTS {column} REMOVE CODEC" for column in columns)
    return f"ALTER TABLE {table} {actions}"


def _drop_codecs_operations(
    table: str, node_roles: list[NodeRole], sharded: bool, is_alter_on_replicated_table: bool
) -> list[RunPython]:
    return [
        run_sql_with_exceptions(
            _set_codecs_sql(table),
            node_roles=node_roles,
            sharded=sharded,
            is_alter_on_replicated_table=is_alter_on_replicated_table,
        ),
        run_sql_with_exceptions(
            _remove_codecs_sql(table),
            node_roles=node_roles,
            sharded=sharded,
            is_alter_on_replicated_table=is_alter_on_replicated_table,
        ),
    ]


# The sharded table runs once per shard (replication propagates the ALTER
# within each shard); the two Distributed tables have host-local metadata, so
# their ALTERs must run on every host of their role.
operations = [
    *_drop_codecs_operations(
        FLAG_EVALUATIONS_DATA_TABLE, node_roles=[NodeRole.DATA], sharded=True, is_alter_on_replicated_table=True
    ),
    *_drop_codecs_operations(
        FLAG_EVALUATIONS_WRITABLE_TABLE,
        node_roles=[NodeRole.INGESTION_MEDIUM],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    *_drop_codecs_operations(
        FLAG_EVALUATIONS_TABLE, node_roles=[NodeRole.DATA], sharded=False, is_alter_on_replicated_table=False
    ),
]
