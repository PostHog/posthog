"""Ratchet on manual ENUM_NAME_OVERRIDES entries in posthog/settings/web.py.

Enum component names are derived from Choices classes by posthog/openapi/enum_names.py, so a
new enum needs no entry. A manual entry only exists for a choice set no class can carry. The
baseline freezes today's entries so the count can fall but never rise.

The keys are read from the settings source with ast, because importing settings would pull in
Django. After deleting an entry, delete its line from the baseline too.
"""

import ast
from pathlib import Path

WEB_SETTINGS_PATH = Path(__file__).parents[2] / "settings" / "web.py"
BASELINE_PATH = Path(__file__).parent / "enum_name_overrides_baseline.txt"


def find_override_keys() -> set[str]:
    tree = ast.parse(WEB_SETTINGS_PATH.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if not (isinstance(key, ast.Constant) and key.value == "ENUM_NAME_OVERRIDES"):
                continue
            assert isinstance(value, ast.Call) and isinstance(value.args[0], ast.Dict), (
                "ENUM_NAME_OVERRIDES must stay ChoicesEnumNameOverrides({...}) with a literal dict, "
                "or this guard cannot read the manual entries."
            )
            explicit = value.args[0]
            assert all(isinstance(entry, ast.Constant) for entry in explicit.keys), (
                "Every ENUM_NAME_OVERRIDES key must be a string literal."
            )
            return {str(entry.value) for entry in explicit.keys if isinstance(entry, ast.Constant)}
    raise AssertionError("ENUM_NAME_OVERRIDES not found in posthog/settings/web.py")


def read_baseline() -> set[str]:
    return {line.strip() for line in BASELINE_PATH.read_text().splitlines() if line.strip()}


def test_no_new_manual_enum_name_overrides() -> None:
    added = sorted(find_override_keys() - read_baseline())
    assert not added, (
        "New manual ENUM_NAME_OVERRIDES entries are not allowed. Derive the enum name from a Choices "
        "class via posthog/openapi/enum_names.py instead of adding an entry in posthog/settings/web.py:\n"
        + "\n".join(added)
    )


def test_enum_name_overrides_baseline_has_no_stale_lines() -> None:
    stale = sorted(read_baseline() - find_override_keys())
    assert not stale, (
        "These lines in posthog/test/repo_invariants/enum_name_overrides_baseline.txt match no "
        "ENUM_NAME_OVERRIDES key anymore. Delete them to keep the ratchet tight:\n" + "\n".join(stale)
    )
