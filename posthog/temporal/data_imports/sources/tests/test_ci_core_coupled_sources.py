import re
import ast
from pathlib import Path

# Guards the `data_import_sources_only` optimization in .github/workflows/ci-backend.yml.
# That step trims a sources-only PR to the Django Temporal segment, dropping Core/CorePOE.
# That is only safe for sources NOT imported by Core/CorePOE-collected code. The workflow
# excludes the coupled ones via its `coupled` list; this test fails if a Core/CorePOE file
# gains a runtime import of a source missing from that list — which would otherwise let a
# sources-only PR silently skip the Core test that exercises it.

SOURCES_PKG = "posthog.temporal.data_imports.sources."

# Roots collected by the Django Core/CorePOE segments. posthog/temporal is excluded — it is
# the Temporal segment, which always runs for a sources-only PR.
_SCAN_ROOTS = ("posthog", "ee", "products/product_analytics")
_EXCLUDED_SUBTREE = ("posthog", "temporal")


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".github" / "workflows" / "ci-backend.yml").exists():
            return parent
    raise RuntimeError("repo root not found")


def _is_type_checking(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _runtime_imported_sources(tree: ast.AST) -> set[str]:
    found: set[str] = set()

    class Visitor(ast.NodeVisitor):
        def visit_If(self, node: ast.If) -> None:
            # Type-only imports don't affect runtime test behavior — skip the
            # TYPE_CHECKING branch but still scan its else.
            if _is_type_checking(node.test):
                for stmt in node.orelse:
                    self.visit(stmt)
                return
            self.generic_visit(node)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            module = node.module or ""
            if module.startswith(SOURCES_PKG):
                found.add(module[len(SOURCES_PKG) :].split(".")[0])

        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                if alias.name.startswith(SOURCES_PKG):
                    found.add(alias.name[len(SOURCES_PKG) :].split(".")[0])

    Visitor().visit(tree)
    return found


def _workflow_coupled(root: Path) -> set[str]:
    text = (root / ".github" / "workflows" / "ci-backend.yml").read_text()
    match = re.search(r'coupled="([^"]*)"', text)
    assert match, 'could not find `coupled="..."` in ci-backend.yml sources step'
    return set(match.group(1).split())


def test_core_coupled_sources_are_excluded_from_ci_trim():
    root = _repo_root()
    excluded = root.joinpath(*_EXCLUDED_SUBTREE).resolve()

    imported: set[str] = set()
    for rel in _SCAN_ROOTS:
        base = root / rel
        if not base.exists():
            continue
        for file in base.rglob("*.py"):
            resolved = file.resolve()
            if resolved == excluded or excluded in resolved.parents:
                continue
            text = file.read_text(errors="ignore")
            if "data_imports.sources" not in text:
                continue
            try:
                tree = ast.parse(text, filename=str(file))
            except SyntaxError:
                continue
            imported |= _runtime_imported_sources(tree)

    coupled = _workflow_coupled(root)
    missing = imported - coupled
    assert not missing, (
        f"Core/CorePOE code imports warehouse sources {sorted(missing)} not in the CI "
        f"`coupled` list {sorted(coupled)}. A sources-only PR touching them would skip "
        f"their Core tests. Add them to `coupled` in .github/workflows/ci-backend.yml."
    )
