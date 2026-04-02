"""Parse desired-state YAML files into typed Python objects.

Each YAML file declares the complete desired schema for one table ecosystem
(e.g. events, sessions_v3, person). The system reads these files, diffs them
against live ClickHouse state, and generates migration plans.

This is the "terraform plan" equivalent for ClickHouse schema management.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ColumnDef:
    name: str
    type: str
    default_kind: str = ""
    default_expression: str = ""
    codec: str = ""


@dataclass
class DesiredTable:
    name: str
    engine: str
    columns: list[ColumnDef]
    on_nodes: list[str]
    order_by: list[str] | None = None
    partition_by: str | None = None
    sharded: bool = False
    sharding_key: str | None = None
    source: str | None = None  # for Distributed: the local table
    target: str | None = None  # for MV: the target table
    select: str | None = None  # for MV: the SELECT statement
    settings: dict[str, str] | None = None  # for Kafka: engine settings
    inherit_columns_from: str | None = None


@dataclass
class DesiredState:
    ecosystem: str
    cluster: str
    tables: dict[str, DesiredTable]
    database: str = "posthog"


def _parse_column(raw: dict[str, Any]) -> ColumnDef:
    return ColumnDef(
        name=raw["name"],
        type=raw["type"],
        default_kind=raw.get("default_kind", ""),
        default_expression=raw.get("default_expression", raw.get("default", "")),
        codec=raw.get("codec", ""),
    )


def _parse_columns(raw: Any, all_tables: dict[str, Any]) -> list[ColumnDef]:
    """Parse columns, handling 'inherit <table_name>' syntax."""
    if isinstance(raw, str) and raw.startswith("inherit "):
        source_table = raw.split(" ", 1)[1].strip()
        source_raw = all_tables.get(source_table)
        if source_raw is None:
            raise ValueError(f"Cannot inherit columns from unknown table '{source_table}'")
        source_cols = source_raw.get("columns")
        if isinstance(source_cols, str) and source_cols.startswith("inherit "):
            return _parse_columns(source_cols, all_tables)
        if not isinstance(source_cols, list):
            raise ValueError(f"Source table '{source_table}' has no column list to inherit from")
        return [_parse_column(c) for c in source_cols]
    if isinstance(raw, list):
        return [_parse_column(c) for c in raw]
    raise ValueError(f"'columns' must be a list of column defs or 'inherit <table_name>', got {type(raw).__name__}")


def _parse_table(name: str, raw: dict[str, Any], all_tables: dict[str, Any]) -> DesiredTable:
    engine = raw.get("engine", "")
    if not engine:
        raise ValueError(f"Table '{name}' must have an 'engine' field")

    columns_raw = raw.get("columns", [])
    inherit_from: str | None = None
    if isinstance(columns_raw, str) and columns_raw.startswith("inherit "):
        inherit_from = columns_raw.split(" ", 1)[1].strip()
    columns = _parse_columns(columns_raw, all_tables)

    on_nodes_raw = raw.get("on_nodes", ["ALL"])
    if isinstance(on_nodes_raw, str):
        on_nodes_raw = [on_nodes_raw]

    order_by = raw.get("order_by")
    if isinstance(order_by, str):
        order_by = [order_by]

    settings = raw.get("settings")
    if settings and isinstance(settings, dict):
        settings = {k: str(v) for k, v in settings.items()}

    return DesiredTable(
        name=name,
        engine=engine,
        columns=columns,
        on_nodes=on_nodes_raw,
        order_by=order_by,
        partition_by=raw.get("partition_by"),
        sharded=raw.get("sharded", False),
        sharding_key=raw.get("sharding_key"),
        source=raw.get("source"),
        target=raw.get("target"),
        select=raw.get("select"),
        settings=settings,
        inherit_columns_from=inherit_from,
    )


def parse_desired_state(yaml_path: Path) -> DesiredState:
    """Parse a single desired-state YAML file into a DesiredState object."""
    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Desired state YAML must be a mapping, got {type(data).__name__}")

    ecosystem = data.get("ecosystem", "")
    if not ecosystem:
        raise ValueError("Desired state YAML must have an 'ecosystem' field")

    cluster = data.get("cluster", "main")
    database = data.get("database", "posthog")

    raw_tables = data.get("tables", {})
    if not isinstance(raw_tables, dict):
        raise ValueError(f"'tables' must be a mapping, got {type(raw_tables).__name__}")

    tables: dict[str, DesiredTable] = {}
    for table_name, table_raw in raw_tables.items():
        tables[table_name] = _parse_table(table_name, table_raw, raw_tables)

    return DesiredState(
        ecosystem=ecosystem,
        cluster=cluster,
        tables=tables,
        database=database,
    )


def parse_desired_state_dir(schema_dir: Path) -> list[DesiredState]:
    """Parse all YAML files in a directory into DesiredState objects."""
    states: list[DesiredState] = []
    yaml_files = sorted(schema_dir.glob("*.yaml")) + sorted(schema_dir.glob("*.yml"))
    for yaml_path in yaml_files:
        states.append(parse_desired_state(yaml_path))
    return states
