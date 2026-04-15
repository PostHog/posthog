"""Unit tests for plan_generator — generate_plan_text and generate_manifest_steps."""

from __future__ import annotations

import unittest

from posthog.clickhouse.migration_tools.plan_generator import generate_manifest_steps, generate_plan_text
from posthog.clickhouse.migration_tools.state_diff import StateDiff


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
        self.assertIn("~", plan)
        self.assertIn("-", plan)
        self.assertIn("+", plan)
        self.assertIn("sharded_events", plan)
        self.assertIn("old_mv", plan)
        self.assertIn("new_table", plan)
        self.assertIn("Plan:", plan)
        self.assertIn("ch_migrate plan:", plan)

    def test_no_changes_plan(self) -> None:
        plan = generate_plan_text([])
        self.assertIn("No changes", plan)

    def test_kafka_recreate_warning(self) -> None:
        diffs = [
            StateDiff(
                action="recreate",
                table="kafka_events",
                detail="Recreate kafka_events",
                sql="DROP TABLE IF EXISTS posthog.kafka_events;\nCREATE TABLE posthog.kafka_events ...",
                node_roles=["ALL"],
            ),
        ]
        plan = generate_plan_text(diffs)
        self.assertIn("KAFKA TABLE RECREATE WARNING", plan)
        self.assertIn("ingestion will pause", plan)


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

    def test_cluster_propagated_to_steps(self) -> None:
        diffs = [
            StateDiff(
                action="create",
                table="t",
                detail="Create t",
                sql="CREATE TABLE ...",
                node_roles=["ALL"],
                cluster="logs",
            ),
        ]
        steps = generate_manifest_steps(diffs)
        self.assertEqual(steps[0][0].cluster, "logs")
