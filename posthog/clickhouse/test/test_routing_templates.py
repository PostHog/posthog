"""Unit tests for ch_migrate multi-cluster routing and template generation.

No Django or ClickHouse connection required.
"""

from __future__ import annotations

import unittest

import posthog.clickhouse.test._stubs  # noqa: F401
from posthog.clickhouse.migration_tools.desired_state import ColumnDef, DesiredState, DesiredTable
from posthog.clickhouse.migration_tools.schema_introspect import ColumnSchema, TableSchema


def _make_desired_table(
    name: str,
    engine: str = "ReplicatedMergeTree",
    columns: list[ColumnDef] | None = None,
    on_nodes: list[str] | None = None,
    **kwargs: object,
) -> DesiredTable:
    return DesiredTable(
        name=name,
        engine=engine,
        columns=columns or [],
        on_nodes=on_nodes or ["DATA"],
        **kwargs,  # type: ignore[arg-type]
    )


def _make_table_schema(
    name: str,
    engine: str = "ReplicatedMergeTree",
    columns: list[ColumnSchema] | None = None,
) -> TableSchema:
    return TableSchema(name=name, engine=engine, columns=columns or [])


class TestTemplates(unittest.TestCase):
    def test_ingestion_pipeline_uses_database_placeholder(self) -> None:
        from posthog.clickhouse.migration_tools.templates import generate_schema_yaml

        result = generate_schema_yaml("ingestion_pipeline", "my_events", "main")
        assert result is not None
        mv_table = result["tables"]["my_events_mv"]
        assert "posthog.kafka_" not in mv_table["select"]
        assert "{{ database }}" in mv_table["select"]

    def test_materialized_view_uses_database_placeholder(self) -> None:
        from posthog.clickhouse.migration_tools.templates import generate_schema_yaml

        result = generate_schema_yaml("materialized_view", "my_events", "main")
        assert result is not None
        mv_table = result["tables"]["my_events_mv"]
        assert "posthog.kafka_" not in mv_table["select"]
        assert "{{ database }}" in mv_table["select"]

    def test_unknown_template_returns_none(self) -> None:
        from posthog.clickhouse.migration_tools.templates import generate_schema_yaml

        result = generate_schema_yaml("nonexistent_template", "my_table", "main")
        assert result is None

    def test_sharded_table_produces_distributed_layers(self) -> None:
        from posthog.clickhouse.migration_tools.templates import generate_schema_yaml

        result = generate_schema_yaml("sharded_table", "widgets", "main")
        assert result is not None
        tables = result["tables"]
        assert "sharded_widgets" in tables
        assert "writable_widgets" in tables
        assert "widgets" in tables
        assert tables["sharded_widgets"]["engine"] == "ReplicatedMergeTree"
        assert tables["writable_widgets"]["engine"] == "Distributed"


class TestComputeDiffsPerCluster(unittest.TestCase):
    """_compute_diffs must introspect each declared cluster separately.
    Earlier it used the migrations-cluster union for every target, which
    produced spurious diffs on satellite ecosystems.
    """

    def test_dump_schema_called_per_cluster(self) -> None:
        from unittest.mock import MagicMock, patch

        from posthog.management.commands.ch_migrate import Command

        logs_state = DesiredState(
            ecosystem="logs",
            cluster="logs",
            tables={
                "logs_table": _make_desired_table(
                    "logs_table",
                    engine="ReplicatedMergeTree",
                    columns=[ColumnDef(name="id", type="UUID")],
                    order_by=["id"],
                ),
            },
        )
        main_state = DesiredState(
            ecosystem="events",
            cluster="main",
            tables={
                "sharded_events": _make_desired_table(
                    "sharded_events",
                    engine="ReplicatedMergeTree",
                    columns=[ColumnDef(name="id", type="UUID")],
                    order_by=["id"],
                ),
            },
        )

        main_cluster = MagicMock(name="main-cluster")
        logs_cluster = MagicMock(name="logs-cluster")

        def fake_get_cluster_by_name(name: str, **_kw):
            if name == "logs":
                return logs_cluster
            return main_cluster

        dump_calls: list[object] = []

        def fake_dump(cluster_obj, _database):
            dump_calls.append(cluster_obj)
            return {}

        with (
            patch(
                "posthog.clickhouse.migration_tools.desired_state.parse_desired_state_dir",
                return_value=[main_state, logs_state],
            ),
            patch(
                "posthog.management.commands.ch_migrate.get_cluster_by_name",
                side_effect=fake_get_cluster_by_name,
            ),
            patch("posthog.management.commands.ch_migrate.is_known_cluster", return_value=True),
            patch(
                "posthog.clickhouse.migration_tools.schema_introspect.dump_schema_all_hosts",
                side_effect=fake_dump,
            ),
        ):
            cmd = Command()
            diffs, err = cmd._compute_diffs("posthog", "/tmp/fake_schema_dir")

        self.assertIsNone(err, f"Expected no error; got: {err}")
        self.assertIn(main_cluster, dump_calls, "main cluster not introspected")
        self.assertIn(logs_cluster, dump_calls, "logs cluster not introspected")
        migration_scans = [c for c in dump_calls if c is not main_cluster and c is not logs_cluster]
        self.assertEqual(migration_scans, [], f"Unexpected fallback scans: {migration_scans}")

    def test_unreachable_cluster_falls_back_to_migrations(self) -> None:
        from unittest.mock import MagicMock, patch

        from posthog.management.commands.ch_migrate import Command

        logs_state = DesiredState(
            ecosystem="logs",
            cluster="logs",
            tables={
                "logs_table": _make_desired_table(
                    "logs_table",
                    engine="ReplicatedMergeTree",
                    columns=[ColumnDef(name="id", type="UUID")],
                    order_by=["id"],
                ),
            },
        )

        migrations_cluster = MagicMock(name="migrations-cluster")
        calls: list[object] = []

        def fake_dump(cluster_obj, _database):
            calls.append(cluster_obj)
            return {}

        with (
            patch(
                "posthog.clickhouse.migration_tools.desired_state.parse_desired_state_dir",
                return_value=[logs_state],
            ),
            patch(
                "posthog.management.commands.ch_migrate.get_cluster_by_name",
                side_effect=Exception("Code: 701 CLUSTER_DOESNT_EXIST: Cluster 'logs' not found"),
            ),
            patch("posthog.management.commands.ch_migrate.is_known_cluster", return_value=True),
            patch(
                "posthog.clickhouse.client.migration_tools.get_migrations_cluster",
                return_value=migrations_cluster,
            ),
            patch(
                "posthog.clickhouse.migration_tools.schema_introspect.dump_schema_all_hosts",
                side_effect=fake_dump,
            ),
        ):
            cmd = Command()
            diffs, err = cmd._compute_diffs("posthog", "/tmp/fake_schema_dir")

        self.assertIsNone(err)
        self.assertIn(migrations_cluster, calls, f"Migrations-cluster fallback not used: {calls}")


class TestComputeDiffsSkipsOrphanScanOnFallback(unittest.TestCase):
    """Pass 2 (orphan scan) must be skipped when the satellite cluster was
    unreachable and `current` came from the migrations-cluster fallback.
    Otherwise every main-cluster table becomes a spurious DROP orphan
    against the unreachable satellite.
    """

    def test_no_orphan_drops_when_satellite_falls_back_to_migrations(self) -> None:
        from unittest.mock import MagicMock, patch

        from posthog.management.commands.ch_migrate import Command

        logs_state = DesiredState(
            ecosystem="logs",
            cluster="logs",
            tables={
                "logs_table": _make_desired_table(
                    "logs_table",
                    engine="ReplicatedMergeTree",
                    columns=[ColumnDef(name="id", type="UUID")],
                    order_by=["id"],
                ),
            },
        )

        def fake_get_cluster_by_name(name: str, **_kw):
            if name == "logs":
                raise Exception("Code: 701 CLUSTER_DOESNT_EXIST: Cluster 'logs' not found")
            return MagicMock(name=f"{name}-cluster")

        def fake_dump(_cluster_obj, _database):
            return {
                "host1": {
                    "sharded_events": _make_table_schema("sharded_events", engine="ReplicatedMergeTree"),
                    "sharded_heatmaps": _make_table_schema("sharded_heatmaps", engine="ReplicatedMergeTree"),
                }
            }

        with (
            patch(
                "posthog.clickhouse.migration_tools.desired_state.parse_desired_state_dir",
                return_value=[logs_state],
            ),
            patch(
                "posthog.management.commands.ch_migrate.get_cluster_by_name",
                side_effect=fake_get_cluster_by_name,
            ),
            patch("posthog.management.commands.ch_migrate.is_known_cluster", return_value=True),
            patch(
                "posthog.clickhouse.client.migration_tools.get_migrations_cluster",
                return_value=MagicMock(name="migrations-cluster"),
            ),
            patch(
                "posthog.clickhouse.migration_tools.schema_introspect.dump_schema_all_hosts",
                side_effect=fake_dump,
            ),
        ):
            cmd = Command()
            diffs, err = cmd._compute_diffs("posthog", "/tmp/fake_schema_dir")

        self.assertIsNone(err)
        drops = [d for d in diffs if d.action == "drop"]
        self.assertEqual(drops, [], f"Fallback must not emit orphan drops: {[d.table for d in drops]}")


class TestComputeDiffsSharedPhysicalHost(unittest.TestCase):
    """On dev stacks several logical clusters share the same physical host —
    the orphan scan must NOT emit drops for tables owned by a sibling logical
    cluster even though that cluster's ecosystems don't claim them.
    """

    def test_aux_does_not_drop_main_owned_tables(self) -> None:
        from unittest.mock import MagicMock, patch

        from posthog.management.commands.ch_migrate import Command

        main_state = DesiredState(
            ecosystem="events",
            cluster="main",
            tables={
                "sharded_events": _make_desired_table(
                    "sharded_events",
                    engine="ReplicatedMergeTree",
                    columns=[ColumnDef(name="id", type="UUID")],
                    order_by=["id"],
                ),
            },
        )
        aux_state = DesiredState(
            ecosystem="error_tracking",
            cluster="aux",
            tables={
                "error_tracking_fingerprint": _make_desired_table(
                    "error_tracking_fingerprint",
                    engine="ReplicatedMergeTree",
                    columns=[ColumnDef(name="id", type="UUID")],
                    order_by=["id"],
                ),
            },
        )

        def fake_dump(_cluster_obj, _database):
            return {
                "host1": {
                    "sharded_events": _make_table_schema("sharded_events"),
                    "error_tracking_fingerprint": _make_table_schema("error_tracking_fingerprint"),
                }
            }

        with (
            patch(
                "posthog.clickhouse.migration_tools.desired_state.parse_desired_state_dir",
                return_value=[main_state, aux_state],
            ),
            patch(
                "posthog.management.commands.ch_migrate.get_cluster_by_name",
                side_effect=lambda name, **_kw: MagicMock(name=f"{name}-cluster"),
            ),
            patch("posthog.management.commands.ch_migrate.is_known_cluster", return_value=True),
            patch(
                "posthog.clickhouse.migration_tools.schema_introspect.dump_schema_all_hosts",
                side_effect=fake_dump,
            ),
        ):
            cmd = Command()
            diffs, err = cmd._compute_diffs("posthog", "/tmp/fake_schema_dir")

        self.assertIsNone(err)
        drops = [d for d in diffs if d.action == "drop"]
        self.assertEqual(drops, [], f"No drops expected — every table is claimed: {[d.table for d in drops]}")

    def test_shared_host_still_drops_tables_claimed_nowhere(self) -> None:
        from unittest.mock import MagicMock, patch

        from posthog.management.commands.ch_migrate import Command

        main_state = DesiredState(
            ecosystem="events",
            cluster="main",
            tables={
                "sharded_events": _make_desired_table(
                    "sharded_events",
                    engine="ReplicatedMergeTree",
                    columns=[ColumnDef(name="id", type="UUID")],
                    order_by=["id"],
                ),
            },
        )

        def fake_dump(_cluster_obj, _database):
            return {
                "host1": {
                    "sharded_events": _make_table_schema("sharded_events"),
                    "truly_orphan": _make_table_schema("truly_orphan", engine="MergeTree"),
                }
            }

        with (
            patch(
                "posthog.clickhouse.migration_tools.desired_state.parse_desired_state_dir",
                return_value=[main_state],
            ),
            patch(
                "posthog.management.commands.ch_migrate.get_cluster_by_name",
                side_effect=lambda name, **_kw: MagicMock(name=f"{name}-cluster"),
            ),
            patch("posthog.management.commands.ch_migrate.is_known_cluster", return_value=True),
            patch(
                "posthog.clickhouse.migration_tools.schema_introspect.dump_schema_all_hosts",
                side_effect=fake_dump,
            ),
        ):
            cmd = Command()
            diffs, err = cmd._compute_diffs("posthog", "/tmp/fake_schema_dir")

        self.assertIsNone(err)
        drops = [d for d in diffs if d.action == "drop"]
        self.assertEqual([d.table for d in drops], ["truly_orphan"])


if __name__ == "__main__":
    unittest.main()
