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

import io
import re
import ast
import json
import argparse
import tokenize
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


def segment(tree: ast.Module, lines: list[str]) -> tuple[dict[str, tuple[int, int]], int]:
    segments: dict[str, tuple[int, int]] = {}
    header_end = 0
    prev_end = 0
    for node in tree.body:
        start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
        j = start - 2
        while j > prev_end - 1 and (lines[j].lstrip().startswith("#") or lines[j].strip() == ""):
            j -= 1
        found = names_of(node)
        for name in found:
            segments[name] = (j + 2, node.end_lineno or start)
        if not found:
            header_end = node.end_lineno or start
        prev_end = node.end_lineno or start
    return segments, header_end


def deepen_relative_imports(text: str) -> str:
    """Add one dot to every relative import: the modules now sit a level deeper.

    Matches any depth and both forms (``from .x import y``, ``from . import x``), and has
    to run over function bodies as well as the header — a deferred import inside a function
    is the one that fails at call time rather than at import, so nothing catches it early.
    """
    # [ \t] not \s: \s matches newlines, so ^\s* can span a blank line and swallow it.
    return re.sub(r"(?m)^([ \t]*)from (\.+)", r"\1from .\2", text)


def requalify(body: str, self_module: str, owner: dict[str, str]) -> tuple[str, set[str], set[str]]:
    """Prefix foreign symbols with their module, touching NAME tokens only.

    Regex would also rewrite the same word inside docstrings, comments, and string
    literals. tokenize sees the difference, so prose that happens to mention a
    function name survives untouched.
    """
    edits: list[tuple[tuple[int, int], tuple[int, int], str]] = []
    used: set[str] = set()
    names: set[str] = set()
    prev = ""
    for tok in tokenize.generate_tokens(io.StringIO(body).readline):
        if tok.type == tokenize.NAME:
            names.add(tok.string)
        if tok.type == tokenize.NAME and prev not in {".", "def", "class"}:
            module = owner.get(tok.string)
            if module is not None and module != self_module:
                used.add(module)
                edits.append((tok.start, tok.end, f"{module}.{tok.string}"))
        if tok.type not in (
            tokenize.NL,
            tokenize.NEWLINE,
            tokenize.INDENT,
            tokenize.DEDENT,
            tokenize.COMMENT,
        ):
            prev = tok.string

    lines = body.splitlines(keepends=True)
    for (srow, scol), (_, ecol), replacement in reversed(edits):
        line = lines[srow - 1]
        lines[srow - 1] = line[:scol] + replacement + line[ecol:]
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
    segments, header_end = segment(tree, lines)

    if args.skeleton:
        ordered = sorted(segments, key=lambda n: segments[n][0])
        print(json.dumps({"UNASSIGNED": {"doc": "TODO one line per module", "symbols": ordered}}, indent=2))
        return 0
    if args.layout is None:
        parser.error("a layout is required unless --skeleton is given")

    raw: dict[str, dict] = json.loads(args.layout.read_text())
    # State every module needs its own copy of (a logger) goes under "__shared__", so no
    # module has to import a sibling just to log. Kept out of `modules` so the coverage
    # check and the write loop read a dict nothing has mutated.
    shared_names = raw.get(SHARED, {}).get("symbols", [])
    modules = {name: spec for name, spec in raw.items() if name != SHARED}
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

    package = args.package_dir or args.source.with_suffix("")
    package.mkdir(parents=True, exist_ok=True)
    for module, spec in modules.items():
        ordered = sorted(spec["symbols"], key=lambda n: segments[n][0])
        body = "\n\n".join("".join(lines[segments[n][0] - 1 : segments[n][1]]).strip("\n") for n in ordered) + "\n"
        # Deferred imports sit inside function bodies, so the body needs deepening too.
        # This runs before the sibling imports below, which are already at the right depth.
        body = deepen_relative_imports(body)
        body, used, names = requalify(body, module, owner)
        siblings = "".join(f"from . import {m}\n" for m in sorted(used))
        # Only carry shared state into modules that reference it: `ruff --fix` prunes an
        # unused import, but never an unused module-level assignment, so a blanket copy
        # leaves a dead logger in every module that doesn't log. `names` comes from the
        # tokenizer, so a mention inside a docstring does not count as a reference.
        carried = "".join(src for name, src in shared_src.items() if name in names)
        (package / f"{module}.py").write_text(f'"""{spec["doc"]}"""\n\n{header}{siblings}\n{carried}\n\n{body}')
        print(f"{module + '.py':<26} {len(ordered):>3} symbols  deps={sorted(used) or '-'}")

    init_doc = args.init_doc or f"{package.name} for {package.parent.name}. One module per concern."
    (package / "__init__.py").write_text(f'"""{init_doc}"""\n')
    args.source.unlink()
    print(f"\nwrote {len(modules)} modules to {package}/ and removed {args.source}")
    if shared_names:
        print(f"shared state carried into the modules that use it: {sorted(shared_names)}")
    print("next: ruff check --fix, ruff format, then verify_pure_move.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
