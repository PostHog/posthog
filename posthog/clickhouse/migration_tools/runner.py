"""Step execution engine -- routes SQL to correct ClickHouse nodes by role.

Also provides legacy migration support: discover_migrations, get_pending_migrations,
run_migration_down.
"""

from __future__ import annotations

import os
import importlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from posthog.clickhouse.migration_tools.manifest import ROLE_MAP, ManifestStep

if TYPE_CHECKING:
    from posthog.clickhouse.cluster import ClickhouseCluster

# Legacy migrations live here
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def _map_node_roles(manifest_roles: list[str]) -> list:
    from posthog.clickhouse.client.connection import NodeRole

    result = []
    for role in manifest_roles:
        role_value = ROLE_MAP.get(role)
        if role_value is None:
            raise ValueError(f"Unknown node role '{role}'. Valid roles: {sorted(ROLE_MAP.keys())}")
        result.append(NodeRole(role_value))
    return result


def execute_migration_step(
    cluster: ClickhouseCluster,
    step: ManifestStep,
    rendered_sql: str,
) -> dict[Any, Any]:
    """Routing: sharded+alter_replicated -> one_host_per_shard, alter_replicated -> any_host, else -> all hosts."""
    from posthog.clickhouse.cluster import Query

    query = Query(rendered_sql)
    node_roles = _map_node_roles(step.node_roles)

    if step.sharded and step.is_alter_on_replicated_table:
        futures_map = cluster.map_one_host_per_shard(query)
        return futures_map.result()
    elif step.is_alter_on_replicated_table:
        future = cluster.any_host_by_roles(query, node_roles=node_roles)
        result = future.result()
        return {"single_host": result}
    else:
        futures_map = cluster.map_hosts_by_roles(query, node_roles=node_roles)
        return futures_map.result()


# ------------------------------------------------------------------
# Legacy migration support
# ------------------------------------------------------------------


def discover_migrations() -> list[str]:
    """Find all legacy .py migration modules in the migrations directory.

    Returns sorted module names like ['0001_initial', '0002_add_events', ...].
    """
    if not MIGRATIONS_DIR.exists():
        return []

    migrations = []
    for entry in sorted(os.listdir(MIGRATIONS_DIR)):
        # Match NNNN_name.py or NNNN_name/ (directory migrations)
        if entry.startswith("0") and not entry.startswith("__"):
            name = entry.removesuffix(".py")
            # Accept .py files, legacy dir migrations with __init__.py, and
            # new-style manifest directories with a manifest.yaml. Earlier
            # this only matched __init__.py, so manifest-only migrations
            # silently disappeared from legacy discovery.
            entry_path = MIGRATIONS_DIR / entry
            if entry_path.is_file() and entry.endswith(".py"):
                migrations.append(name)
            elif entry_path.is_dir() and (
                (entry_path / "__init__.py").exists() or (entry_path / "manifest.yaml").exists()
            ):
                migrations.append(name)

    return migrations


def get_pending_migrations() -> list[str]:
    """Return legacy migrations that haven't been applied yet.

    Checks the infi clickhouse_orm migration tracking.
    """
    all_migrations = discover_migrations()
    if not all_migrations:
        return []

    try:
        from posthog.clickhouse.client.migration_tools import get_migrations_cluster

        cluster = get_migrations_cluster()
        client = cluster.any_host(lambda c: c).result()

        # Check what's been recorded in the infi tracking system
        rows = client.execute(
            "SELECT name FROM system.tables WHERE database = 'default' AND name = 'infi_clickhouse_orm_migrations'"
        )
        if not rows:
            return all_migrations  # no tracking table = everything is pending

        applied_rows = client.execute("SELECT package_name FROM default.infi_clickhouse_orm_migrations")
        applied = {row[0] for row in applied_rows}

        return [m for m in all_migrations if m not in applied]
    except Exception:
        return all_migrations


def run_migration_down(migration_number: int) -> None:
    """Roll back a legacy migration by number."""
    migrations = discover_migrations()
    target = None
    for m in migrations:
        if m.startswith(f"{migration_number:04d}_"):
            target = m
            break

    if target is None:
        raise ValueError(f"Migration {migration_number} not found")

    module_path = f"posthog.clickhouse.migrations.{target}"
    module = importlib.import_module(module_path)
    rollback_ops = getattr(module, "rollback_operations", [])

    if not rollback_ops:
        raise ValueError(f"Migration {target} has no rollback_operations")

    from posthog.clickhouse.client.migration_tools import get_migrations_cluster

    cluster = get_migrations_cluster()

    for op in rollback_ops:
        if hasattr(op, "sql"):
            from posthog.clickhouse.cluster import Query

            cluster.map_all_hosts(Query(op.sql)).result()
        elif hasattr(op, "fn"):
            client = cluster.any_host(lambda c: c).result()
            op.fn(client)
