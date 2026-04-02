# ruff: noqa: T201 allow print statements
"""Generate desired-state YAML dicts from templates.

Each template produces a dict matching the DesiredState YAML format:
  ecosystem, cluster, tables: {name: {engine, columns, on_nodes, ...}}

The ch_migrate generate command writes this dict as YAML.
"""

from __future__ import annotations

from typing import Any


def generate_schema_yaml(template_name: str, table: str, cluster: str) -> dict[str, Any] | None:
    """Dispatch to the named template generator. Returns a dict or None on error."""
    generators: dict[str, Any] = {
        "ingestion_pipeline": _ingestion_pipeline,
        "sharded_table": _sharded_table,
        "add_column": _add_column,
        "cross_cluster_readable": _cross_cluster_readable,
        "materialized_view": _materialized_view,
        "drop_table": _drop_table,
    }

    generator = generators.get(template_name)
    if generator is None:
        print(f"Unknown template: {template_name}")
        print(f"Available templates: {', '.join(sorted(generators.keys()))}")
        return None

    return generator(table, cluster)


_PLACEHOLDER_COLUMNS: list[dict[str, str]] = [
    {"name": "id", "type": "UUID"},
    {"name": "team_id", "type": "Int64"},
    {"name": "timestamp", "type": "DateTime64(6, 'UTC')"},
]


def _ingestion_pipeline(table: str, cluster: str) -> dict[str, Any]:
    """Full Kafka-to-ClickHouse pipeline: kafka + sharded + writable + readable + MV."""
    return {
        "ecosystem": table,
        "cluster": cluster,
        "tables": {
            f"kafka_{table}": {
                "engine": "Kafka",
                "on_nodes": "INGESTION_EVENTS",
                "settings": {
                    "kafka_broker_list": "kafka:9092",
                    "kafka_topic_list": table,
                    "kafka_group_name": f"{table}_consumer",
                    "kafka_format": "JSONEachRow",
                },
                "columns": list(_PLACEHOLDER_COLUMNS),
            },
            f"sharded_{table}": {
                "engine": "ReplicatedMergeTree",
                "sharded": True,
                "on_nodes": "DATA",
                "order_by": ["team_id", "id"],
                "partition_by": "toYYYYMM(timestamp)",
                "columns": list(_PLACEHOLDER_COLUMNS),
            },
            f"writable_{table}": {
                "engine": "Distributed",
                "source": f"sharded_{table}",
                "sharding_key": "cityHash64(id)",
                "on_nodes": "COORDINATOR",
                "columns": f"inherit sharded_{table}",
            },
            table: {
                "engine": "Distributed",
                "source": f"sharded_{table}",
                "sharding_key": "cityHash64(id)",
                "on_nodes": "ALL",
                "columns": f"inherit sharded_{table}",
            },
            f"{table}_mv": {
                "engine": "MaterializedView",
                "source": f"kafka_{table}",
                "target": f"writable_{table}",
                "select": f"SELECT * FROM posthog.kafka_{table}",
                "on_nodes": "INGESTION_EVENTS",
                "columns": [],
            },
        },
    }


def _sharded_table(table: str, cluster: str) -> dict[str, Any]:
    """Sharded table with distributed read/write layers (no Kafka or MV)."""
    return {
        "ecosystem": table,
        "cluster": cluster,
        "tables": {
            f"sharded_{table}": {
                "engine": "ReplicatedMergeTree",
                "sharded": True,
                "on_nodes": "DATA",
                "order_by": ["team_id", "id"],
                "partition_by": "toYYYYMM(timestamp)",
                "columns": list(_PLACEHOLDER_COLUMNS),
            },
            f"writable_{table}": {
                "engine": "Distributed",
                "source": f"sharded_{table}",
                "sharding_key": "cityHash64(id)",
                "on_nodes": "COORDINATOR",
                "columns": f"inherit sharded_{table}",
            },
            table: {
                "engine": "Distributed",
                "source": f"sharded_{table}",
                "sharding_key": "cityHash64(id)",
                "on_nodes": "ALL",
                "columns": f"inherit sharded_{table}",
            },
        },
    }


def _add_column(table: str, cluster: str) -> dict[str, Any]:
    """Placeholder for add-column -- user should edit an existing YAML file instead."""
    print(f"To add a column, edit the existing schema file: posthog/clickhouse/schema/{table}.yaml")
    print("Add the column to the sharded table's columns list.")
    print("Inherited columns will propagate automatically.")
    print("Then run: ch_migrate plan")
    return {
        "ecosystem": table,
        "cluster": cluster,
        "tables": {},
    }


def _cross_cluster_readable(table: str, cluster: str) -> dict[str, Any]:
    """Distributed table on one cluster reading from another."""
    return {
        "ecosystem": table,
        "cluster": cluster,
        "tables": {
            table: {
                "engine": "Distributed",
                "source": f"sharded_{table}",
                "on_nodes": "ALL",
                "columns": list(_PLACEHOLDER_COLUMNS),
            },
        },
    }


def _materialized_view(table: str, cluster: str) -> dict[str, Any]:
    """Single materialized view."""
    return {
        "ecosystem": table,
        "cluster": cluster,
        "tables": {
            f"{table}_mv": {
                "engine": "MaterializedView",
                "source": f"kafka_{table}",
                "target": f"writable_{table}",
                "select": f"SELECT * FROM posthog.kafka_{table}",
                "on_nodes": "ALL",
                "columns": [],
            },
        },
    }


def _drop_table(table: str, cluster: str) -> dict[str, Any]:
    """Empty ecosystem -- plan will show drops for existing tables not in desired state."""
    print(f"To drop tables, remove them from posthog/clickhouse/schema/{table}.yaml")
    print("or delete the file entirely. Then run: ch_migrate plan")
    return {
        "ecosystem": table,
        "cluster": cluster,
        "tables": {},
    }
