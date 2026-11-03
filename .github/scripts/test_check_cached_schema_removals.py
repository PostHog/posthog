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
            schema(Modifiers={"properties": {"mode": {"enum": ["a", "b"]}}}),
            schema(Modifiers={"properties": {"mode": {"const": "a"}}}),
            ["`Modifiers` at `mode`: enum value `b`"],
            id="enum-narrowed-to-a-single-const",
        ),
        pytest.param(
            schema(Modifiers={"properties": {"mode": {"const": "a"}}}),
            schema(Modifiers={"properties": {"mode": {"const": "b"}}}),
            ["`Modifiers` at `mode`: enum value `a`"],
            id="const-value-changed",
        ),
        pytest.param(
            schema(Modifiers={"properties": {"inner": {"properties": {"gone": {}}}}}),
            schema(Modifiers={"properties": {"inner": {"properties": {}}}}),
            ["`Modifiers` at `inner`: property `gone`"],
            id="property-removed-from-inline-object",
        ),
        pytest.param(
            schema(Modifiers={"properties": {"inner": {"properties": {"kept": {}}}}}),
            schema(
                Modifiers={"properties": {"inner": {"$ref": "#/definitions/Inner"}}}, Inner={"properties": {"kept": {}}}
            ),
            [],
            id="inline-object-extracted-to-a-ref-unchanged",
        ),
        pytest.param(
            schema(Modifiers={"properties": {"inner": {"properties": {"kept": {}, "gone": {}}}}}),
            schema(
                Modifiers={"properties": {"inner": {"$ref": "#/definitions/Inner"}}}, Inner={"properties": {"kept": {}}}
            ),
            ["`Modifiers` at `inner`: property `gone`"],
            id="inline-object-extracted-to-a-ref-with-a-removal",
        ),
        pytest.param(
            schema(Modifiers={"properties": {"a": {"properties": {"y": {"properties": {"gone": {}}}}}}}),
            schema(
                Modifiers={"properties": {"a": {"$ref": "#/definitions/Inner"}}},
                Inner={"properties": {"y": {"$ref": "#/definitions/Inner"}}},
            ),
            ["`Modifiers` at `a.y`: property `gone`"],
            id="inline-object-extracted-to-a-recursive-ref",
        ),
        pytest.param(
            schema(
                Modifiers={"properties": {"tree": {"$ref": "#/definitions/Old"}}},
                Old={"properties": {"gone": {}, "child": {"$ref": "#/definitions/Old"}}},
            ),
            schema(
                Modifiers={"properties": {"tree": {"$ref": "#/definitions/New"}}},
                New={"properties": {"child": {"$ref": "#/definitions/New"}}},
            ),
            ["`Modifiers` at `tree`: property `gone`"],
            id="renamed-recursive-model",
        ),
        pytest.param(
            schema(
                Modifiers={"properties": {"a": {"$ref": "#/definitions/Old"}, "b": {"$ref": "#/definitions/Old"}}},
                Old={"properties": {"kept": {}, "gone": {}}},
            ),
            schema(
                Modifiers={"properties": {"a": {"$ref": "#/definitions/New"}, "b": {"$ref": "#/definitions/New"}}},
                New={"properties": {"kept": {}}},
            ),
            ["`Modifiers` at `a`: property `gone`"],
            id="renamed-model-reached-twice-is-reported-once",
        ),
        pytest.param(
            schema(Modifiers={"properties": {"inner": {"properties": {"kept": {}}}}}),
            schema(Modifiers={"properties": {"inner": {"anyOf": [{"properties": {"kept": {}}}, {"type": "null"}]}}}),
            [],
            id="object-made-nullable-unchanged",
        ),
        pytest.param(
            schema(Modifiers={"properties": {"inner": {"properties": {"kept": {}, "gone": {}}}}}),
            schema(Modifiers={"properties": {"inner": {"anyOf": [{"properties": {"kept": {}}}, {"type": "null"}]}}}),
            ["`Modifiers` at `inner`: property `gone`"],
            id="object-made-nullable-with-a-removal",
        ),
        pytest.param(
            schema(Modifiers={"properties": {"days": {"anyOf": [{"items": {"enum": [1, 2, 7]}}, {"type": "null"}]}}}),
            schema(Modifiers={"properties": {"days": {"anyOf": [{"items": {"enum": [1, 2]}}, {"type": "null"}]}}}),
            ["`Modifiers` at `days`: enum value `7`"],
            id="enum-value-removed-from-a-nullable-array",
        ),
        pytest.param(
            schema(Modifiers={"properties": {"inner": {"properties": {"kept": {}}}}}),
            schema(Modifiers={"properties": {"inner": {"anyOf": [{"properties": {"kept": {}}}, {"type": "string"}]}}}),
            [],
            id="union-with-two-types-is-skipped",
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
    "labels,expected",
    [
        pytest.param(["cache-impact-accepted"], "accepted", id="accepted"),
        pytest.param(["cache-impact-deprecated"], "deprecated", id="deprecated"),
        pytest.param(["cache-impact-bumped"], "bumped", id="bumped"),
        pytest.param(["frontend", "cache-impact-accepted", "stamphog"], "accepted", id="among-other-labels"),
        pytest.param(["cache-impact-maybe", "cache-impact", "frontend"], None, id="unrelated-labels"),
        pytest.param([], None, id="no-labels"),
    ],
)
def test_find_acknowledgement(labels: list[str], expected: str | None) -> None:
    assert check_cached_schema_removals.find_acknowledgement(labels) == expected
