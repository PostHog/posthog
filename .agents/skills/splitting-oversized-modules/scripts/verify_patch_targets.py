#!/usr/bin/env python3
"""Check that every mock patch target in a test tree still resolves to a real attribute.

    PYTHONPATH=. .flox/cache/venv/bin/python verify_patch_targets.py \
        products/foo/backend/tests --prefix products.foo

Moving a function changes where it must be patched. A stale `patch("...logic.helper")`
raises at test time, but a *misdirected* one — patched on a module that no longer calls
it — passes the patch and silently fails to intercept, so the test exercises the real
implementation and may still pass for the wrong reason. Both cases are caught here in
seconds, without a database, which matters when the suite is slow or the test DB is busy.

Handles `patch("a.b.c")`, `mocker.patch("a.b.c")`, and `patch.object(module, "name")`, in
`test_*.py` and `conftest.py` alike — fixtures patch too, and a sweep that only rewrites
test files leaves conftest pointing at the old paths.
"""

from __future__ import annotations

import os
import re
import ast
import sys
import argparse
import importlib
from pathlib import Path


def resolve(target: str) -> str | None:
    """Import the longest module prefix of a dotted path, then walk the attributes."""
    parts = target.split(".")
    for cut in range(len(parts) - 1, 1, -1):
        try:
            obj = importlib.import_module(".".join(parts[:cut]))
        except ModuleNotFoundError:
            continue
        for attr in parts[cut:]:
            if not hasattr(obj, attr):
                return f"no attribute {attr!r} on {'.'.join(parts[:cut])}"
            obj = getattr(obj, attr)
        return None
    return "no importable module prefix"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tests", type=Path)
    parser.add_argument("--prefix", required=True, help="only check targets under this dotted prefix")
    parser.add_argument("--settings", default="posthog.settings", help="DJANGO_SETTINGS_MODULE")
    args = parser.parse_args()

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", args.settings)
    import django

    django.setup()

    wanted = re.compile(rf"^{re.escape(args.prefix)}[\w.]*$")
    broken: list[str] = []
    checked = 0

    # conftest.py matters as much as the test files: fixtures patch too, and a retarget
    # sweep over `test_*.py` alone silently leaves those behind.
    files = sorted({*args.tests.rglob("test_*.py"), *args.tests.rglob("conftest.py")})
    for path in files:
        tree = ast.parse(path.read_text())
        aliases = {
            (alias.asname or alias.name): f"{node.module}.{alias.name}"
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
            for alias in node.names
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            targets: list[str] = []
            if name == "patch" and node.args and isinstance(node.args[0], ast.Constant):
                if isinstance(node.args[0].value, str):
                    targets.append(node.args[0].value)
            elif name == "object" and isinstance(func, ast.Attribute) and len(node.args) >= 2:
                base, attr = node.args[0], node.args[1]
                if isinstance(base, ast.Name) and isinstance(attr, ast.Constant) and isinstance(attr.value, str):
                    if base.id in aliases:
                        targets.append(f"{aliases[base.id]}.{attr.value}")
            for target in targets:
                if not wanted.match(target):
                    continue
                problem = resolve(target)
                if problem:
                    broken.append(f"{path}:{node.lineno} {target} — {problem}")
                else:
                    checked += 1

    print(f"resolved {checked} patch targets under {args.prefix}")
    for entry in broken:
        print(f"  BROKEN {entry}")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
