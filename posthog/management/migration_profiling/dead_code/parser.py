"""AST-based parser for Django migration files.

We deliberately do NOT import the migration modules — importing runs
top-level code, drags in the full Django app registry, and forces us to
have a working DB connection. AST walking gives us everything detectors
need (operation class names, kwargs, RunPython callable bodies) with zero
side effects.

Supported operations cover the ones detectors currently care about:
``AddField`` / ``RemoveField`` / ``AlterField`` / ``RenameField`` /
``CreateModel`` / ``DeleteModel`` / ``RenameModel`` / ``AddIndex`` /
``RemoveIndex`` / ``RunPython`` / ``RunSQL`` / ``SeparateDatabaseAndState``.
Anything else lands as ``OperationNode`` with a raw class name and any
extractable kwargs — detectors can ignore unknowns.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Per-operation positional-arg name lookup. Keys match Django's signature.
_POSITIONAL_ARGS: dict[str, list[str]] = {
    "AddField": ["model_name", "name", "field"],
    "RemoveField": ["model_name", "name"],
    "AlterField": ["model_name", "name", "field"],
    "RenameField": ["model_name", "old_name", "new_name"],
    "CreateModel": ["name", "fields"],
    "DeleteModel": ["name"],
    "RenameModel": ["old_name", "new_name"],
    "AddIndex": ["model_name", "index"],
    "RemoveIndex": ["model_name", "name"],
    "AddConstraint": ["model_name", "constraint"],
    "RemoveConstraint": ["model_name", "name"],
    "RunPython": ["code", "reverse_code"],
    "RunSQL": ["sql", "reverse_sql"],
    "SeparateDatabaseAndState": ["database_operations", "state_operations"],
}


@dataclass
class OperationNode:
    """One element of a Migration's ``operations = [...]`` list."""

    class_name: str
    kwargs: dict[str, Any] = field(default_factory=dict)
    # For RunPython: the source text of the referenced callable's body
    # (None if the code arg can't be resolved to a module-level def).
    runpython_callable_name: str | None = None
    runpython_callable_body_source: str | None = None
    # ``is_noop`` is True when the RunPython explicitly uses
    # ``migrations.RunPython.noop`` as its forward code.
    runpython_is_explicit_noop: bool = False


@dataclass
class ParsedMigration:
    """A migration file parsed into structured operation metadata."""

    app: str
    name: str  # filename without ``.py``
    path: Path
    operations: list[OperationNode] = field(default_factory=list)
    # Module-level functions used by RunPython, keyed by callable name.
    module_functions: dict[str, ast.FunctionDef] = field(default_factory=dict)


def parse_migration_file(path: Path, app: str | None = None) -> ParsedMigration | None:
    """Parse a single migration file. Returns ``None`` on errors so a single
    bad file doesn't break a whole-tree scan."""
    if app is None:
        app = _infer_app_from_path(path)
    try:
        source = path.read_text()
    except OSError:
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    parsed = ParsedMigration(app=app, name=path.stem, path=path)

    # Collect module-level functions so RunPython references can be resolved.
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            parsed.module_functions[node.name] = node

    # Find the Migration class and walk its ``operations = [...]`` assignment.
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if not _is_migration_class(node):
            continue
        for class_stmt in node.body:
            ops_list = _extract_operations_list(class_stmt)
            if ops_list is None:
                continue
            for elt in ops_list:
                op = _parse_operation_element(elt, parsed.module_functions)
                if op is not None:
                    parsed.operations.append(op)
            break  # only one operations = [...] expected
        break  # only one Migration class expected
    return parsed


def find_migration_files(repo_root: Path) -> list[Path]:
    """Discover every Django migration file under ``repo_root``.

    Walks the canonical PostHog layout: ``posthog/migrations``, ``ee/migrations``,
    and ``products/*/backend/migrations``. Skips ``__init__.py`` and any
    file not starting with a digit (those are convention helpers like
    ``max_migration.txt``, not migrations).
    """
    candidates: list[Path] = []
    for glob_pattern in (
        "posthog/migrations/[0-9]*.py",
        "ee/migrations/[0-9]*.py",
        "products/*/backend/migrations/[0-9]*.py",
    ):
        candidates.extend(sorted(repo_root.glob(glob_pattern)))
    return candidates


# ---------- internals ----------


def _infer_app_from_path(path: Path) -> str:
    """Derive the Django ``app_label`` from a migration file's path.

    - ``posthog/migrations/0001_initial.py`` → ``posthog``
    - ``ee/migrations/0001_initial.py`` → ``ee``
    - ``products/conversations/backend/migrations/0001_initial.py`` → ``conversations``
    """
    parts = path.parts
    # Walk up looking for "migrations" — its parent is the app dir (for
    # posthog/ee) or grandparent (for products/<app>/backend).
    try:
        idx = parts.index("migrations")
    except ValueError:
        return "<unknown>"
    if idx == 0:
        return "<unknown>"
    parent = parts[idx - 1]
    if parent == "backend" and idx >= 3 and parts[idx - 3] == "products":
        return parts[idx - 2]
    return parent


def _is_migration_class(node: ast.ClassDef) -> bool:
    """Detect ``class Migration(migrations.Migration):``."""
    if node.name != "Migration":
        return False
    return True  # name suffices; bases shape varies (some inherit from helpers)


def _extract_operations_list(stmt: ast.stmt) -> list[ast.expr] | None:
    """Return the literal list assigned to ``operations`` inside a class body."""
    if not isinstance(stmt, ast.Assign):
        return None
    for target in stmt.targets:
        if isinstance(target, ast.Name) and target.id == "operations":
            if isinstance(stmt.value, (ast.List, ast.Tuple)):
                return list(stmt.value.elts)
    return None


def _parse_operation_element(node: ast.expr, module_functions: dict[str, ast.FunctionDef]) -> OperationNode | None:
    """Parse one element of an ``operations`` list.

    Most elements are ``Call`` nodes like ``migrations.AddField(...)``. We
    accept both ``migrations.<Op>`` and bare ``<Op>`` forms.
    """
    if not isinstance(node, ast.Call):
        return None
    class_name = _resolve_call_class_name(node.func)
    if class_name is None:
        return None

    kwargs: dict[str, Any] = {}
    # Positional args mapped via the per-op signature lookup.
    positional_names = _POSITIONAL_ARGS.get(class_name, [])
    for i, arg in enumerate(node.args):
        if i >= len(positional_names):
            break
        kwargs[positional_names[i]] = _literal_or_repr(arg)
    # Keyword args.
    for kw in node.keywords:
        if kw.arg is None:
            continue
        kwargs[kw.arg] = _literal_or_repr(kw.value)

    op = OperationNode(class_name=class_name, kwargs=kwargs)

    if class_name == "RunPython":
        _attach_runpython_callable(op, node, module_functions)

    return op


def _resolve_call_class_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _literal_or_repr(node: ast.expr) -> Any:
    """Best-effort literal extraction. Falls back to the source repr for
    things that aren't literal-evaluable (e.g. ``models.CharField(...)``)."""
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        return _unparse(node)


def _unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return f"<{type(node).__name__}>"


def _attach_runpython_callable(op: OperationNode, call: ast.Call, module_functions: dict[str, ast.FunctionDef]) -> None:
    """For ``migrations.RunPython(<code>, ...)``, resolve ``<code>``.

    Recognized forms:
    - ``my_func`` → module-level function we can inspect.
    - ``migrations.RunPython.noop`` → explicit no-op.
    - lambdas / attribute lookups we don't recognise → skip.
    """
    code_node = call.args[0] if call.args else None
    if code_node is None:
        for kw in call.keywords:
            if kw.arg == "code":
                code_node = kw.value
                break
    if code_node is None:
        return

    # migrations.RunPython.noop sentinel.
    if isinstance(code_node, ast.Attribute) and code_node.attr == "noop":
        op.runpython_is_explicit_noop = True
        op.runpython_callable_name = "<noop>"
        return

    if isinstance(code_node, ast.Name):
        name = code_node.id
        op.runpython_callable_name = name
        func = module_functions.get(name)
        if func is not None:
            try:
                op.runpython_callable_body_source = ast.unparse(ast.Module(body=func.body, type_ignores=[]))
            except Exception:
                op.runpython_callable_body_source = None
