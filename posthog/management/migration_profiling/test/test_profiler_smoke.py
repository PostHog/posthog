"""Smoke test the profiler contextmanager without hitting a real DB.

We synthesize a tiny ``Operation`` subclass with a no-op ``database_forwards``,
run it under ``profile_migrations``, and check that the JSONL output records
the op with the expected shape.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from django.db.migrations.operations.base import Operation

from posthog.management.migration_profiling.profiler import profile_migrations


class _FakeOp(Operation):
    """Concrete Operation subclass with a no-op database_forwards."""

    reduces_to_sql = True
    reversible = True

    def __init__(self, name: str):
        self.name = name

    def state_forwards(self, app_label, state):
        pass

    def database_forwards(self, app_label, schema_editor, from_state, to_state):  # type: ignore[override]
        return None

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        return None

    def describe(self):
        return f"FakeOp({self.name})"


def test_profiler_records_op(tmp_path: Path) -> None:
    output = tmp_path / "profile.jsonl"
    op = _FakeOp("noop")

    with profile_migrations(database="default", output_path=output):
        op.database_forwards("posthog", _FakeSchemaEditor(), None, None)

    lines = [json.loads(line) for line in output.read_text().splitlines() if line.strip()]
    # First line is the _meta header.
    assert "_meta" in lines[0]
    assert lines[0]["_meta"]["database"] == "default"

    # Then one OpRecord for our fake op.
    op_lines = [line for line in lines[1:] if line.get("operation_type") == "_FakeOp"]
    assert len(op_lines) == 1
    record = op_lines[0]
    assert record["app_label"] == "posthog"
    assert record["describe"] == "FakeOp(noop)"
    assert record["duration_ms"] >= 0
    assert record["error"] is None


def test_profiler_records_op_error(tmp_path: Path) -> None:
    output = tmp_path / "profile.jsonl"

    class _ExplodingOp(_FakeOp):
        def database_forwards(self, app_label, schema_editor, from_state, to_state):
            raise RuntimeError("boom")

    op = _ExplodingOp("boom")

    with profile_migrations(database="default", output_path=output):
        with pytest.raises(RuntimeError, match="boom"):
            op.database_forwards("posthog", _FakeSchemaEditor(), None, None)

    lines = [json.loads(line) for line in output.read_text().splitlines() if line.strip()]
    op_lines = [line for line in lines[1:] if line.get("operation_type") == "_ExplodingOp"]
    assert len(op_lines) == 1
    assert op_lines[0]["error"] == "RuntimeError: boom"


class _FakeSchemaEditor:
    """Just enough surface to satisfy the op wrapper's target_alias lookup."""

    class _Conn:
        alias = "default"

    connection = _Conn()
