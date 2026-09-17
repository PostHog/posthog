import re
import ast
from collections import Counter
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCANNED_ROOTS = ("common", "ee", "posthog", "products")
SKIPPED_PARTS = {"test", "tests", "migrations", "__snapshots__"}

GATED_FIELDS = {"active", "filters"}
FLAG_NAME = re.compile(r"(?i)(flag|^ff$|^ff_|_ff$)")
ORM_WRITE_METHODS = {"create", "bulk_create", "get_or_create", "update_or_create", "update", "bulk_update"}

# The approval gate sits on FeatureFlagSerializer. These files are that gated path, so they may
# drive the serializer directly.
GATED_PATH = {
    "products/feature_flags/backend/facade/api.py",
    "products/approvals/backend/actions/feature_flags.py",
    "products/approvals/backend/scheduled_changes.py",
}

# Writes to a flag's gated fields that do not go through products/feature_flags/backend/facade/api.py.
# Each count is exact, so a new write in a listed file fails too. Shrink this dict, never grow it:
# move a write to the facade and lower its count in the same PR.
ALLOWED: dict[str, tuple[int, str]] = {
    # Drive FeatureFlagSerializer directly instead of the facade. The approval gate still runs.
    "ee/clickhouse/views/experiment_holdouts.py": (2, "holdout edit and delete"),
    "products/feature_flags/backend/api/organization_feature_flag.py": (2, "copy a flag to other projects"),
    "products/feature_flags/backend/max_tools.py": (1, "PostHog AI flag creation"),
    "products/feature_flags/backend/models/feature_flag.py": (1, "scheduled change execution"),
    "products/surveys/backend/api/survey.py": (4, "targeting flag writes (2), start/stop mirror of active (2)"),
    # Raw writes that skip validation and the approval gate.
    "posthog/api/file_system/registrations.py": (2, "file-system trash and restore flip active"),
    "products/early_access_features/backend/api.py": (1, "never-fail cleanup when stored filters fail validation"),
    # Operator tooling, local setup, demo data and eval seeders. No request reaches them.
    "posthog/management/commands/fix_invalid_flag_property_types.py": (2, "data repair command"),
    "posthog/management/commands/generate_random_product_tours.py": (1, "local data generator"),
    "posthog/management/commands/reencrypt_flag_payloads.py": (1, "payload re-encryption command"),
    "posthog/management/commands/sync_feature_flags.py": (2, "local dev flag sync"),
    "posthog/management/commands/sync_feature_flags_from_api.py": (3, "local dev flag sync"),
    "products/demo/backend/logic/matrix/matrix.py": (1, "demo data"),
    "products/demo/backend/logic/products/hedgebox/matrix.py": (2, "demo data"),
    "products/feature_flags/evals/seeders.py": (3, "eval seeders"),
    "products/marketing_analytics/backend/demo/config.py": (1, "demo data"),
    "products/posthog_ai/eval_harness/seeders/survey.py": (2, "eval seeders"),
    "products/posthog_ai/evals/experiments/seeders.py": (4, "eval seeders"),
    "products/tasks/backend/management/commands/setup_background_agents.py": (2, "local setup command"),
    "products/tasks/scripts/run_agent_in_docker.py": (2, "local agent script"),
}


def _terminal_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _chain_root(node: ast.expr) -> ast.expr:
    while True:
        if isinstance(node, ast.Call):
            node = node.func
        elif isinstance(node, ast.Attribute):
            node = node.value
        elif isinstance(node, ast.Subscript):
            node = node.value
        else:
            return node


def _names_gated_field(values: list[ast.expr]) -> bool:
    return any(isinstance(v, ast.Constant) and v.value in GATED_FIELDS for v in values)


def _is_feature_flag_query(node: ast.expr) -> bool:
    root = _chain_root(node)
    return isinstance(root, ast.Name) and root.id == "FeatureFlag"


def _names_bound_to_flags(tree: ast.Module) -> set[str]:
    # Catches flags held in variables whose name does not say "flag", such as
    # `existing = FeatureFlag.objects.filter(...).first()`.
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _is_feature_flag_query(node.value):
            targets = node.targets
        elif isinstance(node, ast.For) and _is_feature_flag_query(node.iter):
            targets = [node.target]
        else:
            continue
        names.update(t.id for t in targets if isinstance(t, ast.Name))
    return names


def _is_flag(owner: ast.expr, flag_names: set[str]) -> bool:
    name = _terminal_name(owner)
    if name is None:
        return False
    return FLAG_NAME.search(name) is not None or (isinstance(owner, ast.Name) and name in flag_names)


def _is_gated_write(node: ast.AST, flag_names: set[str]) -> bool:
    if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return any(
            isinstance(t, ast.Attribute) and t.attr in GATED_FIELDS and _is_flag(t.value, flag_names) for t in targets
        )

    if not isinstance(node, ast.Call):
        return False

    if _terminal_name(node.func) == "FeatureFlagSerializer":
        return any(kw.arg == "data" for kw in node.keywords)

    if not isinstance(node.func, ast.Attribute) or node.func.attr not in ORM_WRITE_METHODS:
        return False
    if not _is_feature_flag_query(node.func):
        return False
    method = node.func.attr
    if method == "update":
        return any(kw.arg in GATED_FIELDS for kw in node.keywords)
    if method == "bulk_update":
        fields = (
            node.args[1] if len(node.args) > 1 else next((kw.value for kw in node.keywords if kw.arg == "fields"), None)
        )
        return isinstance(fields, (ast.List, ast.Tuple, ast.Set)) and _names_gated_field(list(fields.elts))
    # A raw create sets `active` too: the model default is True, so the flag is born enabled.
    return True


def _scan() -> Counter[str]:
    offenders: Counter[str] = Counter()
    for root in SCANNED_ROOTS:
        for path in (REPO_ROOT / root).rglob("*.py"):
            relative = path.relative_to(REPO_ROOT)
            if (
                SKIPPED_PARTS & set(relative.parts)
                or relative.name.startswith("test_")
                or relative.name == "conftest.py"
            ):
                continue
            key = relative.as_posix()
            if key in GATED_PATH:
                continue
            source = path.read_text(errors="ignore")
            if "FeatureFlag" not in source and not FLAG_NAME.search(source):
                continue
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            flag_names = _names_bound_to_flags(tree)
            count = sum(1 for node in ast.walk(tree) if _is_gated_write(node, flag_names))
            if count:
                offenders[key] = count
    return offenders


def test_feature_flag_gated_fields_are_written_through_the_facade() -> None:
    # The approval gate checks writes to a flag's `active` and `filters`. A write that skips
    # FeatureFlagSerializer skips the gate, so every new write must call create_flag, update_flag
    # or set_flag_active in products/feature_flags/backend/facade/api.py.
    offenders = _scan()
    expected = {path: count for path, (count, _) in ALLOWED.items()}

    new = {path: count for path, count in offenders.items() if count > expected.get(path, 0)}
    assert not new, (
        f"New writes to FeatureFlag.active or FeatureFlag.filters outside the gated facade: {new}. "
        "Call create_flag, update_flag or set_flag_active from "
        "products/feature_flags/backend/facade/api.py instead."
    )

    fixed = {
        path: (offenders.get(path, 0), count) for path, count in expected.items() if offenders.get(path, 0) < count
    }
    assert not fixed, (
        f"These files now write fewer gated flag fields than ALLOWED records, as (found, allowed): {fixed}. "
        "Lower or remove their entries in ALLOWED so the baseline cannot grow back."
    )


@pytest.mark.parametrize(
    "snippet,expected",
    [
        ("feature_flag.active = False", 1),
        ("survey.targeting_flag.filters = {}", 1),
        ("existing = FeatureFlag.objects.filter(key='k').first()\nexisting.active = True", 1),
        ("for f in FeatureFlag.objects.all():\n    f.active = False", 1),
        ("FeatureFlag.objects.create(team=team, key='k')", 1),
        ("FeatureFlag.objects.filter(pk=1).update(active=False)", 1),
        ("FeatureFlag.objects.bulk_update(flags, ['filters'])", 1),
        ("FeatureFlagSerializer(flag, data={'active': True}, partial=True)", 1),
        ("FeatureFlag.objects.filter(pk=1).update(last_called_at=now)", 0),
        ("FeatureFlag.objects.bulk_update(flags, ['last_called_at'])", 0),
        ("FeatureFlagSerializer(flags, many=True)", 0),
        ("cohort.filters = {}", 0),
        ("feature_flag.key = 'renamed'", 0),
    ],
)
def test_scanner_detects_gated_writes(snippet: str, expected: int) -> None:
    tree = ast.parse(snippet)
    flag_names = _names_bound_to_flags(tree)
    assert sum(1 for node in ast.walk(tree) if _is_gated_write(node, flag_names)) == expected
