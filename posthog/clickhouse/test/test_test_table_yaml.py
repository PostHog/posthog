"""Smoke test: verify test_table.yaml parses correctly via parse_desired_state."""

from __future__ import annotations

from pathlib import Path


def test_test_table_yaml_parses():
    from posthog.clickhouse.migration_tools.desired_state import parse_desired_state

    yaml_path = Path(__file__).parent.parent.parent / "clickhouse" / "schema" / "test_table.yaml"
    assert yaml_path.exists(), f"test_table.yaml not found at {yaml_path}"

    state = parse_desired_state(yaml_path)

    assert state.ecosystem == "test"
    assert state.cluster == "main"
    assert "ch_migrate_test" in state.tables

    t = state.tables["ch_migrate_test"]
    assert t.engine == "MergeTree"
    assert t.order_by == ["team_id", "id"]

    col_names = [c.name for c in t.columns]
    assert "id" in col_names
    assert "team_id" in col_names
    assert "name" in col_names
    assert "created_at" in col_names

    created_at = next(c for c in t.columns if c.name == "created_at")
    assert created_at.type == "DateTime"
    assert created_at.default_kind == "DEFAULT"
    assert created_at.default_expression == "now()"
