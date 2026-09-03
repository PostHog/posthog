#!/usr/bin/env python3
# ruff: noqa: T201 — CLI tool; stdout is the intended output
"""Split one oversized module into a package, one module per concern.

    uv run --no-project python split_module.py products/foo/backend/logic.py layout.json

`layout.json` maps module name -> {"doc": str, "symbols": [...]} (see map_symbols.py
--skeleton). Every top-level symbol in the source must be assigned exactly once, or
this refuses to run — that check is what stops code from silently going missing.

What it does:
  - copies each symbol's source verbatim by AST line range
  - gives every new module the original import header (ruff strips what it doesn't need)
  - deepens relative imports one level (`from .models` -> `from ..models`)
  - requalifies cross-module references via tokenize (`get_run` -> `run_queries.get_run`)
    and adds the matching `from . import run_queries`
  - copies "__shared__" state (a logger, a compiled regex) into each module that uses it
  - writes a package __init__.py with a docstring and no re-exports (--init-doc to set it)

It does NOT reformat or fix imports. Run afterwards:

    ruff check <package>/ --fix && ruff format <package>/
    uv run --no-project python verify_pure_move.py <original> <package>
"""

from __future__ import annotations

import ast
import json
import argparse
from pathlib import Path

# Reserved layout key for module-level state each module needs its own copy of.
SHARED = "__shared__"


def names_of(node: ast.stmt) -> list[str]:
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return [node.name]
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def segment(tree: ast.Module, lines: list[str]) -> tuple[dict[str, tuple[int, int]], int, list[int]]:
    """Symbol -> (first_line, last_line), the header boundary, and any unsupported statements.

    Only statements *before* the first definition extend the header. A bare statement after
    one (a module-level `if`, an `assert`, a registration call) cannot be attributed to a
    concern, and copying it into every module would run its side effect N times, so it is
    reported and the caller refuses to split.
    """
    segments: dict[str, tuple[int, int]] = {}
    header_end = 0
    prev_end = 0
    late: list[int] = []
    seen_definition = False
    for node in tree.body:
        start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
        j = start - 2
        while j > prev_end - 1 and (lines[j].lstrip().startswith("#") or lines[j].strip() == ""):
            j -= 1
        found = names_of(node)
        for name in found:
            segments[name] = (j + 2, node.end_lineno or start)
        if found:
            seen_definition = True
        elif seen_definition:
            late.append(node.lineno)
        else:
            header_end = node.end_lineno or start
        prev_end = node.end_lineno or start
    return segments, header_end, late


def deepen_relative_imports(text: str) -> str:
    """Add one dot to every relative import: the modules now sit a level deeper.

    Locates the statements with the AST rather than by matching raw lines, so a docstring or
    string literal whose line happens to read ``from .models import Thing`` is left alone.
    Covers deferred imports inside function bodies too — those fail at call time rather than
    at import, so nothing catches a missed one early.
    """
    lines = text.splitlines(keepends=True)
    # Right-to-left so an earlier edit cannot shift a later column on the same line.
    spots = sorted(
        (node.lineno, node.col_offset)
        for node in ast.walk(ast.parse(text))
        if isinstance(node, ast.ImportFrom) and node.level > 0
    )
    for lineno, col in reversed(spots):
        line = lines[lineno - 1]
        dot = line.index(".", col)
        lines[lineno - 1] = line[:dot] + "." + line[dot:]
    return "".join(lines)


def shadowed_symbols(body: str, self_module: str, owner: dict[str, str]) -> list[str]:
    """Foreign symbol names that the moved code also binds locally.

    A local `get_run` makes the name ambiguous: requalifying its reads would point them at
    another module, and leaving them alone is only right because the local exists. Rather
    than resolve scopes, refuse and let a human rename the local — the same stance the
    module-name shadowing trap takes, and a one-line fix.
    """
    bound: dict[str, int] = {}
    for node in ast.walk(ast.parse(body)):
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            bound.setdefault(node.id, node.lineno)
        elif isinstance(node, ast.arg):
            bound.setdefault(node.arg, node.lineno)
        elif isinstance(node, ast.alias) and node.asname:
            bound.setdefault(node.asname, getattr(node, "lineno", 0))
    return [
        f"{name} (bound at line {line}, owned by {owner[name]})"
        for name, line in sorted(bound.items())
        if name in owner and owner[name] != self_module
    ]


def requalify(body: str, self_module: str, owner: dict[str, str]) -> tuple[str, set[str], set[str]]:
    """Prefix foreign symbols with their module, rewriting reads only.

    Uses `ast.Name` nodes in `Load` context rather than raw tokens, which excludes three
    things a token scan gets wrong: a name being *bound* (an assignment target or loop
    target would become `mod.name = ...`, which is valid Python writing to the wrong place),
    a parameter or keyword argument (`f(name=1)` would not even parse), and an attribute
    (`obj.name`). Strings and comments hold no Name nodes, so prose mentioning a function
    survives untouched.

    Returns the rewritten body, the modules it now depends on, and every name it reads.
    """
    tree = ast.parse(body)
    edits: list[tuple[int, int, int, str]] = []
    used: set[str] = set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Name):
            continue
        names.add(node.id)
        if not isinstance(node.ctx, ast.Load):
            continue
        module = owner.get(node.id)
        if module is not None and module != self_module:
            used.add(module)
            edits.append((node.lineno, node.col_offset, node.end_col_offset or node.col_offset, f"{module}.{node.id}"))

    lines = body.splitlines(keepends=True)
    # Right-to-left within each line so an earlier edit cannot shift a later column.
    for lineno, col, end_col, replacement in sorted(edits, reverse=True):
        line = lines[lineno - 1]
        lines[lineno - 1] = line[:col] + replacement + line[end_col:]
    return "".join(lines), used, names


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="module to split, e.g. products/foo/backend/logic.py")
    parser.add_argument("layout", type=Path, nargs="?", help="JSON layout: module -> {doc, symbols}")
    parser.add_argument(
        "--skeleton",
        action="store_true",
        help="print a layout skeleton with every symbol in one bucket, then exit. Edit it into "
        "concern-named modules and pass it back as the layout argument",
    )
    parser.add_argument(
        "--package-dir",
        type=Path,
        help="where to write the package (default: the source path without .py). Use this to split a "
        "test file into a directory that mirrors the source package, e.g. tests/logic/",
    )
    parser.add_argument(
        "--init-doc",
        default="",
        help="use this as the whole __init__.py docstring instead of the module-per-concern template "
        "(for a tests package, where the import advice does not apply)",
    )
    args = parser.parse_args()

    source = args.source.read_text()
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)
    segments, header_end, late = segment(tree, lines)

    if args.skeleton:
        ordered = sorted(segments, key=lambda n: segments[n][0])
        print(json.dumps({"UNASSIGNED": {"doc": "TODO one line per module", "symbols": ordered}}, indent=2))
        return 0
    if args.layout is None:
        parser.error("a layout is required unless --skeleton is given")

    if late:
        print(f"{args.source} has top-level statements after its first definition, on lines:")
        print(f"  {late}")
        print("Those cannot be attributed to a concern, and copying them into every module")
        print("would run their side effects once per module. Move them into a function or")
        print("above the first definition, then split.")
        return 1

    raw: dict[str, dict] = json.loads(args.layout.read_text())
    # State every module needs its own copy of (a logger) goes under "__shared__", so no
    # module has to import a sibling just to log. Kept out of `modules` so the coverage
    # check and the write loop read a dict nothing has mutated.
    shared_names = raw.get(SHARED, {}).get("symbols", [])
    modules = {name: spec for name, spec in raw.items() if name != SHARED}

    # A symbol listed twice would be emitted into both modules, and the verifier would read
    # the identical copies as shared state and still say "pure move" — so catch it here.
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for mod, spec in [*modules.items(), (SHARED, raw.get(SHARED, {"symbols": []}))]:
        for sym in spec["symbols"]:
            if sym in seen:
                duplicates.append(f"{sym} (in {seen[sym]} and {mod})")
            seen[sym] = mod
    if duplicates:
        print("layout assigns a symbol to more than one destination:")
        for entry in duplicates:
            print(f"  {entry}")
        return 1

    owner = {sym: mod for mod, spec in modules.items() for sym in spec["symbols"]}

    unassigned = sorted(set(segments) - set(owner) - set(shared_names))
    unknown = sorted((set(owner) | set(shared_names)) - set(segments))
    if unassigned or unknown:
        print("layout does not cover the source.")
        print(f"  unassigned:    {unassigned}")
        print(f"  not in source: {unknown}")
        print(f'  (module state belongs under "{SHARED}", not in a module)')
        return 1

    docstring_end = tree.body[0].end_lineno if ast.get_docstring(tree) else 0
    header = deepen_relative_imports("".join(lines[docstring_end:header_end]))
    shared_src = {
        name: "".join(lines[segments[name][0] - 1 : segments[name][1]]).strip("\n") + "\n"
        for name in sorted(shared_names, key=lambda n: segments[n][0])
    }

    # Build every module first, so a refusal below leaves nothing half-written on disk.
    built: dict[str, tuple[str, set[str], int]] = {}
    shadowed: dict[str, list[str]] = {}
    for module, spec in modules.items():
        ordered = sorted(spec["symbols"], key=lambda n: segments[n][0])
        body = "\n\n".join("".join(lines[segments[n][0] - 1 : segments[n][1]]).strip("\n") for n in ordered) + "\n"
        # Deferred imports sit inside function bodies, so the body needs deepening too.
        # This runs before the sibling imports below, which are already at the right depth.
        body = deepen_relative_imports(body)
        collisions = shadowed_symbols(body, module, owner)
        if collisions:
            shadowed[module] = collisions
            continue
        body, used, names = requalify(body, module, owner)
        siblings = "".join(f"from . import {m}\n" for m in sorted(used))
        # Only carry shared state into modules that reference it: `ruff --fix` prunes an
        # unused import, but never an unused module-level assignment, so a blanket copy
        # leaves a dead logger in every module that doesn't log. `names` holds the names the
        # code reads, so a mention inside a docstring does not count as a reference.
        carried = "".join(src for name, src in shared_src.items() if name in names)
        built[module] = (f'"""{spec["doc"]}"""\n\n{header}{siblings}\n{carried}\n\n{body}', used, len(ordered))

    if shadowed:
        for module, collisions in shadowed.items():
            print(f"{module}.py binds names that belong to other modules:")
            for entry in collisions:
                print(f"  {entry}")
        print("Rename the local, then split — otherwise its reads cannot be told apart from")
        print("reads of the moved symbol.")
        return 1

    package = args.package_dir or args.source.with_suffix("")
    package.mkdir(parents=True, exist_ok=True)
    for module, (text, used, count) in built.items():
        (package / f"{module}.py").write_text(text)
        print(f"{module + '.py':<26} {count:>3} symbols  deps={sorted(used) or '-'}")

    init_doc = args.init_doc or f"{package.name} for {package.parent.name}. One module per concern."
    (package / "__init__.py").write_text(f'"""{init_doc}"""\n')
    if package.name == "models":
        print()
        print("This is a models package, so the empty __init__.py is not enough: Django imports")
        print("an app's `models` package but does not recurse into it, so the classes would be")
        print("missing from the app registry. Add aggregation imports to __init__.py — the one")
        print("case where re-exporting is right, and why no-init-reexports.yaml exempts models/.")
    args.source.unlink()
    print(f"\nwrote {len(modules)} modules to {package}/ and removed {args.source}")
    if shared_names:
        print(f"shared state carried into the modules that use it: {sorted(shared_names)}")
    print("next: ruff check --fix, ruff format, then verify_pure_move.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
