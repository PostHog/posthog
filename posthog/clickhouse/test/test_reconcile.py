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

    def test_cluster_registry_unknown_raises(self) -> None:
        """Unknown logical cluster names must raise instead of silently
        falling back — silent fallback masks bugs where callers mis-spell
        or forget to register a new cluster."""
        from posthog.clickhouse.cluster import get_cluster_by_name

        with self.assertRaises(ValueError) as cm:
            get_cluster_by_name("unknown_cluster")
        self.assertIn("unknown_cluster", str(cm.exception))
        self.assertIn("Known clusters:", str(cm.exception))

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
        """A YAML referencing a truly unknown cluster should produce a clear
        error. `sessions`, `aux`, `ops`, and `ai_events` are now registered
        as satellite clusters, so this test uses a synthetic name."""
        from posthog.clickhouse.cluster import get_all_logical_clusters, is_known_cluster

        # Satellite clusters are now registered — they must resolve.
        self.assertTrue(is_known_cluster("sessions"))
        self.assertTrue(is_known_cluster("aux"))

        # A name that is NOT registered must still be flagged.
        self.assertFalse(is_known_cluster("definitely_not_a_cluster"))

        known = ", ".join(get_all_logical_clusters())
        self.assertIn("logs", known)
        self.assertIn("main", known)
        self.assertIn("migrations", known)
        self.assertIn("sessions", known)


if __name__ == "__main__":
    unittest.main()


class TestStructuralFieldDiffs(unittest.TestCase):
    """Tests for High #1 fix: state_diff compares structural fields."""

    def test_order_by_change_triggers_recreate(self) -> None:
        desired = _make_desired_state(
            {
                "t": _make_desired_table(
                    "t",
                    engine="ReplicatedMergeTree",
                    order_by=["a", "b"],
                    columns=[ColumnDef(name="a", type="String"), ColumnDef(name="b", type="String")],
                ),
            }
        )
        current = {
            "t": TableSchema(name="t", engine="ReplicatedMergeTree", sorting_key="a"),
        }
        diffs = diff_state(desired, current)
        recreate_diffs = [d for d in diffs if d.action == "recreate"]
        self.assertEqual(len(recreate_diffs), 1)
        self.assertIn("ORDER BY", recreate_diffs[0].detail)

    def test_partition_by_change_triggers_recreate(self) -> None:
        desired = _make_desired_state(
            {
                "t": _make_desired_table(
                    "t",
                    engine="ReplicatedMergeTree",
                    partition_by="toYYYYMM(created_at)",
                    columns=[ColumnDef(name="created_at", type="DateTime")],
                ),
            }
        )
        current = {
            "t": TableSchema(name="t", engine="ReplicatedMergeTree", partition_key="toYYYYMMDD(created_at)"),
        }
        diffs = diff_state(desired, current)
        recreate_diffs = [d for d in diffs if d.action == "recreate"]
        self.assertEqual(len(recreate_diffs), 1)
        self.assertIn("PARTITION BY", recreate_diffs[0].detail)

    def test_distributed_source_change_triggers_recreate(self) -> None:
        desired = _make_desired_state(
            {
                "dist_t": DesiredTable(
                    name="dist_t",
                    engine="Distributed",
                    columns=[ColumnDef(name="id", type="UUID")],
                    on_nodes=["ALL"],
                    source="new_sharded_t",
                    sharding_key="rand()",
                ),
            }
        )
        current = {
            "dist_t": TableSchema(
                name="dist_t",
                engine="Distributed",
                engine_full="Distributed('posthog', 'posthog', 'old_sharded_t', rand())",
            ),
        }
        diffs = diff_state(desired, current)
        recreate_diffs = [d for d in diffs if d.action == "recreate"]
        self.assertEqual(len(recreate_diffs), 1)
        self.assertIn("source table changed", recreate_diffs[0].detail)

    def test_kafka_setting_change_triggers_recreate(self) -> None:
        desired = _make_desired_state(
            {
                "kafka_t": _make_desired_table(
                    "kafka_t",
                    engine="Kafka",
                    columns=[ColumnDef(name="id", type="UUID")],
                    settings={"kafka_broker_list": "new-broker:9092", "kafka_topic_list": "events"},
                ),
            }
        )
        current = {
            "kafka_t": TableSchema(
                name="kafka_t",
                engine="Kafka",
                engine_full="Kafka('old-broker:9092', 'events', 'group1', 'JSONEachRow')",
            ),
        }
        diffs = diff_state(desired, current)
        # Kafka column changes trigger drop+create, but structural changes trigger recreate
        recreate_diffs = [d for d in diffs if d.action == "recreate"]
        self.assertEqual(len(recreate_diffs), 1)
        self.assertIn("kafka_broker_list", recreate_diffs[0].detail)

    def test_column_default_change_triggers_modify(self) -> None:
        desired = _make_desired_state(
            {
                "t": _make_desired_table(
                    "t",
                    columns=[
                        ColumnDef(name="val", type="Int64", default_kind="DEFAULT", default_expression="0"),
                    ],
                ),
            }
        )
        current = {
            "t": _make_table_schema(
                "t",
                columns=[
                    ColumnSchema(name="val", type="Int64", default_kind="DEFAULT", default_expression="42"),
                ],
            ),
        }
        diffs = diff_state(desired, current)
        modify_diffs = [d for d in diffs if d.action == "alter_modify_column"]
        self.assertEqual(len(modify_diffs), 1)
        self.assertIn("default", modify_diffs[0].detail.lower())

    def test_no_recreate_when_structural_fields_match(self) -> None:
        """No structural diff when order_by/partition_by match current."""
        desired = _make_desired_state(
            {
                "t": _make_desired_table(
                    "t",
                    engine="ReplicatedMergeTree",
                    order_by=["a"],
                    partition_by="toYYYYMM(ts)",
                    columns=[ColumnDef(name="a", type="String"), ColumnDef(name="ts", type="DateTime")],
                ),
            }
        )
        current = {
            "t": TableSchema(
                name="t",
                engine="ReplicatedMergeTree",
                sorting_key="a",
                partition_key="toYYYYMM(ts)",
            ),
        }
        diffs = diff_state(desired, current)
        # Only column adds since current has no columns defined
        recreate_diffs = [d for d in diffs if d.action in ("recreate", "recreate_mv")]
        self.assertEqual(len(recreate_diffs), 0)


class TestReplicatedEngineExplicitZkPath(unittest.TestCase):
    """Regression tests for the P0 `{uuid}` macro bug found in 2026-04-10 e2e run.

    Before the fix, `_generate_create_sql` emitted zero-arg Replicated* engines
    like `ReplicatedReplacingMergeTree()`. ClickHouse falls back to a default
    zk_path containing `{uuid}`, which only resolves inside `ON CLUSTER` queries
    or Replicated database engines. Since the runner sends CREATE statements
    directly to each host via `map_hosts_by_roles()`, the macro was unresolvable
    and apply failed on the very first table with:

        Code: 36. DB::Exception: Macro 'uuid' in engine arguments is only
        supported when the UUID is explicitly specified, used within an ON
        CLUSTER query, or when using the Replicated database engine.

    The fix emits explicit (zk_path, replica_name) args for every Replicated*
    engine, matching the convention used by `tracking.py` and legacy PostHog
    migrations.
    """

    def _make_table(self, name: str, engine: str) -> DesiredTable:
        return DesiredTable(
            name=name,
            engine=engine,
            columns=[ColumnDef(name="id", type="UUID"), ColumnDef(name="team_id", type="Int64")],
            on_nodes=["DATA"],
            order_by=["team_id", "id"],
        )

    def test_replicated_merge_tree_has_explicit_zk_path(self) -> None:
        from posthog.clickhouse.migration_tools.state_diff import _generate_create_sql

        table = self._make_table("events_raw", "ReplicatedMergeTree")
        sql = _generate_create_sql(table, database="posthog", cluster="main")
        self.assertIn("ReplicatedMergeTree(", sql)
        self.assertIn("'/clickhouse/tables/{shard}/posthog/events_raw'", sql)
        self.assertIn("'{replica}'", sql)
        self.assertNotIn("ReplicatedMergeTree()", sql)

    def test_replicated_replacing_merge_tree_has_explicit_zk_path(self) -> None:
        """The actual engine/table that broke on 2026-04-10 — adhoc_events_deletion."""
        from posthog.clickhouse.migration_tools.state_diff import _generate_create_sql

        table = self._make_table("adhoc_events_deletion", "ReplicatedReplacingMergeTree")
        sql = _generate_create_sql(table, database="posthog_test", cluster="main")
        self.assertIn("ReplicatedReplacingMergeTree(", sql)
        self.assertIn("'/clickhouse/tables/{shard}/posthog_test/adhoc_events_deletion'", sql)
        self.assertIn("'{replica}'", sql)
        self.assertNotIn("ReplicatedReplacingMergeTree()", sql)

    def test_replicated_variants_all_emit_explicit_zk_path(self) -> None:
        from posthog.clickhouse.migration_tools.state_diff import _generate_create_sql

        for engine in (
            "ReplicatedAggregatingMergeTree",
            "ReplicatedSummingMergeTree",
            "ReplicatedCollapsingMergeTree",
        ):
            sql = _generate_create_sql(
                self._make_table("t", engine),
                database="posthog",
                cluster="main",
            )
            self.assertIn(
                "'/clickhouse/tables/{shard}/posthog/t'",
                sql,
                f"{engine} missing explicit zk_path",
            )
            self.assertIn("'{replica}'", sql, f"{engine} missing replica macro")
            self.assertNotIn(f"{engine}()", sql, f"{engine} still emits zero-arg form")

    def test_non_replicated_merge_tree_has_no_zk_path(self) -> None:
        """Plain (unreplicated) MergeTree must stay zero-arg — no zk_path."""
        from posthog.clickhouse.migration_tools.state_diff import _generate_create_sql

        table = self._make_table("local_t", "MergeTree")
        sql = _generate_create_sql(table, database="posthog", cluster="main")
        self.assertIn("ENGINE = MergeTree()", sql)
        self.assertNotIn("/clickhouse/tables/", sql)
        self.assertNotIn("{replica}", sql)


class TestDistributedClusterResolution(unittest.TestCase):
    """Regression tests for the P1 Distributed cluster name mismatch found in
    Round 4 e2e (2026-04-10). Before the fix, `_generate_create_sql` embedded
    the YAML logical cluster name (e.g. 'main') directly into the Distributed
    engine SQL. On dev stacks where the physical CH cluster is named
    'posthog_migrations' (not 'main'), apply failed with:
        Code: 701. DB::Exception: Requested cluster 'main' not found.
    The fix resolves logical -> physical cluster name via _CLUSTER_REGISTRY.
    """

    def test_distributed_uses_physical_cluster_name(self) -> None:
        from posthog.clickhouse.migration_tools.state_diff import _generate_create_sql

        table = DesiredTable(
            name="events_dist",
            engine="Distributed",
            columns=[ColumnDef(name="id", type="UUID")],
            on_nodes=["ALL"],
            source="sharded_events",
            sharding_key="cityHash64(distinct_id)",
        )
        sql = _generate_create_sql(table, database="posthog", cluster="main")
        # 'main' should resolve to settings.CLICKHOUSE_CLUSTER (test stub: 'posthog')
        self.assertIn("Distributed('posthog',", sql)
        self.assertNotIn("Distributed('main',", sql)

    def test_distributed_unknown_cluster_passes_through(self) -> None:
        from posthog.clickhouse.migration_tools.state_diff import _generate_create_sql

        table = DesiredTable(
            name="events_dist",
            engine="Distributed",
            columns=[ColumnDef(name="id", type="UUID")],
            on_nodes=["ALL"],
            source="sharded_events",
            sharding_key="rand()",
        )
        sql = _generate_create_sql(table, database="posthog", cluster="unknown_thing")
        self.assertIn("Distributed('unknown_thing',", sql)

    def test_distributed_satellite_cluster_resolves(self) -> None:
        from posthog.clickhouse.migration_tools.state_diff import _generate_create_sql

        table = DesiredTable(
            name="sessions_dist",
            engine="Distributed",
            columns=[ColumnDef(name="id", type="UUID")],
            on_nodes=["ALL"],
            source="sharded_sessions",
            sharding_key="rand()",
        )
        sql = _generate_create_sql(table, database="posthog", cluster="sessions")
        # 'sessions' should resolve to CLICKHOUSE_SESSIONS_CLUSTER (test stub: 'posthog_sessions')
        self.assertIn("Distributed('posthog_sessions',", sql)


class TestKafkaRecreateWarning(unittest.TestCase):
    """Tests for High #2 fix: Kafka DROP+CREATE operator warning."""

    def test_plan_emits_kafka_warning_on_recreate(self) -> None:
        diffs = [
            StateDiff(
                action="recreate",
                table="kafka_events_json",
                detail="Recreate kafka_events_json (Kafka setting changed)",
                sql="DROP TABLE IF EXISTS posthog.kafka_events_json;\nCREATE TABLE ...",
                node_roles=["ALL"],
            ),
        ]
        plan = generate_plan_text(diffs)
        self.assertIn("KAFKA TABLE RECREATE WARNING", plan)
        self.assertIn("ingestion will pause", plan)
        self.assertIn("kafka_events_json", plan)

    def test_plan_no_kafka_warning_for_non_kafka_table(self) -> None:
        diffs = [
            StateDiff(
                action="recreate",
                table="sharded_events",
                detail="Recreate sharded_events",
                sql="DROP TABLE IF EXISTS posthog.sharded_events;\nCREATE TABLE ...",
                node_roles=["DATA"],
            ),
        ]
        plan = generate_plan_text(diffs)
        self.assertNotIn("KAFKA TABLE RECREATE WARNING", plan)

    def test_plan_kafka_warning_on_drop(self) -> None:
        diffs = [
            StateDiff(
                action="drop",
                table="kafka_session_recording",
                detail="Drop Kafka table for recreation",
                sql="DROP TABLE IF EXISTS posthog.kafka_session_recording",
                node_roles=["ALL"],
            ),
        ]
        plan = generate_plan_text(diffs)
        self.assertIn("KAFKA TABLE RECREATE WARNING", plan)


class TestMvSelectNormalization(unittest.TestCase):
    """Tests for High #3 fix: MV SELECT normalization."""

    def test_mv_select_whitespace_only_no_diff(self) -> None:
        """Whitespace-only differences should not trigger a recreate."""
        desired = _make_desired_state(
            {
                "my_mv": DesiredTable(
                    name="my_mv",
                    engine="MaterializedView",
                    columns=[],
                    on_nodes=["ALL"],
                    target="writable_t",
                    select="SELECT * FROM posthog.kafka_t",
                ),
            }
        )
        current = {
            "my_mv": TableSchema(
                name="my_mv",
                engine="MaterializedView",
                as_select="SELECT *\n  FROM   posthog.kafka_t\n",
            ),
        }
        diffs = diff_state(desired, current)
        drop_diffs = [d for d in diffs if d.action == "drop"]
        create_diffs = [d for d in diffs if d.action == "create"]
        self.assertEqual(len(drop_diffs), 0, "No DROP for whitespace-only MV SELECT change")
        self.assertEqual(len(create_diffs), 0, "No CREATE for whitespace-only MV SELECT change")

    def test_mv_select_keyword_case_no_diff(self) -> None:
        """Keyword case differences should not trigger a recreate."""
        desired = _make_desired_state(
            {
                "my_mv": DesiredTable(
                    name="my_mv",
                    engine="MaterializedView",
                    columns=[],
                    on_nodes=["ALL"],
                    target="writable_t",
                    select="select a, b from t where c = 1",
                ),
            }
        )
        current = {
            "my_mv": TableSchema(
                name="my_mv",
                engine="MaterializedView",
                as_select="SELECT a, b FROM t WHERE c = 1",
            ),
        }
        diffs = diff_state(desired, current)
        self.assertEqual(len(diffs), 0, "No diffs for keyword case changes in MV SELECT")

    def test_mv_select_real_change_still_detected(self) -> None:
        """Actual semantic changes should still trigger a recreate."""
        desired = _make_desired_state(
            {
                "my_mv": DesiredTable(
                    name="my_mv",
                    engine="MaterializedView",
                    columns=[],
                    on_nodes=["ALL"],
                    target="writable_t",
                    select="SELECT a, b, c FROM posthog.kafka_t",
                ),
            }
        )
        current = {
            "my_mv": TableSchema(
                name="my_mv",
                engine="MaterializedView",
                as_select="SELECT a, b FROM posthog.kafka_t",
            ),
        }
        diffs = diff_state(desired, current)
        drop_diffs = [d for d in diffs if d.action == "drop"]
        create_diffs = [d for d in diffs if d.action == "create"]
        self.assertEqual(len(drop_diffs), 1, "Should DROP old MV")
        self.assertEqual(len(create_diffs), 1, "Should CREATE new MV")

    def test_normalize_mv_select_function(self) -> None:
        """Direct test of the normalization function."""
        from posthog.clickhouse.migration_tools.state_diff import _normalize_mv_select

        a = "SELECT a, b\nFROM t\nWHERE c = 1"
        b = "SELECT a, b FROM t WHERE c = 1"
        self.assertEqual(_normalize_mv_select(a), _normalize_mv_select(b))

        c = "select a from t"
        d = "SELECT a FROM t"
        self.assertEqual(_normalize_mv_select(c), _normalize_mv_select(d))

        e = "SELECT a FROM t -- comment\nWHERE 1=1"
        f = "SELECT a FROM t WHERE 1=1"
        self.assertEqual(_normalize_mv_select(e), _normalize_mv_select(f))


class TestCheckLegacyMigrations(unittest.TestCase):
    def test_check_queries_correct_legacy_table(self) -> None:
        import inspect

        from posthog.clickhouse.migration_tools import runner

        source = inspect.getsource(runner)
        assert "infi_clickhouse_orm_migrations" in source
        assert "name = 'clickhouseorm_migrations'" not in source


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


class TestDetectDrift(unittest.TestCase):
    def test_drift_groups_by_role(self) -> None:
        """detect_drift should compare hosts within the same role, not across roles."""
        import inspect

        from posthog.clickhouse.migration_tools import schema_introspect

        source = inspect.getsource(schema_introspect.detect_drift)
        assert "host_cluster_role" in source, "detect_drift must group hosts by role"


class TestCircularInheritance(unittest.TestCase):
    """F13: _parse_columns must detect circular inheritance and raise ValueError."""

    def test_circular_inheritance_raises_value_error(self) -> None:
        """A -> B -> A should raise ValueError, not RecursionError."""
        p = _write_yaml("""\
            ecosystem: test
            cluster: main
            tables:
              table_a:
                engine: ReplicatedMergeTree
                on_nodes: DATA
                order_by: [id]
                columns: inherit table_b
              table_b:
                engine: ReplicatedMergeTree
                on_nodes: DATA
                order_by: [id]
                columns: inherit table_a
        """)
        with self.assertRaises(ValueError) as ctx:
            parse_desired_state(p)
        self.assertIn("Circular", str(ctx.exception))

    def test_non_circular_chain_works(self) -> None:
        """A -> B (no cycle) should resolve columns normally."""
        p = _write_yaml("""\
            ecosystem: test
            cluster: main
            tables:
              base:
                engine: ReplicatedMergeTree
                on_nodes: DATA
                order_by: [id]
                columns:
                  - name: id
                    type: UUID
              derived:
                engine: Distributed
                source: base
                on_nodes: ALL
                columns: inherit base
        """)
        state = parse_desired_state(p)
        self.assertEqual(len(state.tables["derived"].columns), 1)
        self.assertEqual(state.tables["derived"].columns[0].name, "id")


class TestKafkaFallbackWarning(unittest.TestCase):
    """F5: _resolve_setting must log a warning when Django setting is unset."""

    def test_warning_when_kafka_setting_unset(self) -> None:
        from unittest.mock import patch

        from posthog.clickhouse.migration_tools.state_diff import _resolve_setting

        with patch("posthog.clickhouse.migration_tools.state_diff.django_settings") as mock_settings:
            # Simulate missing KAFKA_HOSTS_FOR_CLICKHOUSE
            del mock_settings.KAFKA_HOSTS_FOR_CLICKHOUSE
            mock_settings.configure_mock(**{})
            with self.assertLogs("migrations", level="WARNING") as cm:
                result = _resolve_setting("kafka_broker_list")
        self.assertEqual(result, "kafka:9092")
        self.assertTrue(any("unset" in msg for msg in cm.output))

    def test_no_warning_when_setting_configured(self) -> None:
        from unittest.mock import patch

        from posthog.clickhouse.migration_tools.state_diff import _resolve_setting

        with patch("posthog.clickhouse.migration_tools.state_diff.django_settings") as mock_settings:
            mock_settings.KAFKA_HOSTS_FOR_CLICKHOUSE = ["broker1:9092", "broker2:9092"]
            result = _resolve_setting("kafka_broker_list")
        self.assertEqual(result, "broker1:9092,broker2:9092")


class TestMergetreeOrderByLint(unittest.TestCase):
    """F7: MergeTree tables without ORDER BY must produce a lint error."""

    def test_mergetree_without_order_by_errors(self) -> None:
        from posthog.clickhouse.migration_tools.validator import validate_desired_states

        state = DesiredState(
            ecosystem="test",
            cluster="main",
            tables={
                "bad_table": DesiredTable(
                    name="bad_table",
                    engine="ReplicatedMergeTree",
                    columns=[ColumnDef(name="id", type="UUID")],
                    on_nodes=["DATA"],
                    order_by=None,
                ),
            },
        )
        errors = validate_desired_states([state])
        order_by_errors = [e for e in errors if "ORDER BY" in e]
        self.assertTrue(len(order_by_errors) > 0, f"Expected ORDER BY error, got: {errors}")

    def test_mergetree_with_order_by_passes(self) -> None:
        from posthog.clickhouse.migration_tools.validator import validate_desired_states

        state = DesiredState(
            ecosystem="test",
            cluster="main",
            tables={
                "good_table": DesiredTable(
                    name="good_table",
                    engine="ReplicatedMergeTree",
                    columns=[ColumnDef(name="id", type="UUID")],
                    on_nodes=["DATA"],
                    order_by=["id"],
                ),
            },
        )
        errors = validate_desired_states([state])
        order_by_errors = [e for e in errors if "ORDER BY" in e]
        self.assertEqual(len(order_by_errors), 0, f"Unexpected ORDER BY error: {errors}")


class TestSatelliteRoleLint(unittest.TestCase):
    """P1-D: Satellite roles (LOGS, AUX, SESSIONS, OPS, AI_EVENTS, SHUFFLEHOG,
    ENDPOINTS) must pass cross-cluster targeting lint for Distributed, Kafka,
    and MV engines. Earlier `_EXPECTED_ROLES` only listed COORDINATOR/ALL +
    ingestion roles, so valid YAMLs on satellite ecosystems failed lint.
    """

    def _state_with_engine(self, engine: str, on_nodes: list[str]) -> DesiredState:
        return DesiredState(
            ecosystem="test",
            cluster="logs",
            tables={
                "some_table": DesiredTable(
                    name="some_table",
                    engine=engine,
                    columns=[ColumnDef(name="id", type="UUID")],
                    on_nodes=on_nodes,
                    order_by=["id"],
                    source="sharded_some",  # used by Distributed
                    target="sharded_some",  # used by MV
                    settings={  # used by Kafka
                        "kafka_broker_list": "localhost:9092",
                        "kafka_topic_list": "t",
                    },
                ),
            },
        )

    def test_distributed_on_logs_passes_lint(self) -> None:
        from posthog.clickhouse.migration_tools.validator import _check_cross_cluster_targeting

        errors = _check_cross_cluster_targeting(self._state_with_engine("Distributed", ["LOGS"]))
        self.assertEqual(errors, [], f"LOGS on Distributed should be valid: {errors}")

    def test_kafka_on_aux_passes_lint(self) -> None:
        from posthog.clickhouse.migration_tools.validator import _check_cross_cluster_targeting

        errors = _check_cross_cluster_targeting(self._state_with_engine("Kafka", ["AUX"]))
        self.assertEqual(errors, [], f"AUX on Kafka should be valid: {errors}")

    def test_mv_on_sessions_passes_lint(self) -> None:
        from posthog.clickhouse.migration_tools.validator import _check_cross_cluster_targeting

        errors = _check_cross_cluster_targeting(self._state_with_engine("MaterializedView", ["SESSIONS"]))
        self.assertEqual(errors, [], f"SESSIONS on MaterializedView should be valid: {errors}")

    def test_invalid_role_still_rejected(self) -> None:
        """Ensure we didn't broaden the set so far that garbage roles pass."""
        from posthog.clickhouse.migration_tools.validator import _check_cross_cluster_targeting

        errors = _check_cross_cluster_targeting(self._state_with_engine("Distributed", ["GARBAGE"]))
        self.assertTrue(len(errors) > 0, "Unknown role should still fail lint")

    def test_expected_roles_covers_node_role_enum(self) -> None:
        """Every role advertised by NodeRole should be accepted by at least
        one engine category — otherwise a new role would silently break lint
        on ecosystems that target it."""
        from posthog.clickhouse.migration_tools.validator import _EXPECTED_ROLES

        # Names we expect to see in _EXPECTED_ROLES (some union).
        # Source: NodeRole enum in posthog/clickhouse/client/connection.py.
        # DATA is excluded — Distributed/Kafka/MV don't run on DATA nodes.
        expected_named = {
            "ALL",
            "COORDINATOR",
            "INGESTION_EVENTS",
            "INGESTION_SMALL",
            "INGESTION_MEDIUM",
            "SHUFFLEHOG",
            "ENDPOINTS",
            "LOGS",
            "AI_EVENTS",
            "AUX",
            "OPS",
            "SESSIONS",
        }
        union_of_allowed: set[str] = set()
        for allowed in _EXPECTED_ROLES.values():
            union_of_allowed |= allowed
        missing = expected_named - union_of_allowed
        self.assertEqual(missing, set(), f"_EXPECTED_ROLES union missing roles: {sorted(missing)}")


class TestDriftComparesKeyFields(unittest.TestCase):
    """P2: compare_schemas must detect drift on partition_key, primary_key,
    engine_full — not just engine + sorting_key + columns.
    """

    def _base(self, **overrides):
        from posthog.clickhouse.migration_tools.schema_introspect import TableSchema

        defaults = {
            "name": "sharded_events",
            "engine": "ReplicatedMergeTree",
            "engine_full": "ReplicatedMergeTree('/clickhouse/tables/{shard}/events', '{replica}')",
            "sorting_key": "team_id, id",
            "partition_key": "toStartOfMonth(timestamp)",
            "primary_key": "team_id, id",
        }
        defaults.update(overrides)
        return TableSchema(**defaults)

    def test_partition_key_drift_detected(self) -> None:
        from posthog.clickhouse.migration_tools.schema_introspect import compare_schemas

        expected = {"t": self._base(partition_key="toStartOfMonth(timestamp)")}
        actual = {"t": self._base(partition_key="toStartOfWeek(timestamp)")}
        diffs = compare_schemas(expected, actual)
        partition_diffs = [d for d in diffs if d.diff_type == "partition_key_mismatch"]
        self.assertEqual(len(partition_diffs), 1, f"Expected partition drift; got {diffs}")

    def test_primary_key_drift_detected(self) -> None:
        from posthog.clickhouse.migration_tools.schema_introspect import compare_schemas

        expected = {"t": self._base(primary_key="team_id, id")}
        actual = {"t": self._base(primary_key="team_id")}
        diffs = compare_schemas(expected, actual)
        pk_diffs = [d for d in diffs if d.diff_type == "primary_key_mismatch"]
        self.assertEqual(len(pk_diffs), 1, f"Expected primary-key drift; got {diffs}")

    def test_engine_full_drift_detected(self) -> None:
        from posthog.clickhouse.migration_tools.schema_introspect import compare_schemas

        expected = {"t": self._base(engine_full="ReplicatedMergeTree('/tables/{shard}/events', '{replica}')")}
        actual = {"t": self._base(engine_full="ReplicatedMergeTree('/tables/{shard}/OTHER', '{replica}')")}
        diffs = compare_schemas(expected, actual)
        engine_diffs = [d for d in diffs if d.diff_type == "engine_full_mismatch"]
        self.assertEqual(len(engine_diffs), 1, f"Expected engine_full drift; got {diffs}")

    def test_no_drift_when_all_fields_match(self) -> None:
        from posthog.clickhouse.migration_tools.schema_introspect import compare_schemas

        expected = {"t": self._base()}
        actual = {"t": self._base()}
        diffs = compare_schemas(expected, actual)
        self.assertEqual(diffs, [], f"Unexpected drift on identical schemas: {diffs}")

    def test_engine_full_skipped_when_actual_empty(self) -> None:
        """Some system tables leave engine_full empty — don't flag as drift."""
        from posthog.clickhouse.migration_tools.schema_introspect import compare_schemas

        expected = {"t": self._base(engine_full="ReplicatedMergeTree('/x', '{replica}')")}
        actual = {"t": self._base(engine_full="")}
        diffs = compare_schemas(expected, actual)
        engine_diffs = [d for d in diffs if d.diff_type == "engine_full_mismatch"]
        self.assertEqual(len(engine_diffs), 0, "engine_full drift should skip when either side is empty")


class TestComputeDiffsPerCluster(unittest.TestCase):
    """P1-A: _compute_diffs must introspect each declared cluster separately.
    Earlier it used the migrations-cluster union for every target, which
    produced spurious diffs on satellite ecosystems (their tables don't
    exist on the main migrations cluster).
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

        # Fake cluster objects — distinguishable by id()
        main_cluster = MagicMock(name="main-cluster")
        logs_cluster = MagicMock(name="logs-cluster")

        def fake_get_cluster_by_name(name: str, **_kw):
            if name == "logs":
                return logs_cluster
            return main_cluster

        dump_calls: list[object] = []

        def fake_dump(cluster_obj, _database):
            dump_calls.append(cluster_obj)
            return {}  # empty live schema → every desired table becomes a create

        with (
            patch(
                "posthog.clickhouse.migration_tools.desired_state.parse_desired_state_dir",
                return_value=[main_state, logs_state],
            ),
            patch(
                "posthog.management.commands.ch_migrate.get_cluster_by_name",
                side_effect=fake_get_cluster_by_name,
            ),
            patch(
                "posthog.management.commands.ch_migrate.is_known_cluster",
                return_value=True,
            ),
            patch(
                "posthog.clickhouse.migration_tools.schema_introspect.dump_schema_all_hosts",
                side_effect=fake_dump,
            ),
        ):
            cmd = Command()
            diffs, err = cmd._compute_diffs("posthog", "/tmp/fake_schema_dir")

        self.assertIsNone(err, f"Expected no error; got: {err}")

        # Both clusters should have been introspected — not just migrations.
        self.assertIn(main_cluster, dump_calls, "main cluster not introspected")
        self.assertIn(logs_cluster, dump_calls, "logs cluster not introspected")

        # No migrations-cluster fallback since both per-cluster scans succeeded.
        migration_scans = [c for c in dump_calls if c is not main_cluster and c is not logs_cluster]
        self.assertEqual(migration_scans, [], f"Unexpected fallback scans: {migration_scans}")

    def test_unreachable_cluster_falls_back_to_migrations(self) -> None:
        """When a satellite cluster is unreachable (dev stack), fall back
        to the migrations cluster schema instead of crashing."""
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

        def fake_get_cluster_by_name(name: str, **_kw):
            raise Exception("Code: 701 CLUSTER_DOESNT_EXIST: Cluster 'logs' not found")

        # Track call args separately since migrations cluster and the failing
        # logs cluster both route through dump_schema_all_hosts.
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
                side_effect=fake_get_cluster_by_name,
            ),
            patch(
                "posthog.management.commands.ch_migrate.is_known_cluster",
                return_value=True,
            ),
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
        # Fallback to migrations cluster should have been taken
        self.assertIn(migrations_cluster, calls, f"Migrations-cluster fallback not used: {calls}")
