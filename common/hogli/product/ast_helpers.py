"""AST-based helpers for inspecting product Python files."""

from __future__ import annotations

import ast
from pathlib import Path


def ast_parse_safe(file_path: Path) -> ast.Module | None:
    try:
        return ast.parse(file_path.read_text())
    except (SyntaxError, OSError):
        return None


def get_model_names(backend_dir: Path) -> list[str]:
    """Return names of Django ORM model subclasses in backend/models.py or backend/models/."""
    sources: list[Path] = []
    models_file = backend_dir / "models.py"
    models_dir = backend_dir / "models"
    if models_file.exists():
        sources.append(models_file)
    elif models_dir.is_dir():
        sources.extend(models_dir.rglob("*.py"))

    names: list[str] = []
    for path in sources:
        tree = ast_parse_safe(path)
        if not tree:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    base_name = (
                        base.id
                        if isinstance(base, ast.Name)
                        else base.attr
                        if isinstance(base, ast.Attribute)
                        else None
                    )
                    if base_name and "Model" in base_name:
                        names.append(node.name)
                        break
    return names


def get_frozen_dataclass_names(file_path: Path) -> list[str]:
    """Return names of @dataclass(frozen=True) classes in a file."""
    tree = ast_parse_safe(file_path)
    if not tree:
        return []
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            func = dec.func
            is_dc = (isinstance(func, ast.Name) and func.id == "dataclass") or (
                isinstance(func, ast.Attribute) and func.attr == "dataclass"
            )
            if is_dc and any(
                kw.arg == "frozen" and isinstance(kw.value, ast.Constant) and kw.value.value is True
                for kw in dec.keywords
            ):
                names.append(node.name)
    return names


def get_public_function_names(file_path: Path) -> list[str]:
    """Return names of public top-level and class-level functions/methods."""
    tree = ast_parse_safe(file_path)
    if not tree:
        return []
    return [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_")
    ]


def imports_any(file_path: Path, prefixes: list[str]) -> bool:
    """Return True if file imports from any of the given module prefixes."""
    tree = ast_parse_safe(file_path)
    if not tree:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if any(node.module == p or node.module.startswith(p + ".") for p in prefixes):
                return True
        elif isinstance(node, ast.Import):
            if any(alias.name == p or alias.name.startswith(p + ".") for alias in node.names for p in prefixes):
                return True
    return False


def contract_coverage(model_names: list[str], dc_names: list[str]) -> tuple[list[str], list[str]]:
    """Returns (covered, uncovered) model names based on exact name match with frozen dataclasses."""
    dc_set = set(dc_names)
    covered = [m for m in model_names if m in dc_set]
    uncovered = [m for m in model_names if m not in dc_set]
    return covered, uncovered


def get_orm_bound_serializer_names(file_path: Path) -> list[str]:
    """
    Return names of serializer classes that still have a Meta.model binding.
    These need to be reworked to accept/return contracts instead.
    """
    tree = ast_parse_safe(file_path)
    if not tree:
        return []
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        is_serializer = any(
            (isinstance(b, ast.Name) and "Serializer" in b.id)
            or (isinstance(b, ast.Attribute) and "Serializer" in b.attr)
            for b in node.bases
        )
        if not is_serializer:
            continue
        for child in node.body:
            if isinstance(child, ast.ClassDef) and child.name == "Meta":
                for stmt in child.body:
                    if isinstance(stmt, ast.Assign) and any(
                        isinstance(t, ast.Name) and t.id == "model" for t in stmt.targets
                    ):
                        names.append(node.name)
    return names


def count_direct_orm_queries(file_path: Path) -> int:
    """Count .objects. attribute accesses — each is a direct ORM query that should go through the facade."""
    tree = ast_parse_safe(file_path)
    if not tree:
        return 0
    return sum(1 for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr == "objects")


def get_cross_product_internal_imports(product_dir: Path, product_name: str) -> list[str]:
    """
    Find imports from other products' internals (non-facade) within this product's own files.
    Returns list of 'relpath: module' strings.
    """
    violations: list[str] = []
    for py_file in product_dir.rglob("*.py"):
        tree = ast_parse_safe(py_file)
        if not tree:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if node.module.startswith(f"products.{product_name}"):
                continue
            if node.module.startswith("products.") and ".backend." in node.module:
                parts = node.module.split(".")
                if "facade" not in parts:
                    rel = str(py_file.relative_to(product_dir))
                    violations.append(f"{rel}: {node.module}")
    return violations


def view_facade_usage(views_path: Path) -> tuple[bool, bool]:
    """
    Returns (imports_facade, imports_models_directly).
    Handles both relative (from ..facade import ...) and absolute imports.
    """
    tree = ast_parse_safe(views_path)
    if not tree:
        return False, False
    imports_facade = False
    imports_models = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        parts = (node.module or "").split(".")
        if "facade" in parts:
            imports_facade = True
        if "models" in parts or node.module == "models":
            imports_models = True
    return imports_facade, imports_models
