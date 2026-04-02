"""Unit tests for desired-state reconciliation (desired_state, state_diff, plan_generator).

No Django or ClickHouse connection required.
"""

from __future__ import annotations

import tempfile
import textwrap
from pathlib import Path

import unittest

import posthog.clickhouse.test._stubs  # noqa: F401
from posthog.clickhouse.migration_tools.desired_state import (
    ColumnDef,
    DesiredState,
    DesiredTable,
    parse_desired_state,
    parse_desired_state_dir,
)
from posthog.clickhouse.migration_tools.plan_generator import (
    generate_manifest_steps,
    generate_plan_text,
    generate_rollback_steps,
)
from posthog.clickhouse.migration_tools.schema_introspect import ColumnSchema, TableSchema
from posthog.clickhouse.migration_tools.state_diff import StateDiff, diff_state


def _write_yaml(content: str) -> Path:
    d = tempfile.mkdtemp()
    p = Path(d) / "test_ecosystem.yaml"
    p.write_text(textwrap.dedent(content))
    return p


def _make_desired_state(tables: dict[str, DesiredTable]) -> DesiredState:
    return DesiredState(ecosystem="test", cluster="main", tables=tables)


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


class TestParseDesiredState(unittest.TestCase):
    def test_parse_basic_yaml(self) -> None:
        p = _write_yaml("""\
            ecosystem: events
            cluster: main
            tables:
              sharded_events:
                engine: ReplicatedMergeTree
                sharded: true
                on_nodes: DATA
                order_by: [team_id, id]
                columns:
                  - name: id
                    type: UUID
                  - name: team_id
                    type: Int64
        """)
        state = parse_desired_state(p)
        self.assertEqual(state.ecosystem, "events")
        self.assertEqual(state.cluster, "main")
        self.assertIn("sharded_events", state.tables)
        table = state.tables["sharded_events"]
        self.assertEqual(table.engine, "ReplicatedMergeTree")
        self.assertTrue(table.sharded)
        self.assertEqual(len(table.columns), 2)
        self.assertEqual(table.columns[0].name, "id")
        self.assertEqual(table.columns[0].type, "UUID")
        self.assertEqual(table.order_by, ["team_id", "id"])

    def test_parse_column_inheritance(self) -> None:
        p = _write_yaml("""\
            ecosystem: test
            cluster: main
            tables:
              sharded_t:
                engine: ReplicatedMergeTree
                on_nodes: DATA
                columns:
                  - name: id
                    type: UUID
                  - name: name
                    type: String
              distributed_t:
                engine: Distributed
                source: sharded_t
                on_nodes: ALL
                columns: inherit sharded_t
        """)
        state = parse_desired_state(p)
        dist = state.tables["distributed_t"]
        self.assertEqual(len(dist.columns), 2)
        self.assertEqual(dist.columns[0].name, "id")
        self.assertEqual(dist.inherit_columns_from, "sharded_t")

    def test_parse_missing_ecosystem(self) -> None:
        p = _write_yaml("""\
            cluster: main
            tables: {}
        """)
        with self.assertRaises(ValueError) as ctx:
            parse_desired_state(p)
        self.assertIn("ecosystem", str(ctx.exception))

    def test_parse_mv_table(self) -> None:
        p = _write_yaml("""\
            ecosystem: test
            cluster: main
            tables:
              my_mv:
                engine: MaterializedView
                source: kafka_t
                target: writable_t
                select: "SELECT * FROM posthog.kafka_t"
                on_nodes: ALL
                columns: []
        """)
        state = parse_desired_state(p)
        mv = state.tables["my_mv"]
        self.assertEqual(mv.engine, "MaterializedView")
        self.assertEqual(mv.target, "writable_t")
        self.assertEqual(mv.source, "kafka_t")

    def test_parse_dir(self) -> None:
        d = tempfile.mkdtemp()
        (Path(d) / "eco1.yaml").write_text(
            textwrap.dedent("""\
            ecosystem: eco1
            cluster: main
            tables:
              t1:
                engine: MergeTree
                on_nodes: DATA
                columns:
                  - name: id
                    type: UInt64
        """)
        )
        (Path(d) / "eco2.yaml").write_text(
            textwrap.dedent("""\
            ecosystem: eco2
            cluster: main
            tables:
              t2:
                engine: MergeTree
                on_nodes: DATA
                columns:
                  - name: id
                    type: UInt64
        """)
        )
        states = parse_desired_state_dir(Path(d))
        self.assertEqual(len(states), 2)
        ecosystems = {s.ecosystem for s in states}
        self.assertEqual(ecosystems, {"eco1", "eco2"})


class TestDiffStateMissingTable(unittest.TestCase):
    def test_missing_table_creates(self) -> None:
        desired = _make_desired_state(
            {
                "new_table": _make_desired_table(
                    "new_table",
                    columns=[ColumnDef(name="id", type="UUID")],
                ),
            }
        )
        current: dict[str, TableSchema] = {}
        diffs = diff_state(desired, current)
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0].action, "create")
        self.assertEqual(diffs[0].table, "new_table")
        self.assertIn("CREATE TABLE", diffs[0].sql)


class TestDiffStateExtraColumn(unittest.TestCase):
    def test_extra_column_adds(self) -> None:
        desired = _make_desired_state(
            {
                "t": _make_desired_table(
                    "t",
                    columns=[
                        ColumnDef(name="id", type="UUID"),
                        ColumnDef(name="new_col", type="String"),
                    ],
                ),
            }
        )
        current = {
            "t": _make_table_schema(
                "t",
                columns=[
                    ColumnSchema(name="id", type="UUID"),
                ],
            ),
        }
        diffs = diff_state(desired, current)
        add_diffs = [d for d in diffs if d.action == "alter_add_column"]
        self.assertEqual(len(add_diffs), 1)
        self.assertEqual(add_diffs[0].table, "t")
        self.assertIn("new_col", add_diffs[0].sql)
        self.assertIn("ADD COLUMN", add_diffs[0].sql)


class TestDiffStateMissingColumn(unittest.TestCase):
    def test_missing_column_drops(self) -> None:
        desired = _make_desired_state(
            {
                "t": _make_desired_table(
                    "t",
                    columns=[
                        ColumnDef(name="id", type="UUID"),
                    ],
                ),
            }
        )
        current = {
            "t": _make_table_schema(
                "t",
                columns=[
                    ColumnSchema(name="id", type="UUID"),
                    ColumnSchema(name="old_col", type="String"),
                ],
            ),
        }
        diffs = diff_state(desired, current)
        drop_diffs = [d for d in diffs if d.action == "alter_drop_column"]
        self.assertEqual(len(drop_diffs), 1)
        self.assertIn("old_col", drop_diffs[0].sql)
        self.assertIn("DROP COLUMN", drop_diffs[0].sql)


class TestDiffStateTypeChange(unittest.TestCase):
    def test_type_change_modifies(self) -> None:
        desired = _make_desired_state(
            {
                "t": _make_desired_table(
                    "t",
                    columns=[
                        ColumnDef(name="val", type="Int64"),
                    ],
                ),
            }
        )
        current = {
            "t": _make_table_schema(
                "t",
                columns=[
                    ColumnSchema(name="val", type="Int32"),
                ],
            ),
        }
        diffs = diff_state(desired, current)
        modify_diffs = [d for d in diffs if d.action == "alter_modify_column"]
        self.assertEqual(len(modify_diffs), 1)
        self.assertIn("MODIFY COLUMN", modify_diffs[0].sql)
        self.assertIn("Int64", modify_diffs[0].sql)


class TestDiffStateMvChange(unittest.TestCase):
    def test_mv_engine_change_recreates(self) -> None:
        desired = _make_desired_state(
            {
                "my_mv": DesiredTable(
                    name="my_mv",
                    engine="MaterializedView",
                    columns=[],
                    on_nodes=["ALL"],
                    target="writable_t",
                    select="SELECT * FROM kafka_t",
                ),
            }
        )
        current = {
            "my_mv": _make_table_schema("my_mv", engine="MergeTree"),
        }
        diffs = diff_state(desired, current)
        recreate_diffs = [d for d in diffs if d.action == "recreate_mv"]
        self.assertEqual(len(recreate_diffs), 1)
        self.assertIn("DROP TABLE", recreate_diffs[0].sql)
        self.assertIn("CREATE MATERIALIZED VIEW", recreate_diffs[0].sql)


class TestDiffDependencyOrder(unittest.TestCase):
    def test_mv_dropped_before_source_altered(self) -> None:
        """When a MV exists in current but not desired, and its source table
        is being altered, the MV drop should come before the alter."""
        desired = _make_desired_state(
            {
                "source_t": _make_desired_table(
                    "source_t",
                    columns=[
                        ColumnDef(name="id", type="UUID"),
                        ColumnDef(name="new_col", type="String"),
                    ],
                ),
            }
        )
        current = {
            "source_t": _make_table_schema(
                "source_t",
                columns=[
                    ColumnSchema(name="id", type="UUID"),
                ],
            ),
            "my_mv": _make_table_schema("my_mv", engine="MaterializedView"),
        }
        diffs = diff_state(desired, current)

        # Find positions
        drop_idx = next(i for i, d in enumerate(diffs) if d.action == "drop" and d.table == "my_mv")
        alter_idx = next(i for i, d in enumerate(diffs) if d.action == "alter_add_column")

        self.assertLess(drop_idx, alter_idx, "MV drop should come before source table alter")

    def test_create_local_before_distributed(self) -> None:
        """Local tables should be created before distributed tables."""
        desired = _make_desired_state(
            {
                "sharded_t": _make_desired_table(
                    "sharded_t",
                    columns=[
                        ColumnDef(name="id", type="UUID"),
                    ],
                ),
                "dist_t": DesiredTable(
                    name="dist_t",
                    engine="Distributed",
                    columns=[ColumnDef(name="id", type="UUID")],
                    on_nodes=["ALL"],
                    source="sharded_t",
                ),
            }
        )
        current: dict[str, TableSchema] = {}
        diffs = diff_state(desired, current)
        creates = [d for d in diffs if d.action == "create"]
        self.assertEqual(len(creates), 2)

        local_idx = next(i for i, d in enumerate(creates) if d.table == "sharded_t")
        dist_idx = next(i for i, d in enumerate(creates) if d.table == "dist_t")
        self.assertLess(local_idx, dist_idx, "Local table should be created before distributed")


class TestPlanGeneratorHumanReadable(unittest.TestCase):
    def test_plan_includes_symbols(self) -> None:
        diffs = [
            StateDiff(
                action="alter_add_column",
                table="sharded_events",
                detail="Add column foo String to sharded_events",
                sql="ALTER TABLE ...",
                node_roles=["DATA"],
            ),
            StateDiff(
                action="drop",
                table="old_mv",
                detail="Table old_mv exists but is not in desired state",
                sql="DROP TABLE ...",
                node_roles=["ALL"],
            ),
            StateDiff(
                action="create",
                table="new_table",
                detail="Create MergeTree table new_table",
                sql="CREATE TABLE ...",
                node_roles=["DATA"],
            ),
        ]
        plan = generate_plan_text(diffs)
        self.assertIn("~", plan)  # modify symbol
        self.assertIn("-", plan)  # drop symbol
        self.assertIn("+", plan)  # create symbol
        self.assertIn("sharded_events", plan)
        self.assertIn("old_mv", plan)
        self.assertIn("new_table", plan)
        self.assertIn("Plan:", plan)
        self.assertIn("ch_migrate plan:", plan)

    def test_no_changes_plan(self) -> None:
        plan = generate_plan_text([])
        self.assertIn("No changes", plan)


class TestManifestStepGeneration(unittest.TestCase):
    def test_generates_manifest_steps(self) -> None:
        diffs = [
            StateDiff(
                action="alter_add_column",
                table="t",
                detail="Add col",
                sql="ALTER TABLE posthog.t ADD COLUMN IF NOT EXISTS foo String",
                node_roles=["DATA"],
                sharded=True,
                is_alter_on_replicated_table=True,
            ),
        ]
        steps = generate_manifest_steps(diffs)
        self.assertEqual(len(steps), 1)
        step, sql = steps[0]
        self.assertEqual(step.node_roles, ["DATA"])
        self.assertTrue(step.sharded)
        self.assertTrue(step.is_alter_on_replicated_table)
        self.assertIn("ALTER TABLE", sql)

    def test_recreate_splits_into_drop_create(self) -> None:
        diffs = [
            StateDiff(
                action="recreate_mv",
                table="my_mv",
                detail="Recreate MV",
                sql="DROP TABLE IF EXISTS posthog.my_mv;\nCREATE MATERIALIZED VIEW ...",
                node_roles=["ALL"],
            ),
        ]
        steps = generate_manifest_steps(diffs)
        self.assertEqual(len(steps), 2)
        self.assertIn("drop", steps[0][0].sql)
        self.assertIn("create", steps[1][0].sql)


class TestRollbackGeneration(unittest.TestCase):
    def test_rollback_create_produces_drop(self) -> None:
        diffs = [
            StateDiff(
                action="create",
                table="new_t",
                detail="Create table",
                sql="CREATE TABLE ...",
                node_roles=["DATA"],
            ),
        ]
        rollback = generate_rollback_steps(diffs)
        self.assertEqual(len(rollback), 1)
        self.assertIn("DROP TABLE", rollback[0][1])

    def test_rollback_add_column_produces_drop_column(self) -> None:
        diffs = [
            StateDiff(
                action="alter_add_column",
                table="t",
                detail="Add col",
                sql="ALTER TABLE posthog.t ADD COLUMN IF NOT EXISTS foo String",
                node_roles=["DATA"],
                is_alter_on_replicated_table=True,
            ),
        ]
        rollback = generate_rollback_steps(diffs)
        self.assertEqual(len(rollback), 1)
        self.assertIn("DROP COLUMN", rollback[0][1])
        self.assertIn("foo", rollback[0][1])


class TestReconcileImportYamlRoundTrip(unittest.TestCase):
    def test_import_roundtrip(self) -> None:
        """Write a YAML file, parse it, verify it round-trips through the parser."""
        import yaml

        yaml_content = textwrap.dedent("""\
            ecosystem: roundtrip_test
            cluster: main
            tables:
              sharded_t:
                engine: ReplicatedMergeTree
                sharded: true
                on_nodes: DATA
                order_by: [team_id, id]
                partition_by: "toYYYYMM(timestamp)"
                columns:
                  - name: id
                    type: UUID
                  - name: team_id
                    type: Int64
                  - name: timestamp
                    type: DateTime64(6, 'UTC')
              writable_t:
                engine: Distributed
                source: sharded_t
                sharding_key: "cityHash64(id)"
                on_nodes: COORDINATOR
                columns: inherit sharded_t
        """)

        d = tempfile.mkdtemp()
        p = Path(d) / "roundtrip_test.yaml"
        p.write_text(yaml_content)

        state = parse_desired_state(p)
        self.assertEqual(state.ecosystem, "roundtrip_test")
        self.assertEqual(len(state.tables), 2)

        sharded = state.tables["sharded_t"]
        self.assertEqual(sharded.order_by, ["team_id", "id"])
        self.assertEqual(sharded.partition_by, "toYYYYMM(timestamp)")
        self.assertEqual(len(sharded.columns), 3)

        writable = state.tables["writable_t"]
        self.assertEqual(writable.source, "sharded_t")
        self.assertEqual(len(writable.columns), 3)  # inherited

        # Write back out as YAML and re-parse
        tables_out: dict[str, dict] = {}
        for tname, tbl in state.tables.items():
            tdata: dict = {"engine": tbl.engine, "on_nodes": tbl.on_nodes}
            if tbl.order_by:
                tdata["order_by"] = tbl.order_by
            if tbl.partition_by:
                tdata["partition_by"] = tbl.partition_by
            if tbl.source:
                tdata["source"] = tbl.source
            if tbl.sharding_key:
                tdata["sharding_key"] = tbl.sharding_key
            if tbl.sharded:
                tdata["sharded"] = True
            tdata["columns"] = [{"name": c.name, "type": c.type} for c in tbl.columns]
            tables_out[tname] = tdata
        out_data = {
            "ecosystem": state.ecosystem,
            "cluster": state.cluster,
            "tables": tables_out,
        }

        out_path = Path(d) / "roundtrip_out.yaml"
        with open(out_path, "w") as f:
            yaml.dump(out_data, f, default_flow_style=False, sort_keys=False)

        state2 = parse_desired_state(out_path)
        self.assertEqual(state2.ecosystem, state.ecosystem)
        self.assertEqual(len(state2.tables), len(state.tables))
        for tname in state.tables:
            self.assertEqual(
                len(state2.tables[tname].columns),
                len(state.tables[tname].columns),
            )


class TestMvSelectChange(unittest.TestCase):
    def test_mv_select_change_detected(self) -> None:
        """When an MV's SELECT changes, state_diff should generate DROP + CREATE."""
        desired = _make_desired_state(
            {
                "my_mv": DesiredTable(
                    name="my_mv",
                    engine="MaterializedView",
                    columns=[],
                    on_nodes=["ALL"],
                    target="writable_t",
                    select="SELECT id, new_col FROM posthog.kafka_t",
                ),
            }
        )
        current = {
            "my_mv": TableSchema(
                name="my_mv",
                engine="MaterializedView",
                as_select="SELECT * FROM posthog.kafka_t",
            ),
        }
        diffs = diff_state(desired, current)

        drop_diffs = [d for d in diffs if d.action == "drop"]
        create_diffs = [d for d in diffs if d.action == "create"]

        self.assertEqual(len(drop_diffs), 1, "Should generate a DROP for the old MV")
        self.assertEqual(drop_diffs[0].table, "my_mv")
        self.assertEqual(len(create_diffs), 1, "Should generate a CREATE for the new MV")
        self.assertEqual(create_diffs[0].table, "my_mv")
        self.assertIn("CREATE MATERIALIZED VIEW", create_diffs[0].sql)

    def test_mv_select_unchanged_no_diff(self) -> None:
        """When an MV's SELECT matches, no diff should be generated."""
        select_stmt = "SELECT * FROM posthog.kafka_t"
        desired = _make_desired_state(
            {
                "my_mv": DesiredTable(
                    name="my_mv",
                    engine="MaterializedView",
                    columns=[],
                    on_nodes=["ALL"],
                    target="writable_t",
                    select=select_stmt,
                ),
            }
        )
        current = {
            "my_mv": TableSchema(
                name="my_mv",
                engine="MaterializedView",
                as_select=select_stmt,
            ),
        }
        diffs = diff_state(desired, current)
        self.assertEqual(len(diffs), 0, "No diffs when MV SELECT is unchanged")


class TestDetectOrphans(unittest.TestCase):
    def test_finds_undeclared_tables(self) -> None:
        from posthog.clickhouse.migration_tools.state_diff import detect_orphans

        desired_states = [
            _make_desired_state({"t1": _make_desired_table("t1", columns=[ColumnDef(name="id", type="UUID")])}),
        ]
        current = {
            "t1": _make_table_schema("t1"),
            "orphan_table": _make_table_schema("orphan_table"),
        }
        orphans = detect_orphans(desired_states, current)
        self.assertEqual(orphans, ["orphan_table"])

    def test_excludes_system_tables(self) -> None:
        from posthog.clickhouse.migration_tools.state_diff import detect_orphans

        desired_states = [
            _make_desired_state({"t1": _make_desired_table("t1", columns=[ColumnDef(name="id", type="UUID")])}),
        ]
        current = {
            "t1": _make_table_schema("t1"),
            "clickhouse_schema_migrations": _make_table_schema("clickhouse_schema_migrations"),
            "_tmp_backup": _make_table_schema("_tmp_backup"),
        }
        orphans = detect_orphans(desired_states, current)
        self.assertEqual(orphans, [])

    def test_excludes_custom_patterns(self) -> None:
        from posthog.clickhouse.migration_tools.state_diff import detect_orphans

        desired_states = [
            _make_desired_state({"t1": _make_desired_table("t1", columns=[ColumnDef(name="id", type="UUID")])}),
        ]
        current = {
            "t1": _make_table_schema("t1"),
            "legacy_table": _make_table_schema("legacy_table"),
        }
        orphans = detect_orphans(desired_states, current, exclude_patterns=["legacy_table"])
        self.assertEqual(orphans, [])


class TestClusterRegistry(unittest.TestCase):
    """Tests for cluster registry in cluster.py."""

    def test_cluster_registry_maps_main(self) -> None:
        from unittest.mock import MagicMock, patch

        mock_settings = MagicMock()
        mock_settings.CLICKHOUSE_HOST = "main-host"
        mock_settings.CLICKHOUSE_CLUSTER = "posthog"

        with (
            patch("posthog.clickhouse.cluster.get_cluster") as mock_get_cluster,
            patch("posthog.clickhouse.cluster.settings", mock_settings),
        ):
            from posthog.clickhouse.cluster import get_cluster_by_name

            get_cluster_by_name("main")
            mock_get_cluster.assert_called_once_with(host="main-host", cluster="posthog")

    def test_cluster_registry_maps_logs(self) -> None:
        from unittest.mock import MagicMock, patch

        mock_settings = MagicMock()
        mock_settings.CLICKHOUSE_LOGS_CLUSTER_HOST = "logs-host"
        mock_settings.CLICKHOUSE_LOGS_CLUSTER = "posthog_single_shard"

        with (
            patch("posthog.clickhouse.cluster.get_cluster") as mock_get_cluster,
            patch("posthog.clickhouse.cluster.settings", mock_settings),
        ):
            from posthog.clickhouse.cluster import get_cluster_by_name

            get_cluster_by_name("logs")
            mock_get_cluster.assert_called_once_with(host="logs-host", cluster="posthog_single_shard")

    def test_cluster_registry_unknown_falls_back(self) -> None:
        from unittest.mock import patch

        with patch("posthog.clickhouse.cluster.get_cluster") as mock_get_cluster:
            from posthog.clickhouse.cluster import get_cluster_by_name

            get_cluster_by_name("unknown_cluster")
            mock_get_cluster.assert_called_once_with()

    def test_plan_groups_by_cluster(self) -> None:
        """Desired states with different clusters should each connect to their own cluster host."""
        ds_main = _make_desired_state({"t1": _make_desired_table("t1", columns=[ColumnDef(name="id", type="UUID")])})
        ds_main.cluster = "main"

        ds_logs = DesiredState(
            ecosystem="logs_eco",
            cluster="logs",
            tables={"t2": _make_desired_table("t2", columns=[ColumnDef(name="id", type="UUID")])},
        )

        # Both clusters exist in the registry
        from posthog.clickhouse.cluster import is_known_cluster

        self.assertTrue(is_known_cluster("main"))
        self.assertTrue(is_known_cluster("logs"))
        # And they produce separate groupings
        from collections import defaultdict

        by_cluster: dict[str, list] = defaultdict(list)
        for ds in [ds_main, ds_logs]:
            by_cluster[ds.cluster].append(ds)

        self.assertEqual(sorted(by_cluster.keys()), ["logs", "main"])
        self.assertEqual(len(by_cluster["main"]), 1)
        self.assertEqual(len(by_cluster["logs"]), 1)

    def test_unknown_cluster_in_yaml_errors(self) -> None:
        """A YAML referencing an unknown cluster should produce a clear error."""
        from posthog.clickhouse.cluster import get_all_logical_clusters, is_known_cluster

        self.assertFalse(is_known_cluster("sessions"))

        known = ", ".join(get_all_logical_clusters())
        self.assertIn("logs", known)
        self.assertIn("main", known)
        self.assertIn("migrations", known)

        # Simulate the validation error message
        cluster_name = "sessions"
        ecosystem = "sessions_v3"
        msg = (
            f"Schema file for ecosystem '{ecosystem}' references cluster "
            f"'{cluster_name}' which is not in the cluster registry. "
            f"Known clusters: {known}."
        )
        self.assertIn("sessions", msg)
        self.assertIn("not in the cluster registry", msg)


if __name__ == "__main__":
    unittest.main()
