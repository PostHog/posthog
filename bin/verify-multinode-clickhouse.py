#!/usr/bin/env python
# ruff: noqa: T201
"""
Verify that the multinode ClickHouse smoke-test stack ended up in the expected
shape after `manage.py migrate_clickhouse` ran.

Connects to each ClickHouse node directly (via its published port) and asserts:

1. `getMacro('hostClusterRole')` returns the expected role per node — confirms
   the per-node config files mounted correctly.
2. `system.clusters` is consistent across nodes and lists the expected logical
   clusters with the expected member hosts — confirms `<remote_servers>` is
   wired correctly.
3. Tables that production routes to a satellite cluster (ai_events / aux / ops
   / sessions) live on the matching node and **not** on the data node. Catches
   migrations that forgot `node_roles=[NodeRole.X]` and accidentally created a
   table everywhere.

Exits 0 on success, non-zero on the first failed assertion (with context).
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from dataclasses import dataclass

from clickhouse_driver import Client


@dataclass(frozen=True)
class Node:
    name: str
    host: str
    port: int
    expected_role: str


# Match the published ports in docker-compose.multinode-clickhouse.yml.
NODES: list[Node] = [
    Node("clickhouse-data", "localhost", 9000, "data"),
    Node("clickhouse-ai-events", "localhost", 9100, "ai_events"),
    Node("clickhouse-aux", "localhost", 9200, "aux"),
    Node("clickhouse-ops", "localhost", 9300, "ops"),
    Node("clickhouse-sessions", "localhost", 9400, "sessions"),
]

# Logical cluster -> expected member hosts (sorted). Each multinode XML file
# declares the same `<remote_servers>` block, so every node must agree.
EXPECTED_CLUSTERS: dict[str, list[str]] = {
    "posthog": ["clickhouse-data"],
    "posthog_single_shard": ["clickhouse-data"],
    "posthog_writable": ["clickhouse-data"],
    "posthog_primary_replica": ["clickhouse-data"],
    "posthog_migrations": [
        "clickhouse-ai-events",
        "clickhouse-aux",
        "clickhouse-data",
        "clickhouse-ops",
        "clickhouse-sessions",
    ],
    "ai_events": ["clickhouse-ai-events"],
    "aux": ["clickhouse-aux"],
    "ops": ["clickhouse-ops"],
    "sessions": ["clickhouse-sessions"],
}

# Tables (in CLICKHOUSE_DATABASE) that must live on the named satellite node
# but must NOT live on the data node. Update when adding new per-cluster
# tables. Empty list means "skip this satellite check (no manifest yet)".
SATELLITE_TABLE_MANIFEST: dict[str, list[str]] = {
    "ai_events": ["ai_events", "sharded_ai_events"],
    "aux": [],
    "ops": [],
    "sessions": [],
}

DATABASE = "posthog"


def client(node: Node) -> Client:
    return Client(host=node.host, port=node.port, database="default")


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def check_macros() -> None:
    print("==> Checking <macros> per node")
    for node in NODES:
        with client(node) as c:
            ((role,),) = c.execute("SELECT getMacro('hostClusterRole')")
        if role != node.expected_role:
            fail(f"{node.name}: hostClusterRole={role!r}, expected {node.expected_role!r}")
        print(f"  {node.name}: hostClusterRole={role}")


def fetch_clusters(node: Node) -> dict[str, list[str]]:
    with client(node) as c:
        rows = c.execute(
            "SELECT cluster, host_name FROM system.clusters WHERE cluster IN %(clusters)s ORDER BY cluster, host_name",
            {"clusters": tuple(EXPECTED_CLUSTERS.keys())},
        )
    layout: dict[str, list[str]] = {}
    for cluster, host in rows:
        layout.setdefault(cluster, []).append(host)
    return layout


def check_cluster_topology() -> None:
    print("==> Checking system.clusters consistency across nodes")
    expected = {k: sorted(set(v)) for k, v in EXPECTED_CLUSTERS.items()}
    for node in NODES:
        layout = {k: sorted(set(v)) for k, v in fetch_clusters(node).items()}
        for cluster, hosts in expected.items():
            actual = layout.get(cluster)
            if actual != hosts:
                fail(f"{node.name}: cluster {cluster!r} hosts={actual}, expected {hosts}")
        print(f"  {node.name}: {len(layout)} clusters match")


def fetch_local_tables(node: Node) -> set[str]:
    with client(node) as c:
        rows = c.execute(
            "SELECT name FROM system.tables WHERE database = %(db)s",
            {"db": DATABASE},
        )
    return {name for (name,) in rows}


def find_node(role: str) -> Node:
    for node in NODES:
        if node.expected_role == role:
            return node
    raise KeyError(role)


def check_satellite_tables() -> None:
    print("==> Checking per-cluster table placement (manifest)")
    data_node = find_node("data")
    data_tables = fetch_local_tables(data_node)
    print(f"  {data_node.name}: {len(data_tables)} tables in {DATABASE!r}")

    any_checked = False
    for role, tables in SATELLITE_TABLE_MANIFEST.items():
        if not tables:
            continue
        any_checked = True
        node = find_node(role)
        node_tables = fetch_local_tables(node)
        print(f"  {node.name}: {len(node_tables)} tables in {DATABASE!r}")

        missing = [t for t in tables if t not in node_tables]
        if missing:
            fail(f"{node.name}: missing expected tables {missing}")

        leaked = [t for t in tables if t in data_tables]
        if leaked:
            fail(
                f"{data_node.name} should not have satellite-only tables {leaked} "
                f"(they belong on {node.name}). Did a migration forget node_roles=?"
            )

    if not any_checked:
        print("  (no satellite manifests populated yet — skipping presence checks)")


def main(argv: Iterable[str] = ()) -> int:
    check_macros()
    check_cluster_topology()
    check_satellite_tables()
    print("OK: multinode topology and table layout look correct.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
