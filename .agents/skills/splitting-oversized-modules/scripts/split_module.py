#!/usr/bin/env python3
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
  - writes a package __init__.py with a docstring and no re-exports

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

INIT_DOC = '''"""{doc}

One module per concern, named after it. Import the module you need
(``from .{example} import ...``) rather than re-exporting through here: a single
binding per symbol keeps it obvious where behavior lives, and keeps test patch
targets pointing at the real definition.
"""
'''


def names_of(node: ast.stmt) -> list[str]:
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return [node.name]
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def segment(source: str) -> tuple[dict[str, tuple[int, int]], int]:
    lines = source.splitlines()
    segments: dict[str, tuple[int, int]] = {}
    header_end = 0
    prev_end = 0
    for node in ast.parse(source).body:
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


def requalify(body: str, self_module: str, owner: dict[str, str]) -> tuple[str, set[str]]:
    """Prefix foreign symbols with their module, touching NAME tokens only.

    Regex would also rewrite the same word inside docstrings, comments, and string
    literals. tokenize sees the difference, so prose that happens to mention a
    function name survives untouched.
    """
    edits: list[tuple[tuple[int, int], tuple[int, int], str]] = []
    used: set[str] = set()
    prev = ""
    for tok in tokenize.generate_tokens(io.StringIO(body).readline):
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
    for (srow, scol), (erow, ecol), replacement in reversed(edits):
        if srow != erow:  # a NAME token never spans lines
            raise AssertionError(f"multi-line NAME token at {srow}")
        line = lines[srow - 1]
        lines[srow - 1] = line[:scol] + replacement + line[ecol:]
    return "".join(lines), used


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="module to split, e.g. products/foo/backend/logic.py")
    parser.add_argument("layout", type=Path, help="JSON layout: module -> {doc, symbols}")
    parser.add_argument("--package-doc", default="", help="docstring for the new package __init__.py")
    args = parser.parse_args()

    source = args.source.read_text()
    lines = source.splitlines(keepends=True)
    segments, header_end = segment(source)
    layout: dict[str, dict] = json.loads(args.layout.read_text())

    # Module state every module needs its own copy of (a logger, a compiled regex) goes
    # under "__shared__". It is replicated into each module rather than owned by one,
    # so nothing has to import a sibling just to log.
    shared_names = layout.pop(SHARED, {}).get("symbols", [])
    owner = {sym: mod for mod, spec in layout.items() for sym in spec["symbols"]}

    unassigned = sorted(set(segments) - set(owner) - set(shared_names))
    unknown = sorted((set(owner) | set(shared_names)) - set(segments))
    if unassigned or unknown:
        print("layout does not cover the source.")
        print(f"  unassigned:    {unassigned}")
        print(f"  not in source: {unknown}")
        print(f'  (module state belongs under "{SHARED}", not in a module)')
        return 1

    tree = ast.parse(source)
    docstring_end = tree.body[0].end_lineno if ast.get_docstring(tree) else 0
    header = "".join(lines[docstring_end:header_end])
    header = re.sub(r"(?m)^(\s*)from \.(?=[A-Za-z_])", r"\1from ..", header)
    shared_src = {
        name: "".join(lines[segments[name][0] - 1 : segments[name][1]]).strip("\n") + "\n"
        for name in sorted(shared_names, key=lambda n: segments[n][0])
    }

    package = args.source.with_suffix("")
    package.mkdir(exist_ok=True)
    for module, spec in layout.items():
        ordered = sorted(spec["symbols"], key=lambda n: segments[n][0])
        body = "\n\n".join("".join(lines[segments[n][0] - 1 : segments[n][1]]).strip("\n") for n in ordered) + "\n"
        body, used = requalify(body, module, owner)
        siblings = "".join(f"from . import {m}\n" for m in sorted(used))
        # Only carry shared state into modules that reference it. `ruff --fix` prunes an
        # unused *import*, but never an unused module-level assignment, so a blanket copy
        # would leave a dead logger in every module that doesn't log.
        carried = "".join(src for name, src in shared_src.items() if re.search(rf"\b{name}\b", body))
        (package / f"{module}.py").write_text(f'"""{spec["doc"]}"""\n\n{header}{siblings}\n{carried}\n\n{body}')
        print(f"{module + '.py':<26} {len(ordered):>3} symbols  deps={sorted(used) or '-'}")

    example = next(iter(layout))
    (package / "__init__.py").write_text(
        INIT_DOC.format(doc=args.package_doc or f"{package.name} package.", example=example)
    )
    args.source.unlink()
    print(f"\nwrote {len(layout)} modules to {package}/ and removed {args.source}")
    if shared_names:
        print(f"shared state carried into the modules that use it: {sorted(shared_names)}")
    print("next: ruff check --fix, ruff format, then verify_pure_move.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
