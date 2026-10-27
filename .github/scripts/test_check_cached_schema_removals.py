import importlib.util
from pathlib import Path
from typing import Any

import pytest

SCRIPT_PATH = Path(__file__).with_name("check_cached_schema_removals.py")
SPEC = importlib.util.spec_from_file_location("check_cached_schema_removals", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
check_cached_schema_removals = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_cached_schema_removals)

ROOT = {"CachedFooResponse": {"properties": {"modifiers": {"$ref": "#/definitions/Modifiers"}}}}


def schema(**definitions: Any) -> dict[str, Any]:
    return {"definitions": {**ROOT, **definitions}}


@pytest.mark.parametrize(
    "base,head,expected",
    [
        pytest.param(
            schema(Modifiers={"properties": {"keep": {}, "gone": {}}}),
            schema(Modifiers={"properties": {"keep": {}}}),
            ["`Modifiers`: property `gone`"],
            id="property-removed-from-model-reached-through-a-ref",
        ),
        pytest.param(
            schema(Modifiers={"properties": {"mode": {"enum": ["a", "b"]}}}),
            schema(Modifiers={"properties": {"mode": {"enum": ["a"]}}}),
            ["`Modifiers` at `mode`: enum value `b`"],
            id="enum-value-removed",
        ),
        pytest.param(
            schema(Modifiers={"properties": {"inner": {"properties": {"gone": {}}}}}),
            schema(Modifiers={"properties": {"inner": {"properties": {}}}}),
            ["`Modifiers` at `inner`: property `gone`"],
            id="property-removed-from-inline-object",
        ),
        pytest.param(
            schema(Modifiers={"properties": {"keep": {}}}, Request={"properties": {"gone": {}}}),
            schema(Modifiers={"properties": {"keep": {}}}, Request={"properties": {}}),
            [],
            id="model-that-no-cached-response-reaches",
        ),
        pytest.param(
            schema(Modifiers={"properties": {"mode": {"enum": ["a"]}}}),
            schema(Modifiers={"properties": {"mode": {"enum": ["a", "b"]}, "new": {}}}),
            [],
            id="additions-only",
        ),
    ],
)
def test_find_removals(base: dict[str, Any], head: dict[str, Any], expected: list[str]) -> None:
    removals = check_cached_schema_removals.find_removals(base, head)

    assert [removal.describe() for removal in removals] == expected


@pytest.mark.parametrize(
    "body,expected",
    [
        pytest.param("Cache impact: accepted, the field only chose a connection path", "accepted", id="accepted"),
        pytest.param("## Notes\n\ncache impact: Deprecated", "deprecated", id="case-and-position-ignored"),
        pytest.param("Cache impact: bumped", "bumped", id="bumped"),
        pytest.param("Cache impact: maybe", None, id="unknown-choice"),
        pytest.param("The cache impact is small.", None, id="no-line"),
        pytest.param("", None, id="empty-body"),
    ],
)
def test_find_acknowledgement(body: str, expected: str | None) -> None:
    assert check_cached_schema_removals.find_acknowledgement(body) == expected
