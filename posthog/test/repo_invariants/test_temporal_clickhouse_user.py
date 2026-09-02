import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SKIPPED_DIR_NAMES = frozenset({"test", "tests", "node_modules", ".venv"})


def _temporal_modules() -> list[Path]:
    paths: list[Path] = []
    for path in _REPO_ROOT.rglob("temporal/**/*.py"):
        parts = path.relative_to(_REPO_ROOT).parts
        if _SKIPPED_DIR_NAMES.isdisjoint(parts) and not path.name.startswith("test_"):
            paths.append(path)
    return paths


def _names_a_user(call: ast.Call) -> bool:
    for keyword in call.keywords:
        if keyword.arg != "ch_user":
            continue
        # An explicit DEFAULT is not an opt-out: sync_execute reads it as "no user named".
        return not (isinstance(keyword.value, ast.Attribute) and keyword.value.attr == "DEFAULT")
    return False


def _calls_without_ch_user(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(), filename=str(path))
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name == "sync_execute" and not _names_a_user(node):
            lines.append(node.lineno)
    return lines


def test_temporal_sync_execute_calls_name_a_clickhouse_user() -> None:
    offenders = []
    for path in _temporal_modules():
        for lineno in _calls_without_ch_user(path):
            offenders.append(f"{path.relative_to(_REPO_ROOT)}:{lineno}")

    assert not offenders, (
        "These Temporal calls name no ClickHouse user, so they fall back to the shared BACKGROUND "
        "user and get no resource limits of their own. Pass ch_user=ClickHouseUser.<YOUR_PRODUCT>, "
        "and add a member to ClickHouseUser if your product has none:\n" + "\n".join(sorted(offenders))
    )
