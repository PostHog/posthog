"""Test that each per-op metadata extractor pulls out the right fields.

Uses lightweight stubs rather than constructing real Django Operation
instances — keeps the test fast and avoids dragging in the app registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from posthog.management.migration_profiling.metadata import EXTRACTORS, STATE_ONLY_OPERATIONS, extract


@dataclass
class _FakeOp:
    name: str = ""


@pytest.mark.parametrize(
    "op_type,attrs,expected",
    [
        ("CreateModel", {"name": "Event"}, {"model_name": "Event"}),
        ("DeleteModel", {"name": "Event"}, {"model_name": "Event"}),
        ("AddField", {"model_name": "Event", "name": "color"}, {"model_name": "Event", "field_name": "color"}),
        ("RemoveField", {"model_name": "Event", "name": "color"}, {"model_name": "Event", "field_name": "color"}),
        ("AlterField", {"model_name": "Event", "name": "color"}, {"model_name": "Event", "field_name": "color"}),
        (
            "RenameField",
            {"model_name": "Event", "old_name": "x", "new_name": "y"},
            {"model_name": "Event", "old_name": "x", "new_name": "y"},
        ),
        ("AlterModelOptions", {"name": "Event"}, {"model_name": "Event"}),
        (
            "RunPython",
            {"code": lambda apps, schema_editor: None},
            None,
        ),
    ],
)
def test_extractor_for_known_op_type(op_type: str, attrs: dict[str, Any], expected: dict[str, Any] | None) -> None:
    op = type("Stub", (), {})()
    op.__class__.__name__ = op_type
    for k, v in attrs.items():
        setattr(op, k, v)

    result = extract(op)

    if op_type == "RunPython":
        assert result["is_runpython"] is True
        assert "callable" in result
    else:
        assert result == expected


def test_extractor_unknown_op_type_returns_empty() -> None:
    op = type("Stub", (), {})()
    op.__class__.__name__ = "TotallyMadeUpOp"
    assert extract(op) == {}


def test_add_index_extracts_index_name() -> None:
    op = type("Stub", (), {})()
    op.__class__.__name__ = "AddIndex"
    op.model_name = "Event"
    op.index = type("Idx", (), {"name": "foo_idx"})()
    assert extract(op) == {"model_name": "Event", "index_name": "foo_idx"}


def test_run_sql_extracts_preview() -> None:
    op = type("Stub", (), {})()
    op.__class__.__name__ = "RunSQL"
    op.sql = "SELECT 1;"
    assert extract(op) == {"sql_preview": "SELECT 1;"}


def test_run_sql_list_preview_truncates() -> None:
    op = type("Stub", (), {})()
    op.__class__.__name__ = "RunSQL"
    op.sql = ["A" * 500, "B" * 500, "C" * 500, "D" * 500]
    result = extract(op)
    # First three items joined, each truncated to 200 chars.
    assert "A" * 200 in result["sql_preview"]
    assert "D" * 200 not in result["sql_preview"]


def test_extractor_swallows_errors() -> None:
    """An extractor that raises must not bring down the profiler — the
    profiler should still produce an OpRecord with an error marker in
    metadata, not propagate the exception."""
    op = type("Stub", (), {})()
    op.__class__.__name__ = "AddField"
    # Deliberately omit model_name + name so the extractor raises AttributeError.
    result = extract(op)
    assert "_extract_error" in result


def test_state_only_operations_match_extractor_keys() -> None:
    # Sanity: every state-only op type must have an extractor (so its
    # metadata still gets populated even though database_forwards is a no-op).
    assert STATE_ONLY_OPERATIONS.issubset(EXTRACTORS.keys() | {"AlterOrderWithRespectTo"})
