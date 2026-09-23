import re
import ast
from collections import Counter
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BASELINE = Path(__file__).with_name("feature_flag_gated_writes_baseline.txt")
SCANNED_ROOTS = ("common", "ee", "posthog", "products")
SKIPPED_PARTS = {"test", "tests", "migrations", "__snapshots__"}

GATED_FIELDS = {"active", "filters"}
FLAG_NAME = re.compile(r"(?i)(flag|^ff$|^ff_|_ff$)")
ORM_WRITE_METHODS = {"create", "bulk_create", "get_or_create", "update_or_create", "update", "bulk_update"}

# The approval gate itself. Only its serializer writes are exempt.
GATED_PATH = {
    "products/feature_flags/backend/facade/api.py",
    "products/approvals/backend/actions/feature_flags.py",
    "products/approvals/backend/scheduled_changes.py",
}

# Shrink-only. Move a write to the facade, then regenerate the baseline and drop its entry here.
ALLOWED_REASONS: dict[str, str] = {
    "products/feature_flags/backend/api/organization_feature_flag.py": "copy a flag to other projects",
    "products/surveys/backend/api/survey.py": "targeting flag writes and the start/stop mirror of active",
    "posthog/api/file_system/registrations.py": "file-system trash and restore flip active",
    "products/early_access_features/backend/api.py": "never-fail cleanup when stored filters fail validation",
    "posthog/management/commands/fix_invalid_flag_property_types.py": "data repair command",
    "posthog/management/commands/generate_random_product_tours.py": "local data generator",
    "posthog/management/commands/reencrypt_flag_payloads.py": "payload re-encryption command",
    "posthog/management/commands/sync_feature_flags.py": "local dev flag sync",
    "posthog/management/commands/sync_feature_flags_from_api.py": "local dev flag sync",
    "products/demo/backend/logic/matrix/matrix.py": "demo data",
    "products/demo/backend/logic/products/hedgebox/matrix.py": "demo data",
    "products/feature_flags/evals/seeders.py": "eval seeders",
    "products/marketing_analytics/backend/demo/config.py": "demo data",
    "products/posthog_ai/eval_harness/seeders/survey.py": "eval seeders",
    "products/posthog_ai/evals/experiments/seeders.py": "eval seeders",
    "products/tasks/backend/management/commands/setup_background_agents.py": "local setup command",
    "products/tasks/scripts/run_agent_in_docker.py": "local agent script",
}

REGENERATE = (
    "Regenerate it with: python -c \"import sys; sys.path.insert(0, 'posthog/test/repo_invariants'); "
    'import test_feature_flag_gated_writes as t; t.write_baseline()"'
)


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


SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def _imported_aliases(tree: ast.AST, name: str) -> set[str]:
    aliases = {name}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            aliases.update(alias.asname for alias in node.names if alias.name == name and alias.asname)
    return aliases


def _is_model_query(node: ast.expr, models: set[str]) -> bool:
    root = _chain_root(node)
    return isinstance(root, ast.Name) and root.id in models


def _mentions_model(annotation: ast.expr | None, models: set[str]) -> bool:
    if annotation is None:
        return False
    for sub in ast.walk(annotation):
        if isinstance(sub, (ast.Name, ast.Attribute)) and _terminal_name(sub) in models:
            return True
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            try:
                forward_reference = ast.parse(sub.value, mode="eval").body
            except SyntaxError:
                continue
            if _mentions_model(forward_reference, models):
                return True
    return False


def _own_nodes(scope: ast.AST):
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, SCOPE_NODES):
            stack.extend(ast.iter_child_nodes(node))


def _bound_names(target: ast.expr) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        return set().union(*(_bound_names(element) for element in target.elts))
    if isinstance(target, ast.Starred):
        return _bound_names(target.value)
    return set()


def _scope_flag_names(scope: ast.AST, models: set[str]) -> set[str]:
    names: set[str] = set()
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        args = scope.args
        for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
            if _mentions_model(arg.annotation, models):
                names.add(arg.arg)
    for node in _own_nodes(scope):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign) and _is_model_query(node.value, models):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and (
            _mentions_model(node.annotation, models) or (node.value is not None and _is_model_query(node.value, models))
        ):
            targets = [node.target]
        elif isinstance(node, (ast.For, ast.AsyncFor)) and _is_model_query(node.iter, models):
            targets = [node.target]
        for target in targets:
            names.update(_bound_names(target))
    return names


def _is_flag(owner: ast.expr, flag_names: set[str]) -> bool:
    name = _terminal_name(owner)
    if name is None:
        return False
    return FLAG_NAME.search(name) is not None or (isinstance(owner, ast.Name) and name in flag_names)


def _names_gated_field(values: list[ast.expr]) -> bool:
    # A non-literal entry could name a gated field, so it counts as one.
    return any(not isinstance(v, ast.Constant) or v.value in GATED_FIELDS for v in values)


def _write_target(
    node: ast.AST, flag_names: set[str], models: set[str], serializers: set[str], *, serializer_exempt: bool
) -> str | None:
    if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Attribute) and target.attr in GATED_FIELDS and _is_flag(target.value, flag_names):
                return f"{ast.unparse(target)} ="
        return None

    if not isinstance(node, ast.Call):
        return None

    if _terminal_name(node.func) in serializers:
        # Positional data or **kwargs cannot be resolved, so they count as a write.
        is_write = len(node.args) > 1 or any(kw.arg in (None, "data") for kw in node.keywords)
        if not is_write or serializer_exempt:
            return None
        instance = ast.unparse(node.args[0]) if node.args else ""
        return f"FeatureFlagSerializer({instance})"

    if not isinstance(node.func, ast.Attribute) or node.func.attr not in ORM_WRITE_METHODS:
        return None
    root = _chain_root(node.func)
    if not (isinstance(root, ast.Name) and (root.id in models or root.id in flag_names)):
        return None
    method = node.func.attr
    if method == "update" and not any(kw.arg is None or kw.arg in GATED_FIELDS for kw in node.keywords):
        return None
    if method == "bulk_update":
        fields = (
            node.args[1] if len(node.args) > 1 else next((kw.value for kw in node.keywords if kw.arg == "fields"), None)
        )
        if isinstance(fields, (ast.List, ast.Tuple, ast.Set)) and not _names_gated_field(list(fields.elts)):
            return None
    # A raw create sets `active` too: the model default is True, so the flag is born enabled.
    return f"{ast.unparse(node.func)}()"


def gated_writes(tree: ast.AST, *, serializer_exempt: bool = False) -> list[str]:
    # Keying by scope instead of line number keeps the baseline stable when code moves.
    models = _imported_aliases(tree, "FeatureFlag")
    serializers = _imported_aliases(tree, "FeatureFlagSerializer")
    found: list[str] = []

    def visit(scope: ast.AST, label: str, inherited: set[str]) -> None:
        flag_names = inherited | _scope_flag_names(scope, models)
        for node in _own_nodes(scope):
            target = _write_target(node, flag_names, models, serializers, serializer_exempt=serializer_exempt)
            if target is not None:
                found.append(f"{label or '<module>'}::{target}")
            if isinstance(node, SCOPE_NODES):
                name = getattr(node, "name", "<lambda>")
                visit(node, f"{label}.{name}" if label else name, flag_names)

    visit(tree, "", set())
    return found


def _scan() -> Counter[str]:
    found: Counter[str] = Counter()
    for root in SCANNED_ROOTS:
        for path in (REPO_ROOT / root).rglob("*.py"):
            relative = path.relative_to(REPO_ROOT)
            if (
                SKIPPED_PARTS & set(relative.parts)
                or relative.name.startswith("test_")
                or relative.name == "conftest.py"
            ):
                continue
            source = path.read_text(errors="ignore")
            if "FeatureFlag" not in source and not FLAG_NAME.search(source):
                continue
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            key = relative.as_posix()
            for write in gated_writes(tree, serializer_exempt=key in GATED_PATH):
                found[f"{key}::{write}"] += 1
    return found


def _read_baseline() -> Counter[str]:
    lines = BASELINE.read_text().splitlines() if BASELINE.exists() else []
    return Counter(line for line in lines if line and not line.startswith("#"))


def write_baseline() -> None:
    header = "# Generated by write_baseline() in test_feature_flag_gated_writes.py. Shrink it, never grow it.\n"
    BASELINE.write_text(header + "".join(f"{entry}\n" for entry in sorted(_scan().elements())))


def test_feature_flag_gated_fields_are_written_through_the_facade() -> None:
    # A write that skips FeatureFlagSerializer also skips the approval gate.
    found = _scan()
    baseline = _read_baseline()

    new = sorted((found - baseline).elements())
    assert not new, (
        f"New writes to FeatureFlag.active or FeatureFlag.filters outside the gated facade: {new}. "
        "Call create_flag, update_flag or set_flag_active from "
        "products/feature_flags/backend/facade/api.py instead."
    )

    removed = sorted((baseline - found).elements())
    assert not removed, f"The baseline lists writes that no longer exist: {removed}. {REGENERATE}"

    baseline_files = {entry.split("::", 1)[0] for entry in baseline}
    assert baseline_files == ALLOWED_REASONS.keys(), (
        f"ALLOWED_REASONS and the baseline disagree. Without a reason: {sorted(baseline_files - ALLOWED_REASONS.keys())}. "
        f"Without baseline writes: {sorted(ALLOWED_REASONS.keys() - baseline_files)}."
    )


@pytest.mark.parametrize(
    "snippet,expected",
    [
        ("feature_flag.active = False", 1),
        ("survey.targeting_flag.filters = {}", 1),
        ("existing = FeatureFlag.objects.filter(key='k').first()\nexisting.active = True", 1),
        ("row, _ = FeatureFlag.objects.get_or_create(key='k')\nrow.filters = {}", 2),
        ("for f in FeatureFlag.objects.all():\n    f.active = False", 1),
        ("rows = FeatureFlag.objects.filter(team=team)\nrows.update(active=False)", 1),
        ("FeatureFlag.objects.create(team=team, key='k')", 1),
        ("FeatureFlag.objects.filter(pk=1).update(active=False)", 1),
        ("FeatureFlag.objects.filter(pk=1).update(**payload)", 1),
        ("FeatureFlag.objects.bulk_update(flags, ['filters'])", 1),
        ("FeatureFlag.objects.bulk_update(flags, fields)", 1),
        ("FeatureFlagSerializer(flag, data={'active': True}, partial=True)", 1),
        ("FeatureFlagSerializer(flag, payload, partial=True)", 1),
        ("FeatureFlagSerializer(flag, **kwargs)", 1),
        ("from m import FeatureFlag as FF\nFF.objects.create(key='k')", 1),
        ("from m import FeatureFlagSerializer as S\nS(item, data={})", 1),
        ("def f(feature: FeatureFlag):\n    feature.active = False", 1),
        ("def f(feature: 'FeatureFlag | None'):\n    feature.filters = {}", 1),
        ("def f(feature: 'ArchivedFeatureFlag'):\n    feature.active = False", 0),
        (
            "async def f(holder):\n    async for holder.item in FeatureFlag.objects.all():\n        holder.active = False",
            0,
        ),
        ("first, *rest = FeatureFlag.objects.all()\nrest.update(active=False)", 1),
        ("async def f():\n    async for item in FeatureFlag.objects.all():\n        item.active = False", 1),
        ("item: FeatureFlag = load()\nitem.active = True", 1),
        ("FeatureFlag.objects.filter(pk=1).update(last_called_at=now)", 0),
        ("FeatureFlag.objects.bulk_update(flags, ['last_called_at'])", 0),
        ("FeatureFlagSerializer(flags, many=True)", 0),
        ("cohort.filters = {}", 0),
        ("feature_flag.key = 'renamed'", 0),
    ],
)
def test_scanner_detects_gated_writes(snippet: str, expected: int) -> None:
    assert len(gated_writes(ast.parse(snippet))) == expected


def test_bindings_do_not_leak_between_functions() -> None:
    tree = ast.parse(
        "def a():\n    row = FeatureFlag.objects.first()\n    row.active = False\n"
        "def b():\n    row = Cohort.objects.first()\n    row.active = False"
    )
    assert gated_writes(tree) == ["a::row.active ="]


def test_gated_path_exempts_only_serializer_writes() -> None:
    tree = ast.parse("def apply(flag):\n    FeatureFlagSerializer(flag, data={})\n    flag.active = True")
    assert gated_writes(tree, serializer_exempt=True) == ["apply::flag.active ="]


def test_swapping_an_allowed_write_for_another_is_a_new_write() -> None:
    before = Counter(gated_writes(ast.parse("def sync(flag):\n    flag.active = True")))
    after = Counter(gated_writes(ast.parse("def sync(flag):\n    flag.filters = {}")))
    assert sorted((after - before).elements()) == ["sync::flag.filters ="]
