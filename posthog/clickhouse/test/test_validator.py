"""Unit tests for migration_tools/validator.py.

No Django or ClickHouse connection required.
"""

from __future__ import annotations

import unittest

import posthog.clickhouse.test._stubs  # noqa: F401
from posthog.clickhouse.migration_tools.desired_state import ColumnDef, DesiredState, DesiredTable


class TestMergetreeOrderByLint(unittest.TestCase):
    """MergeTree tables without ORDER BY must produce a lint error."""

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


class TestEngineRequiredFieldsLint(unittest.TestCase):
    """Distributed tables need a source; materialized views need a target."""

    def _validate(self, tables: dict[str, DesiredTable]) -> list[str]:
        from posthog.clickhouse.migration_tools.validator import validate_desired_states

        state = DesiredState(ecosystem="test", cluster="main", tables=tables)
        return validate_desired_states([state])

    def test_distributed_without_source_rejected(self) -> None:
        errors = self._validate(
            {
                "dist_no_source": DesiredTable(
                    name="dist_no_source",
                    engine="Distributed",
                    columns=[ColumnDef(name="id", type="UUID")],
                    on_nodes=["COORDINATOR"],
                ),
            }
        )
        self.assertTrue(any("source" in e.lower() for e in errors), f"Expected source error, got: {errors}")

    def test_mv_without_target_rejected(self) -> None:
        errors = self._validate(
            {
                "mv_no_target": DesiredTable(
                    name="mv_no_target",
                    engine="MaterializedView",
                    columns=[],
                    on_nodes=["DATA"],
                    select="SELECT 1",
                ),
            }
        )
        self.assertTrue(any("target" in e.lower() for e in errors), f"Expected target error, got: {errors}")


class TestSatelliteRoleLint(unittest.TestCase):
    """Satellite roles (LOGS, AUX, SESSIONS, OPS, AI_EVENTS, SHUFFLEHOG, ENDPOINTS)
    must pass cross-cluster targeting lint for Distributed, Kafka, and MV engines.
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
                    source="sharded_some",
                    target="sharded_some",
                    settings={
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

    def test_distributed_accepts_ingestion_and_data_roles(self) -> None:
        from posthog.clickhouse.migration_tools.validator import _check_cross_cluster_targeting

        for role in ("DATA", "INGESTION_SMALL", "INGESTION_MEDIUM", "INGESTION_EVENTS"):
            errors = _check_cross_cluster_targeting(self._state_with_engine("Distributed", [role]))
            self.assertEqual(errors, [], f"{role} on Distributed should be valid: {errors}")

    def test_kafka_on_aux_passes_lint(self) -> None:
        from posthog.clickhouse.migration_tools.validator import _check_cross_cluster_targeting

        errors = _check_cross_cluster_targeting(self._state_with_engine("Kafka", ["AUX"]))
        self.assertEqual(errors, [], f"AUX on Kafka should be valid: {errors}")

    def test_mv_on_sessions_passes_lint(self) -> None:
        from posthog.clickhouse.migration_tools.validator import _check_cross_cluster_targeting

        errors = _check_cross_cluster_targeting(self._state_with_engine("MaterializedView", ["SESSIONS"]))
        self.assertEqual(errors, [], f"SESSIONS on MaterializedView should be valid: {errors}")

    def test_invalid_role_still_rejected(self) -> None:
        from posthog.clickhouse.migration_tools.validator import _check_cross_cluster_targeting

        errors = _check_cross_cluster_targeting(self._state_with_engine("Distributed", ["GARBAGE"]))
        self.assertTrue(len(errors) > 0, "Unknown role should still fail lint")

    def test_expected_roles_covers_node_role_enum(self) -> None:
        from posthog.clickhouse.migration_tools.validator import _EXPECTED_ROLES

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


if __name__ == "__main__":
    unittest.main()
