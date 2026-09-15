import re
from collections.abc import Callable
from importlib import import_module
from uuid import uuid4

import pytest

from django.conf import settings

from clickhouse_driver.errors import ServerException

from posthog.clickhouse.client import sync_execute
from posthog.session_recordings.sql.session_replay_event_sql import (
    KAFKA_SESSION_REPLAY_EVENTS_TABLE_BASE_SQL,
    SESSION_REPLAY_EVENTS_TABLE_BASE_SQL,
    SESSION_REPLAY_EVENTS_TABLE_MV_SQL,
    SESSION_REPLAY_EVENTS_WS_MV_SQL,
)


@pytest.mark.parametrize("mv_sql", [SESSION_REPLAY_EVENTS_TABLE_MV_SQL, SESSION_REPLAY_EVENTS_WS_MV_SQL])
def test_replay_metadata_reads_old_parts_and_classified_blocks(mv_sql: Callable[..., str]) -> None:
    suffix = uuid4().hex
    source = f"replay_mode_source_{suffix}"
    target = f"replay_mode_target_{suffix}"
    view = f"replay_mode_mv_{suffix}"
    database = settings.CLICKHOUSE_DATABASE
    migration = import_module("posthog.clickhouse.migrations.0322_add_snapshot_mode_v2_to_session_replay_events")

    def create_view(*, legacy: bool) -> None:
        query = mv_sql(on_cluster=False, exclude_columns=["snapshot_mode_v2"] if legacy else [])
        for original in ("session_replay_events_ws_mv", "session_replay_events_mv"):
            query = query.replace(original, view)
        for original in ("kafka_session_replay_events_ws", "kafka_session_replay_events"):
            query = query.replace(original, source)
        sync_execute(query.replace("writable_session_replay_events", target))

    def insert_block(session_id: str, mode: str | None, timestamp: str) -> None:
        sync_execute(
            f"""
            INSERT INTO {database}.{source}
                (session_id, team_id, distinct_id, first_timestamp, last_timestamp, snapshot_source, snapshot_mode)
            VALUES (%(session_id)s, 1, 'test-user', %(timestamp)s, %(timestamp)s, 'mobile', %(mode)s)
            """,
            {"session_id": session_id, "timestamp": timestamp, "mode": mode},
        )

    try:
        sync_execute(
            KAFKA_SESSION_REPLAY_EVENTS_TABLE_BASE_SQL.replace(
                ") ENGINE = {engine}", "_timestamp DateTime\n) ENGINE = {engine}"
            ).format(table_name=f"{database}.{source}", on_cluster_clause="", engine="Memory")
        )
        sync_execute(
            SESSION_REPLAY_EVENTS_TABLE_BASE_SQL.replace(
                "    snapshot_mode_v2 AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),\n", ""
            ).format(
                table_name=f"{database}.{target}",
                on_cluster_clause="",
                engine="AggregatingMergeTree ORDER BY (team_id, session_id, toDate(min_first_timestamp))",
            )
        )
        create_view(legacy=True)
        insert_block("historical", "screenshot", "2026-01-01 00:00:00")
        sync_execute(f"DROP VIEW IF EXISTS {database}.{view}")
        for _ in range(2):
            sync_execute(migration.ADD_SNAPSHOT_MODE_V2.format(table_name=f"{database}.{target}"))
        create_view(legacy=False)

        insert_block("screenshots", None, "2026-01-02 00:00:00")
        insert_block("screenshots", "screenshot", "2026-01-03 00:00:00")
        insert_block("screenshots", None, "2026-01-04 00:00:00")
        insert_block("wireframes", "wireframe", "2026-01-02 00:00:00")
        insert_block("unknown", None, "2026-01-02 00:00:00")

        query = f"""
            SELECT session_id, argMinMerge(snapshot_source), argMinMerge(snapshot_mode_v2)
            FROM {database}.{target}
            GROUP BY session_id ORDER BY session_id
        """
        expected = [
            ("historical", "mobile", None),
            ("screenshots", "mobile", "screenshot"),
            ("unknown", "mobile", None),
            ("wireframes", "mobile", "wireframe"),
        ]
        assert sync_execute(query) == expected
        sync_execute(f"OPTIMIZE TABLE {database}.{target} FINAL")
        assert sync_execute(query) == expected
    finally:
        sync_execute(f"DROP VIEW IF EXISTS {database}.{view}")
        sync_execute(f"DROP TABLE IF EXISTS {database}.{source}")
        sync_execute(f"DROP TABLE IF EXISTS {database}.{target}")


@pytest.mark.parametrize(
    "unprepared_table", ["sharded_session_replay_events", "writable_session_replay_events", "session_replay_events"]
)
@pytest.mark.parametrize("problem", ["source_type", "legacy_mode"])
def test_mode_migration_rejects_unprepared_schema_before_changing_tables(unprepared_table: str, problem: str) -> None:
    migration = import_module("posthog.clickhouse.migrations.0322_add_snapshot_mode_v2_to_session_replay_events")
    suffix = uuid4().hex
    tables = ["sharded_session_replay_events", "writable_session_replay_events", "session_replay_events"]
    views = ["session_replay_events_mv", "session_replay_events_ws_mv"]
    source = "kafka_session_replay_events"
    names = {name: f"{name}_{suffix}" for name in [*tables, *views, source]}
    name_pattern = re.compile(r"\b(" + "|".join(names) + r")\b")
    source_column = "    snapshot_source AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),\n"
    mode_column = "    snapshot_mode_v2 AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),\n"
    prepared_schema = SESSION_REPLAY_EVENTS_TABLE_BASE_SQL.replace(mode_column, "")

    def create_target(table: str, *, prepared: bool) -> None:
        schema = prepared_schema
        if not prepared:
            if problem == "source_type":
                schema = schema.replace(
                    source_column, source_column.replace("Nullable(String)", "LowCardinality(Nullable(String))")
                )
            else:
                schema = schema.replace(
                    source_column, source_column + mode_column.replace("snapshot_mode_v2", "snapshot_mode")
                )
        sync_execute(schema.format(table_name=names[table], on_cluster_clause="", engine="Memory"))

    def run_migration() -> None:
        for operation in migration.operations:
            sync_execute(name_pattern.sub(lambda match: names[match[0]], operation._sql))

    try:
        for table in tables:
            create_target(table, prepared=table != unprepared_table)
        sync_execute(
            KAFKA_SESSION_REPLAY_EVENTS_TABLE_BASE_SQL.replace(
                ") ENGINE = {engine}", "_timestamp DateTime\n) ENGINE = {engine}"
            ).format(table_name=names[source], on_cluster_clause="", engine="Memory")
        )
        for view in views:
            sync_execute(f"CREATE VIEW {names[view]} AS SELECT 1")

        with pytest.raises(ServerException, match="Replay metadata schema is not ready"):
            run_migration()

        assert sync_execute(
            "SELECT count() FROM system.columns WHERE database = currentDatabase() "
            "AND table IN %(tables)s AND name = 'snapshot_mode_v2'",
            {"tables": tuple(names[table] for table in tables)},
        ) == [(0,)]
        assert sync_execute(
            "SELECT count() FROM system.tables WHERE database = currentDatabase() "
            "AND name IN %(views)s AND engine = 'View'",
            {"views": tuple(names[view] for view in views)},
        ) == [(2,)]

        sync_execute(f"DROP TABLE {names[unprepared_table]}")
        create_target(unprepared_table, prepared=True)
        run_migration()
        assert sync_execute(
            "SELECT count() FROM system.columns WHERE database = currentDatabase() "
            "AND table IN %(tables)s AND name = 'snapshot_mode_v2'",
            {"tables": tuple(names[table] for table in tables)},
        ) == [(3,)]
        assert sync_execute(
            "SELECT engine FROM system.tables WHERE database = currentDatabase() AND name = %(view)s",
            {"view": names[views[0]]},
        ) == [("MaterializedView",)]
    finally:
        for name in [*views, source, *tables]:
            sync_execute(f"DROP TABLE IF EXISTS {names[name]}")
