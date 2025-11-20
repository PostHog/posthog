#!/usr/bin/env python3
"""
Split schema.py into multiple modules for faster imports.

Properly analyzes dependencies to distinguish:
- Runtime dependencies: defaults, generics, base classes (must import at runtime)
- Type-checking dependencies: type hints only (can use TYPE_CHECKING)
"""

import ast
import sys
from collections import defaultdict
from pathlib import Path

SCHEMA_PY = Path("posthog/schema.py")
SCHEMA_DIR = Path("posthog/schema")
GENERATED_SCHEMA = SCHEMA_DIR / "_generated.py"


def find_runtime_dependencies(class_def: ast.ClassDef, all_classes: dict[str, ast.ClassDef]) -> set[str]:
    """Find classes that must be imported at runtime (defaults, generics, base classes)."""
    deps = set()

    # Base classes are runtime
    for base in class_def.bases:
        if isinstance(base, ast.Name) and base.id in all_classes:
            deps.add(base.id)
        elif isinstance(base, ast.Subscript):
            # RootModel[Union[...]] - the generic parameter is runtime
            if isinstance(base.value, ast.Name) and base.value.id == "RootModel":
                deps.update(_extract_classes_from_generic(base.slice, all_classes))

    # Default values are runtime
    for node in ast.walk(class_def):
        if isinstance(node, ast.keyword) and node.arg == "default":
            deps.update(_extract_classes_from_expr(node.value, all_classes))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            # Field(default=SomeClass.VALUE) - need SomeClass
            if node.func.attr == "Field":
                for kw in node.keywords:
                    if kw.arg == "default":
                        deps.update(_extract_classes_from_expr(kw.value, all_classes))

    return deps


def find_type_checking_dependencies(class_def: ast.ClassDef, all_classes: dict[str, ast.ClassDef]) -> set[str]:
    """Find classes only used in type hints (can use TYPE_CHECKING)."""
    deps = set()

    def visit_annotation(node: ast.AST) -> None:
        if isinstance(node, ast.Name) and node.id in all_classes:
            deps.add(node.id)
        elif isinstance(node, ast.Subscript):
            # Union[X, Y] is a Subscript with Name(id='Union') as value
            visit_annotation(node.value)
            # Handle slice (the [X, Y] part)
            if isinstance(node.slice, ast.Index):  # Python < 3.9
                visit_annotation(node.slice.value)
            elif isinstance(node.slice, ast.Tuple):
                for elt in node.slice.elts:
                    visit_annotation(elt)
            elif hasattr(node.slice, "elts"):  # ast.Tuple in Python 3.9+
                for elt in node.slice.elts:
                    visit_annotation(elt)
            elif hasattr(node.slice, "value"):  # Single value
                visit_annotation(node.slice.value)

    # Only type hints (not defaults, not generics in base classes)
    for node in ast.walk(class_def):
        if isinstance(node, ast.AnnAssign) and node.annotation:
            visit_annotation(node.annotation)
        elif isinstance(node, ast.arg) and node.annotation:
            visit_annotation(node.annotation)
        elif isinstance(node, ast.FunctionDef):
            if node.returns:
                visit_annotation(node.returns)
            for arg in node.args.args:
                if arg.annotation:
                    visit_annotation(arg.annotation)

    return deps


def _extract_classes_from_generic(slice_node: ast.AST, all_classes: dict[str, ast.ClassDef]) -> set[str]:
    """Extract class names from a generic parameter like Union[Class1, Class2]."""
    deps = set()

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.Name) and node.id in all_classes:
            deps.add(node.id)
        elif isinstance(node, ast.Subscript):
            # Union[X, Y] is a Subscript
            visit(node.value)
            if isinstance(node.slice, ast.Index):  # Python < 3.9
                visit(node.slice.value)
            elif isinstance(node.slice, ast.Tuple):
                for elt in node.slice.elts:
                    visit(elt)
            elif hasattr(node.slice, "elts"):  # ast.Tuple in Python 3.9+
                for elt in node.slice.elts:
                    visit(elt)
            elif hasattr(node.slice, "value"):
                visit(node.slice.value)
        elif isinstance(node, ast.Tuple):
            for elt in node.elts:
                visit(elt)

    visit(slice_node)
    return deps


def _extract_classes_from_expr(expr: ast.AST, all_classes: dict[str, ast.ClassDef]) -> set[str]:
    """Extract class names from an expression like SomeClass.VALUE."""
    deps = set()

    if isinstance(expr, ast.Attribute):
        # SomeClass.VALUE - need SomeClass
        if isinstance(expr.value, ast.Name) and expr.value.id in all_classes:
            deps.add(expr.value.id)
    elif isinstance(expr, ast.Name) and expr.id in all_classes:
        deps.add(expr.id)

    return deps


def categorize_class(class_name: str, class_def: ast.ClassDef) -> str:
    """Categorize a class based on its name and base classes."""
    bases = []
    for base in class_def.bases:
        if isinstance(base, ast.Name):
            bases.append(base.id)
        elif isinstance(base, ast.Attribute):
            bases.append(base.attr)

    if any("Enum" in b or "StrEnum" in b for b in bases):
        return "enums"
    if class_name.endswith("Query") or class_name.endswith("QueryResponse"):
        return "queries"
    if "Filter" in class_name:
        return "filters"
    if class_name.endswith("Node") or class_name in ("EventsNode", "ActionsNode", "PersonsNode", "DataWarehouseNode"):
        return "nodes"
    if "Root" in class_name or class_name in ("SchemaRoot", "QuerySchemaRoot"):
        return "core"
    if "TypeProps" in class_name:
        return "type_props"
    return "other"


def split_schema():
    """Split schema.py into modules."""
    if not SCHEMA_PY.exists():
        sys.stderr.write(f"Error: {SCHEMA_PY} does not exist. Run build-schema-python.sh first.\n")
        return

    sys.stderr.write(f"Reading {SCHEMA_PY}...\n")
    content = SCHEMA_PY.read_text()
    tree = ast.parse(content, filename=str(SCHEMA_PY))

    # Extract header
    header_lines = []
    for node in tree.body:
        if isinstance(node, ast.Import | ast.ImportFrom | ast.Expr):
            start = node.lineno - 1
            end = node.end_lineno if hasattr(node, "end_lineno") else node.lineno
            header_lines.extend(content.splitlines()[start:end])
        elif isinstance(node, ast.ClassDef):
            break

    header = "\n".join(header_lines)
    if header and not header.endswith("\n"):
        header += "\n"

    # Collect all classes
    all_classes: dict[str, ast.ClassDef] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            all_classes[node.name] = node

    sys.stderr.write(f"Found {len(all_classes)} classes\n")

    # Analyze dependencies for each class
    runtime_deps: dict[str, set[str]] = {}
    type_checking_deps: dict[str, set[str]] = {}

    for name, class_def in all_classes.items():
        runtime_deps[name] = find_runtime_dependencies(class_def, all_classes)
        type_checking_deps[name] = find_type_checking_dependencies(class_def, all_classes)

    # Categorize classes
    categories: dict[str, list[tuple[str, ast.ClassDef]]] = defaultdict(list)
    for name, class_def in all_classes.items():
        category = categorize_class(name, class_def)
        categories[category].append((name, class_def))

    sys.stderr.write("\nCategories:\n")
    for cat, classes in categories.items():
        sys.stderr.write(f"  {cat}: {len(classes)} classes\n")

    # For each category, determine what it needs to import
    category_runtime_imports: dict[str, set[str]] = defaultdict(set)
    category_type_checking_imports: dict[str, set[str]] = defaultdict(set)

    for category, class_list in categories.items():
        for class_name, _ in class_list:
            # Runtime deps: import from other categories
            for dep in runtime_deps[class_name]:
                dep_category = next(
                    (cat for cat, classes in categories.items() if any(n == dep for n, _ in classes)), None
                )
                if dep_category and dep_category != category:
                    category_runtime_imports[category].add(dep_category)

            # Type-checking deps: import from other categories
            for dep in type_checking_deps[class_name]:
                dep_category = next(
                    (cat for cat, classes in categories.items() if any(n == dep for n, _ in classes)), None
                )
                if dep_category and dep_category != category:
                    category_type_checking_imports[category].add(dep_category)

    # Create output directory
    SCHEMA_DIR.mkdir(exist_ok=True)

    # Write category files
    for category, class_list in categories.items():
        if not class_list:
            continue

        output_file = SCHEMA_DIR / f"{category}.py"
        sys.stderr.write(f"\nWriting {len(class_list)} classes to {output_file}...\n")
        sys.stderr.write(f"  Runtime imports: {sorted(category_runtime_imports[category])}\n")
        sys.stderr.write(f"  TYPE_CHECKING imports: {sorted(category_type_checking_imports[category])}\n")

        class_sources = []
        for name, class_def in class_list:
            start_line = class_def.lineno - 1
            end_line = class_def.end_lineno if hasattr(class_def, "end_lineno") else class_def.lineno
            class_source = "\n".join(content.splitlines()[start_line:end_line])
            class_sources.append((name, class_source))

        with open(output_file, "w") as f:
            if category != "enums":
                f.write("# ruff: noqa: F405  # Star imports are intentional\n")

            f.write(header)
            f.write("\n")

            # Runtime imports (enums are always imported at runtime - they're fast)
            if category != "enums":
                f.write("from posthog.schema.enums import *  # noqa: F403, F401\n")

            # Other runtime imports
            for dep_category in sorted(category_runtime_imports[category]):
                if dep_category != "enums":
                    f.write(f"from posthog.schema.{dep_category} import *  # noqa: F403, F401\n")

            if category_runtime_imports[category] or category_type_checking_imports[category]:
                f.write("\n")

            # TYPE_CHECKING imports
            type_checking_only = category_type_checking_imports[category] - category_runtime_imports[category]
            if type_checking_only:
                f.write("from typing import TYPE_CHECKING\n\n")
                f.write("if TYPE_CHECKING:\n")
                for dep_category in sorted(type_checking_only):
                    f.write(f"    from posthog.schema.{dep_category} import *  # noqa: F403, F401\n")
                f.write("\n")

            # Write classes
            for _name, class_source in class_sources:
                f.write(class_source)
                f.write("\n\n")

    # Create __init__.py
    sys.stderr.write("\nCreating __init__.py...\n")
    init_content = '''# mypy: disable-error-code="assignment"
"""
Schema module - split into submodules for faster imports.

This module provides backward compatibility. For faster imports, use:
    from posthog.schema.enums import HogQLQueryModifiers
    from posthog.schema.queries import HogQLQuery
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Type checkers see everything immediately
    from posthog.schema.core import *  # noqa: F403, F401
    from posthog.schema.enums import *  # noqa: F403, F401
    from posthog.schema.filters import *  # noqa: F403, F401
    from posthog.schema.nodes import *  # noqa: F403, F401
    from posthog.schema.other import *  # noqa: F403, F401
    from posthog.schema.queries import *  # noqa: F403, F401
    from posthog.schema.type_props import *  # noqa: F403, F401
else:
    # Runtime: lazy imports for faster startup
    import importlib
    from types import ModuleType

    _lazy_modules: dict[str, ModuleType] = {}

    def _get_module(name: str) -> ModuleType:
        """Lazily import a submodule using importlib to avoid recursion."""
        if name not in _lazy_modules:
            # Use importlib to import submodules directly, bypassing __init__.py
            module = importlib.import_module(f"posthog.schema.{name}")
            _lazy_modules[name] = module
        return _lazy_modules[name]

    def __getattr__(name: str):
        """Lazy import classes from appropriate submodule."""
        # Try each module in dependency order
        for module_name in ["enums", "type_props", "filters", "nodes", "queries", "core", "other"]:
            try:
                module = _get_module(module_name)
                if hasattr(module, name):
                    return getattr(module, name)
            except (ImportError, AttributeError):
                continue
        raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
'''

    (SCHEMA_DIR / "__init__.py").write_text(init_content)

    # Move original schema.py to _generated.py as backup
    if SCHEMA_PY.exists():
        sys.stderr.write(f"\nMoving {SCHEMA_PY} to {GENERATED_SCHEMA} as backup...\n")
        GENERATED_SCHEMA.parent.mkdir(exist_ok=True)
        SCHEMA_PY.rename(GENERATED_SCHEMA)

    sys.stderr.write("\nDone! Schema split into modules.\n")


if __name__ == "__main__":
    split_schema()
