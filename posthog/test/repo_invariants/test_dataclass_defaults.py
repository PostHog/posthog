"""Ratchet guard for dataclass defaults.

New dataclasses must either use posthog.dataclasses.frozen (house defaults:
frozen, kw_only, slots) or state an explicit frozen= flag so the choice is
deliberate. Existing bare @dataclass uses are grandfathered in the baseline.

Regenerate the baseline (only to ratchet DOWN or after moving code):

    python posthog/test/repo_invariants/test_dataclass_defaults.py
"""

import ast
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

from repo_invariant_scan_scope import ScanScope

if TYPE_CHECKING:
    from pytest import MonkeyPatch

REPO_ROOT = Path(__file__).parents[3]
BASELINE_PATH = Path(__file__).parent / "dataclass_frozen_baseline.txt"
SCANNED_ROOTS = ("posthog", "ee", "products", "common")
SKIPPED_DIRS = {"node_modules", ".venv", "venv", "__pycache__", ".git", ".mypy_cache"}


def _dotted_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _is_undeclared_dataclass_decorator(decorator: ast.expr) -> bool:
    """A stdlib @dataclass decorator with no explicit frozen= choice."""
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    dotted = _dotted_name(target)
    if dotted is None or "pydantic" in dotted:
        return False
    if dotted != "dataclass" and not dotted.endswith(".dataclass"):
        return False
    if isinstance(decorator, ast.Call):
        return not any(kw.arg == "frozen" for kw in decorator.keywords)
    return True


def _class_definitions(tree: ast.AST) -> Iterator[ast.ClassDef]:
    pending = [tree]
    while pending:
        node = pending.pop()
        if isinstance(node, ast.ClassDef):
            yield node
        # Expressions cannot contain class definitions, so their subtrees need no scan.
        pending.extend(child for child in ast.iter_child_nodes(node) if not isinstance(child, ast.expr))


def collect_offenders() -> dict[str, list[int]]:
    offenders: dict[str, list[int]] = {}
    for root in ScanScope.from_environment().roots(SCANNED_ROOTS):
        for path in (REPO_ROOT / root).rglob("*.py"):
            if SKIPPED_DIRS.intersection(path.parts):
                continue
            source = path.read_text(encoding="utf-8", errors="ignore")
            if "dataclass" not in source:
                continue
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            lines = [
                decorator.lineno
                for node in _class_definitions(tree)
                for decorator in node.decorator_list
                if _is_undeclared_dataclass_decorator(decorator)
            ]
            if lines:
                offenders[path.relative_to(REPO_ROOT).as_posix()] = sorted(lines)
    return offenders


def read_baseline() -> dict[str, int]:
    baseline: dict[str, int] = {}
    for line in BASELINE_PATH.read_text().splitlines():
        if line.strip():
            count, path = line.split(" ", 1)
            baseline[path] = int(count)
    return baseline


def write_baseline(offenders: dict[str, list[int]]) -> None:
    lines = sorted(f"{len(linenos)} {path}" for path, linenos in offenders.items())
    BASELINE_PATH.write_text("\n".join(lines) + "\n")


def test_no_new_undeclared_dataclasses() -> None:
    offenders = collect_offenders()
    baseline = read_baseline()
    regressions = []
    for path, linenos in sorted(offenders.items()):
        allowed = baseline.get(path, 0)
        if len(linenos) > allowed:
            locations = ", ".join(f"{path}:{lineno}" for lineno in linenos)
            regressions.append(f"{path}: {len(linenos)} undeclared (baseline {allowed}) at {locations}")
    assert not regressions, (
        "New @dataclass without an explicit frozen= choice. Prefer @frozen from "
        "posthog.dataclasses (frozen, kw_only, slots by default; every flag overridable), "
        "or pass frozen= explicitly if mutability is intentional. If you only moved "
        "existing code, regenerate the baseline: python posthog/test/repo_invariants/test_dataclass_defaults.py\n"
        + "\n".join(regressions)
    )


def test_collect_offenders_finds_nested_classes(tmp_path: Path, monkeypatch: "MonkeyPatch") -> None:
    source = (
        "@dataclass\n"
        "class Outer:\n"
        "    @dataclass\n"
        "    class Nested: pass\n"
        "    def factory(self):\n"
        "        @dataclass()\n"
        "        class Local: pass\n"
        "        return Local\n"
        "async def factory():\n"
        "    match value:\n"
        "        case True:\n"
        "            @dataclasses.dataclass\n"
        "            class Conditional: pass\n"
        "@dataclass(frozen=True)\n"
        "class Explicit: pass\n"
    )
    (tmp_path / "posthog").mkdir()
    (tmp_path / "posthog" / "sample.py").write_text(source)
    monkeypatch.setattr(f"{__name__}.REPO_ROOT", tmp_path)
    monkeypatch.delenv("REPO_INVARIANTS_SCAN_SCOPE", raising=False)

    assert collect_offenders() == {"posthog/sample.py": [1, 3, 6, 12]}


if __name__ == "__main__":
    collected = collect_offenders()
    write_baseline(collected)
    print(f"baseline written: {sum(len(v) for v in collected.values())} offenders in {len(collected)} files")  # noqa: T201
