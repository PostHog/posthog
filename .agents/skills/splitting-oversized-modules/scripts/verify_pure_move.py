#!/usr/bin/env python3
# ruff: noqa: T201 — CLI tool; stdout is the intended output
"""Prove a split moved code without changing it.

    git show HEAD:products/foo/backend/logic.py > /tmp/before.py
    uv run --no-project python verify_pure_move.py /tmp/before.py products/foo/backend/logic

Compares every top-level definition before and after, ignoring the module
qualification the split introduces (`get_run` vs `run_queries.get_run`) and any
formatting the formatter changed. Reports symbols that went missing, appeared from
nowhere, got duplicated across modules, or actually changed.

This is the check that makes a large split reviewable: "48 files changed" means
nothing on its own, but "every definition is byte-identical modulo qualification"
is a claim a reviewer can trust. Works the same for a test-file split (compare
test classes) since it just diffs top-level definitions.
"""

from __future__ import annotations

import re
import ast
import sys
import argparse
from pathlib import Path


def definitions(source: str) -> dict[str, ast.stmt]:
    out: dict[str, ast.stmt] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            out[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out[node.target.id] = node
    return out


def canonical(node: ast.stmt, modules: list[str], deepen: bool = False) -> str:
    """Unparse, then collapse module qualification so both sides compare equal.

    Do this textually on the unparsed form, not with a NodeTransformer: a transformer
    that rewrites `mod.attr` into `attr` is order-sensitive on nested attributes and
    reports differences that are not there. Text canonicalization is symmetric.
    """
    text = ast.unparse(node)
    # The split adds exactly one dot to every relative import, since the modules sit a level
    # deeper. Apply that same transformation to the before side rather than collapsing depth
    # on both: collapsing would accept an import deepened by two levels, which imports from
    # somewhere else entirely and only fails when the enclosing function runs.
    if deepen:
        text = re.sub(r"\bfrom (\.+)", r"from .\1", text)
    if modules:
        alternation = "|".join(sorted(modules, key=len, reverse=True))
        text = re.sub(rf"\b({alternation})\.", "", text)
        # bare module names appear as arguments, e.g. patch.object(ci_status, "x")
        text = re.sub(rf"\b({alternation})\b", "<module>", text)
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path, help="the original single file (e.g. from git show)")
    parser.add_argument("after", type=Path, help="the package directory it became")
    parser.add_argument(
        "--also-strip",
        nargs="*",
        default=[],
        help="extra names to treat as module qualification, e.g. the old module's own name",
    )
    parser.add_argument(
        "--strip-package",
        type=Path,
        help="also strip the module names in this package — use when verifying a test split, "
        "since the tests reference the source package's modules, not their own",
    )
    args = parser.parse_args()

    modules = [p.stem for p in sorted(args.after.glob("*.py")) if p.stem != "__init__"]
    strip = modules + list(args.also_strip)
    if args.strip_package:
        strip += [p.stem for p in sorted(args.strip_package.glob("*.py")) if p.stem != "__init__"]

    before = {name: canonical(node, strip, deepen=True) for name, node in definitions(args.before.read_text()).items()}

    forms: dict[str, set[str]] = {}
    where: dict[str, list[str]] = {}
    for path in sorted(args.after.glob("*.py")):
        if path.stem == "__init__":
            continue
        for name, node in definitions(path.read_text()).items():
            forms.setdefault(name, set()).add(canonical(node, strip))
            where.setdefault(name, []).append(path.name)

    missing = sorted(set(before) - set(forms))
    unexpected = sorted(set(forms) - set(before))
    changed = sorted(n for n in set(before) & set(forms) if before[n] not in forms[n])
    # Shared module state (a logger, a compiled regex) is legitimately repeated once per
    # module. Identical copies are fine; copies that drifted apart are a real finding.
    repeated = sorted(n for n, mods in where.items() if len(mods) > 1)
    conflicting = sorted(n for n in repeated if len(forms[n]) > 1)

    print(f"definitions: {len(before)} before -> {len(forms)} after")
    print(f"missing:     {missing or 'none'}")
    print(f"unexpected:  {unexpected or 'none'}")
    print(f"changed:     {changed or 'none'}")
    print(f"conflicting copies: {conflicting or 'none'}")
    if repeated:
        print(f"repeated identically across modules (per-module state): {repeated}")

    if missing or unexpected or changed or conflicting:
        print("\nNOT a pure move — inspect the symbols above before committing.")
        return 1
    print("\nPure move confirmed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
