"""Tests for the structured edit primitive used by the registry."""

from __future__ import annotations

import pytest

from products.agent_platform.backend.registry_edits import StructuredEditError, apply_structured_edits


class TestApplyStructuredEdits:
    def test_no_edits_returns_input_unchanged(self) -> None:
        assert apply_structured_edits("hello", []) == "hello"

    def test_single_edit_applies(self) -> None:
        out = apply_structured_edits("hello world", [{"old": "world", "new": "Ben"}])
        assert out == "hello Ben"

    def test_sequential_edits_see_prior_results(self) -> None:
        # The second edit can match text the first edit introduced —
        # this is the chaining contract the concierge depends on.
        edits = [
            {"old": "foo", "new": "bar"},
            {"old": "bar", "new": "baz"},
        ]
        assert apply_structured_edits("foo", edits) == "baz"

    def test_zero_matches_raises_with_index(self) -> None:
        with pytest.raises(StructuredEditError) as excinfo:
            apply_structured_edits("hello", [{"old": "world", "new": "x"}])
        assert excinfo.value.edit_index == 0
        assert "not found" in excinfo.value.message

    def test_multiple_matches_raises_with_index(self) -> None:
        with pytest.raises(StructuredEditError) as excinfo:
            apply_structured_edits("foo bar foo", [{"old": "foo", "new": "x"}])
        assert excinfo.value.edit_index == 0
        assert "2 times" in excinfo.value.message

    def test_missing_field_raises(self) -> None:
        with pytest.raises(StructuredEditError) as excinfo:
            apply_structured_edits("hello", [{"old": "hello"}])
        assert excinfo.value.edit_index == 0
        assert "new" in excinfo.value.message

    def test_non_string_field_raises(self) -> None:
        with pytest.raises(StructuredEditError) as excinfo:
            apply_structured_edits("hello", [{"old": 1, "new": "x"}])
        assert excinfo.value.edit_index == 0
        assert "must be strings" in excinfo.value.message

    def test_later_edit_index_surfaces(self) -> None:
        edits = [
            {"old": "a", "new": "z"},
            {"old": "MISSING", "new": "y"},
        ]
        with pytest.raises(StructuredEditError) as excinfo:
            apply_structured_edits("abc", edits)
        assert excinfo.value.edit_index == 1
