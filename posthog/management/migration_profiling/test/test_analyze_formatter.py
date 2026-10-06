"""Test the Markdown report renderer end-to-end against synthetic OpRecords."""

from __future__ import annotations

import json
from pathlib import Path

from posthog.management.migration_profiling.formatters import load_run, render_report
from posthog.management.migration_profiling.spy import SpyAggregate


def _write_jsonl(path: Path, meta: dict, ops: list[dict]) -> Path:
    lines = [json.dumps({"_meta": meta})]
    lines.extend(json.dumps(o) for o in ops)
    path.write_text("\n".join(lines))
    return path


def _op(**overrides) -> dict:
    base = {
        "database": "default",
        "app_label": "posthog",
        "migration_name": "0001_initial",
        "operation_index": 0,
        "operation_type": "CreateModel",
        "describe": "Create model Event",
        "started_at": "2026-05-22T10:00:00Z",
        "duration_ms": 100.0,
        "sql_count": 1,
        "sql_total_ms": 95.0,
        "sql_truncated_count": 0,
        "is_runpython": False,
        "is_state_only": False,
        "parent_op_index": None,
        "error": None,
        "sql_statements": [
            {
                "sql": "CREATE TABLE event (...);",
                "sql_truncated": False,
                "params_repr": None,
                "duration_ms": 95.0,
                "source": "schema_editor",
                "ts_offset_ms": 1.0,
            }
        ],
        "metadata": {"model_name": "Event"},
    }
    base.update(overrides)
    return base


class TestRenderReport:
    def test_renders_with_no_spy(self, tmp_path: Path) -> None:
        path = _write_jsonl(
            tmp_path / "p.jsonl",
            {"database": "default", "started_at": "now", "django_version": "5.2.0"},
            [
                _op(duration_ms=2500.0, operation_type="AddIndex", describe="big idx"),
                _op(duration_ms=10.0, operation_index=1, operation_type="AlterModelOptions", is_state_only=True),
                _op(duration_ms=50.0, operation_index=2, migration_name="0002_more"),
            ],
        )
        run = load_run(path)

        report = render_report([run], {})

        assert "# Migration profile report" in report
        assert "## Top 50 slowest operations" in report
        assert "AddIndex" in report
        # State-only op should not appear in the slowest-ops table (filtered).
        assert "AlterModelOptions" not in report.split("## Top 50 slowest operations")[1].split("##")[0]

    def test_renders_with_spy(self, tmp_path: Path) -> None:
        path = _write_jsonl(
            tmp_path / "p.jsonl",
            {"database": "default", "started_at": "now"},
            [_op()],
        )
        run = load_run(path)
        agg = SpyAggregate(
            total_samples=100,
            by_self=[("func_a", 60, 60.0), ("func_b", 40, 40.0)],
            by_cumulative=[("main", 100, 100.0)],
        )

        report = render_report([run], {"default": (agg, None)})

        assert "Python hot functions (py-spy)" in report
        assert "func_a" in report
        assert "Total samples: 100" in report

    def test_separate_db_and_state_outer_excluded_when_has_children(self, tmp_path: Path) -> None:
        path = _write_jsonl(
            tmp_path / "p.jsonl",
            {"database": "default", "started_at": "now"},
            [
                # Outer SDAS op with 2s wall clock — but its children sum to
                # the same thing, so the outer must be excluded.
                _op(
                    operation_index=0,
                    operation_type="SeparateDatabaseAndState",
                    duration_ms=2000.0,
                ),
                _op(operation_index=1, operation_type="AddField", duration_ms=1500.0, parent_op_index=0),
                _op(operation_index=2, operation_type="AddIndex", duration_ms=500.0, parent_op_index=0),
            ],
        )
        run = load_run(path)

        report = render_report([run], {})

        slowest_section = report.split("## Top 50 slowest operations")[1].split("##")[0]
        # The outer SDAS line should not be in the slowest table — only the inner ops.
        assert "SeparateDatabaseAndState" not in slowest_section
