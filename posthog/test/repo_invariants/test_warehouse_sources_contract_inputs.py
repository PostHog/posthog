import ast
import subprocess
from collections import defaultdict
from collections.abc import Iterator
from functools import cache
from pathlib import Path

from hogli_commands.product.ast_helpers import lazy_reexport_map, lazy_reexport_prefixes
from hogli_commands.product.isolation import unwatched_modules

# Guards the backend:contract-check isolation of warehouse_sources.
# When only files outside the contract-check inputs change, turbo-discover.js skips the Django
# suite (Core, CorePOE, and the Temporal segment, which is skipped with it) and the jobs of the
# products that depend on warehouse_sources. That is sound only if outside code reaches no
# unwatched file through the facade. Otherwise a change to that file skips the outside tests that
# execute it (a silent coverage hole).
#
# For each name an outside file uses from the facade, this guard follows the imports from the
# facade module to the file that defines the name, including the lazy PEP 562 maps and re-exports
# through other modules. Every file on that path under backend/temporal/ must be an input. The
# files the defining file imports need not be. Its input is the whole repo, so it lives here and
# runs on every backend PR, not only when warehouse_sources changes. It fails on an import shape it
# cannot follow, so that a hand-out never drops out of the check without a trace.
#
# Files outside backend/temporal/ are not checked. The product lint's narrowed-inputs rule
# (has_narrowed_turbo_inputs) accepts backend/temporal/ as a wiring location and rejects other
# internal files as inputs, so those hand-outs stay unwatched until that rule changes.
#
# Registry lookups resolve vendors dynamically, so this guard cannot enumerate their
# dependencies. MSSQL stays in the contract inputs because data_warehouse's SQL migration
# tests depend on its optional schema field. Other registry dependencies can be skipped on
# PRs and narrowed merge-queue runs; the hourly full master run is their backstop.
#
# Deliberately uses stdlib ast over the files, NOT the repo's `grimp` dependency: grimp
# does not descend products/warehouse_sources/backend/temporal/data_imports/ (an implicit namespace package — no
# __init__.py), so its graph contains zero source modules and the guard would pass blind.

REPO_ROOT = Path(__file__).resolve().parents[3]
PRODUCT_DIR = REPO_ROOT / "products" / "warehouse_sources"
PRODUCT_PACKAGE = "products.warehouse_sources"
BACKEND_PACKAGE = "products.warehouse_sources.backend"
FACADE_PACKAGE = "products.warehouse_sources.backend.facade"
CHECKED_DIR = "backend/temporal/"
# Trees whose tests run outside the product's own job. The root conftest.py loads facade test helpers.
OUTSIDE_PATHS = ("posthog", "ee", "common", "products", "conftest.py")
# A longer chain of re-exports means an import cycle.
MAX_HOPS = 20


def _is_type_checking(node: ast.AST) -> bool:
    if not isinstance(node, ast.If):
        return False
    test = node.test
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


@cache
def _module_file(module: str) -> Path | None:
    path = REPO_ROOT / module.replace(".", "/")
    if path.with_suffix(".py").is_file():
        return path.with_suffix(".py")
    if (path / "__init__.py").is_file():
        return path / "__init__.py"
    return None


def _in_product(module: str) -> bool:
    return module.startswith(f"{PRODUCT_PACKAGE}.")


def _runtime_statements(body: list[ast.stmt]) -> Iterator[ast.stmt]:
    for node in body:
        if isinstance(node, ast.If):
            yield from _runtime_statements(node.orelse if _is_type_checking(node) else [*node.body, *node.orelse])
        elif isinstance(node, ast.Try):
            handlers = [stmt for handler in node.handlers for stmt in handler.body]
            yield from _runtime_statements([*node.body, *handlers, *node.orelse, *node.finalbody])
        else:
            yield node


def _absolute_module(node: ast.ImportFrom, package: str) -> str:
    if node.level == 0:
        return node.module or ""
    parts = package.split(".")
    base = parts[: len(parts) - node.level + 1]
    return ".".join([*base, node.module] if node.module else base)


# A lazy map names each module by its full path, relative to a prefix constant such as `_B`, or
# relative to the backend package.
def _lazy_targets(module: str, tree: ast.Module) -> dict[str, str]:
    lazy = lazy_reexport_map(tree)
    has_getattr = any(isinstance(node, ast.FunctionDef) and node.name == "__getattr__" for node in tree.body)
    assert lazy or not has_getattr, f"{module} defines __getattr__ without a lazy map this guard can read"
    bases = [*lazy_reexport_prefixes(tree), f"{BACKEND_PACKAGE}."]
    targets: dict[str, str] = {}
    for name, value in lazy.items():
        candidates = [value] if value.startswith("products.") else [base + value for base in bases]
        target = next((candidate for candidate in candidates if _module_file(candidate) is not None), None)
        assert target is not None, f"{module} maps {name!r} to {value!r}, which names no module"
        targets[name] = target
    return targets


@cache
def _imported_names(module: str) -> dict[str, tuple[str, str]]:
    file = _module_file(module)
    assert file is not None, f"{module} is no module"
    tree = ast.parse(file.read_text(), filename=str(file))
    package = module if file.name == "__init__.py" else module.rpartition(".")[0]
    names: dict[str, tuple[str, str]] = {}
    for node in _runtime_statements(tree.body):
        if isinstance(node, ast.ImportFrom):
            source = _absolute_module(node, package)
            for alias in node.names:
                names[alias.asname or alias.name] = (source, alias.name)
        elif isinstance(node, ast.Import) and module.startswith(FACADE_PACKAGE):
            assert not any(_in_product(alias.name) for alias in node.names), (
                f"{module} uses `import` on a product module; use `from ... import` so this guard can follow it"
            )
    for name, target in _lazy_targets(module, tree).items():
        names[name] = (target, name)
    return names


@cache
def _files_on_path(module: str, name: str) -> tuple[Path, ...]:
    files: list[Path] = []
    for _ in range(MAX_HOPS):
        if not _in_product(module):
            return tuple(files)
        file = _module_file(module)
        if file is not None:
            imported = _imported_names(module)
            if name in imported:
                files.append(file)
                module, name = imported[name]
                continue
        # `from package import module` hands out a submodule, also from a package without __init__.py.
        submodule_file = _module_file(f"{module}.{name}")
        if submodule_file is not None:
            return (*files, submodule_file)
        assert file is not None, f"{module} is no module"
        return (*files, file)
    raise AssertionError(f"re-exports of {name} do not end within {MAX_HOPS} modules")


def _outside_files_using_the_facade() -> list[Path]:
    result = subprocess.run(
        [
            "git",
            "grep",
            "-l",
            "-z",
            "-F",
            "-e",
            FACADE_PACKAGE,
            "-e",
            f"from {BACKEND_PACKAGE} import",
            "--",
            *OUTSIDE_PATHS,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    # git grep exits 1 when nothing matches.
    assert result.returncode in (0, 1), result.stderr.decode()
    files = [REPO_ROOT / name for name in result.stdout.decode().split("\0") if name.endswith(".py")]
    return [file for file in files if not file.is_relative_to(PRODUCT_DIR)]


def _runtime_nodes(node: ast.AST) -> Iterator[ast.AST]:
    # TYPE_CHECKING-only imports do not run, so they do not count.
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.If) and _is_type_checking(child):
            for stmt in child.orelse:
                yield stmt
                yield from _runtime_nodes(stmt)
            continue
        yield child
        yield from _runtime_nodes(child)


def _used_facade_names(tree: ast.AST, file: Path) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    module_aliases: dict[str, str] = {}
    attributes: list[tuple[str, str]] = []
    for node in _runtime_nodes(tree):
        if isinstance(node, ast.ImportFrom) and node.module == FACADE_PACKAGE:
            for alias in node.names:
                module_aliases[alias.asname or alias.name] = f"{FACADE_PACKAGE}.{alias.name}"
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(f"{FACADE_PACKAGE}."):
            found.update((node.module, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module == BACKEND_PACKAGE:
            assert all(alias.name != "facade" for alias in node.names), (
                f"{file}: import the facade modules by their full path, not their package"
            )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(FACADE_PACKAGE):
                    assert alias.asname, f"{file}: give `import {alias.name}` an alias so this guard can follow it"
                    module_aliases[alias.asname] = alias.name
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            attributes.append((node.value.id, node.attr))
    # `from ...facade import api as warehouse_facade` hands out names as attribute reads.
    found.update((module_aliases[alias], attr) for alias, attr in attributes if alias in module_aliases)
    return found


def test_outside_code_reaches_only_watched_files_through_the_facade() -> None:
    users: defaultdict[str, set[str]] = defaultdict(set)
    for file in _outside_files_using_the_facade():
        tree = ast.parse(file.read_text(), filename=str(file))
        for module, name in _used_facade_names(tree, file):
            for path in _files_on_path(module, name):
                rel = path.relative_to(PRODUCT_DIR).as_posix()
                if rel.startswith(CHECKED_DIR):
                    users[rel].add(file.relative_to(REPO_ROOT).as_posix())

    unwatched = unwatched_modules(PRODUCT_DIR, users)
    assert not unwatched, (
        f"Outside code reaches files under {CHECKED_DIR} of warehouse_sources through the facade that the "
        "backend:contract-check inputs do not watch, so a change to those files would skip the "
        "outside tests that execute them. Add each file to the backend:contract-check inputs in "
        "products/warehouse_sources/turbo.json:\n"
        + "\n".join(f"  {rel} (used by {', '.join(sorted(users[rel])[:3])})" for rel in sorted(unwatched))
    )
