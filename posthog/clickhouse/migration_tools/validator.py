"""Validate desired-state YAML schemas for ecosystem completeness and targeting."""

from __future__ import annotations

from posthog.clickhouse.migration_tools.desired_state import DesiredState
from posthog.clickhouse.migration_tools.schema_graph import TableEcosystem, lookup_ecosystem
from posthog.clickhouse.migration_tools.state_diff import _is_distributed, _is_kafka, _is_mergetree, _is_mv

# Expected node roles by engine type.
#
# Source of truth: `NodeRole` enum in posthog/clickhouse/client/connection.py.
# Every satellite cluster (LOGS, AUX, SESSIONS, OPS, AI_EVENTS, SHUFFLEHOG,
# ENDPOINTS) can host its own Distributed, Kafka, and MV tables in its own
# topology, so all three engine categories accept those roles in addition to
# the main-cluster roles.
_SATELLITE_ROLES: frozenset[str] = frozenset({"LOGS", "AUX", "SESSIONS", "OPS", "AI_EVENTS", "SHUFFLEHOG", "ENDPOINTS"})

_EXPECTED_ROLES: dict[str, set[str]] = {
    # Distributed routing is logical, not physical — a Distributed table can
    # legitimately live on any role (DATA for read paths, INGESTION_* for
    # writable passthroughs on ingestion hosts, COORDINATOR for query
    # coordination, satellite roles for per-ecosystem hosts).
    "distributed": {
        "COORDINATOR",
        "ALL",
        "DATA",
        "INGESTION_EVENTS",
        "INGESTION_SMALL",
        "INGESTION_MEDIUM",
        *_SATELLITE_ROLES,
    },
    "kafka": {"INGESTION_EVENTS", "INGESTION_SMALL", "INGESTION_MEDIUM", "ALL", *_SATELLITE_ROLES},
    "materializedview": {"INGESTION_EVENTS", "INGESTION_SMALL", "INGESTION_MEDIUM", "ALL", *_SATELLITE_ROLES},
}


def build_ecosystems_from_yaml(desired_states: list[DesiredState]) -> list[TableEcosystem]:
    """Build ecosystem objects from desired-state YAML definitions.

    Scans all DesiredState objects and identifies ecosystems by finding
    Distributed tables that reference MergeTree source tables.
    """
    ecosystems: list[TableEcosystem] = []

    for state in desired_states:
        tables = state.tables

        local_tables = {n: t for n, t in tables.items() if _is_mergetree(t.engine)}
        distributed = {n: t for n, t in tables.items() if _is_distributed(t.engine)}
        kafka = {n: t for n, t in tables.items() if _is_kafka(t.engine)}
        mvs = {n: t for n, t in tables.items() if _is_mv(t.engine)}

        for local_name in local_tables:
            writable = next(
                (n for n, t in distributed.items() if t.source == local_name and "writable" in n),
                None,
            )
            readable = next(
                (n for n, t in distributed.items() if t.source == local_name and "writable" not in n),
                None,
            )

            base_name = local_name.replace("sharded_", "")

            kafka_tbl = next(
                (n for n in kafka if base_name in n),
                None,
            )
            mv_tbl = next(
                (n for n in mvs if base_name in n),
                None,
            )

            if writable or readable:
                ecosystems.append(
                    TableEcosystem(
                        base_name=base_name,
                        sharded_table=local_name,
                        distributed_writable=writable,
                        distributed_readable=readable,
                        kafka_table=kafka_tbl,
                        materialized_view=mv_tbl,
                    )
                )

    return ecosystems


def validate_desired_states(desired_states: list[DesiredState]) -> list[str]:
    """Validate a list of desired states. Returns a list of error strings (empty = valid)."""
    errors: list[str] = []

    # Build dynamic ecosystems from YAML for completeness checking
    dynamic_ecosystems = build_ecosystems_from_yaml(desired_states)
    dynamic_lookup: dict[str, TableEcosystem] = {}
    for eco in dynamic_ecosystems:
        for tbl in eco.all_tables():
            dynamic_lookup[tbl] = eco

    for state in desired_states:
        errors.extend(_check_ecosystem_completeness(state, dynamic_lookup))
        errors.extend(_check_cross_cluster_targeting(state))
        errors.extend(_check_mergetree_order_by(state))

    return errors


def _check_ecosystem_completeness(
    state: DesiredState,
    dynamic_lookup: dict[str, TableEcosystem] | None = None,
) -> list[str]:
    """Warn if an ecosystem is partially declared (e.g. sharded without distributed).

    Uses dynamic ecosystems built from YAML when available, falls back to
    the hardcoded registry in schema_graph.py.
    """
    errors: list[str] = []

    for table_name in state.tables:
        # Try dynamic lookup first, then hardcoded
        eco = None
        if dynamic_lookup:
            eco = dynamic_lookup.get(table_name)
        if eco is None:
            eco = lookup_ecosystem(table_name)
        if eco is None:
            continue

        expected_tables = eco.all_tables()
        declared_tables = set(state.tables.keys())
        missing = expected_tables - declared_tables

        if missing:
            errors.append(
                f"[{state.ecosystem}] Table '{table_name}' belongs to ecosystem "
                f"'{eco.base_name}' but companion tables are missing: {sorted(missing)}"
            )
            break  # one warning per ecosystem is enough

    return errors


def _check_cross_cluster_targeting(state: DesiredState) -> list[str]:
    """Check that engine types target appropriate node roles."""
    errors: list[str] = []

    for table_name, table in state.tables.items():
        engine_lower = table.engine.lower()
        expected = None
        for engine_key, roles in _EXPECTED_ROLES.items():
            if engine_key in engine_lower:
                expected = roles
                break

        if expected is None:
            continue

        on_nodes_set = set(table.on_nodes)
        if not on_nodes_set & expected:
            errors.append(
                f"[{state.ecosystem}] Table '{table_name}' (engine={table.engine}) "
                f"targets {table.on_nodes} but expected one of {sorted(expected)}"
            )

    return errors


def _check_mergetree_order_by(state: DesiredState) -> list[str]:
    """MergeTree-family tables must have an ORDER BY clause.

    ClickHouse rejects CREATE TABLE for MergeTree engines without ORDER BY.
    Catching this at lint time prevents silent failures at apply time.
    """
    errors: list[str] = []
    for table_name, table in state.tables.items():
        if _is_mergetree(table.engine) and not table.order_by:
            errors.append(
                f"[{state.ecosystem}] Table '{table_name}' (engine={table.engine}) "
                f"is missing ORDER BY \u2014 ClickHouse will reject this CREATE"
            )
    return errors
