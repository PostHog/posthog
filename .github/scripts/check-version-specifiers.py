#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""
CI check: flag unbounded >= version specifiers in pyproject.toml.

Prefer ~= (compatible release) over >= (unbounded floor). A bare >= lets any
future major version satisfy the requirement with no signal to reviewers or
tooling (Dependabot, security scanners) that an update is in-range.

Exemptions:
  - >= paired with an upper bound (< or <=) on the same requirement, e.g.
    "pkg>=1.0,<2.0" — that is an explicit bounded range, not a floor.
  - Environment markers are ignored when checking for upper bounds, so
    "pkg>=1.0; python_version<'3.13'" is correctly flagged as unbounded.
  - Comment lines and non-dependency fields (requires-python, etc.) are skipped.

Usage:
    python .github/scripts/check-version-specifiers.py

Exit codes:
    0 - No unbounded >= specifiers found
    1 - One or more unbounded >= specifiers found (fix: replace with ~=)
"""

import os
import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"

_HAS_GTE = re.compile(r">=")
_HAS_UPPER = re.compile(r"[<]=?")

# Matches a dep string that is the first (and only significant) quoted value on
# a TOML array line, i.e. lines like:    "somepackage>=1.0",
_DEP_LINE = re.compile(r'^\s*"([^"]+)"')

IN_GITHUB_ACTIONS = os.getenv("GITHUB_ACTIONS") == "true"


def _is_unbounded_gte(spec: str) -> bool:
    """Return True if spec contains >= with no accompanying upper-bound operator.

    Strips the environment marker (everything after the first ';') before
    checking for upper bounds, so 'pkg>=1.0; python_version<"3.13"' is
    correctly identified as unbounded.
    """
    version_part = spec.split(";", 1)[0]
    if not _HAS_GTE.search(version_part):
        return False
    return not _HAS_UPPER.search(version_part)


def collect_deps(data: dict) -> list[str]:
    """Return all requirement strings from dependency lists."""
    results: list[str] = []

    project = data.get("project", {})
    results.extend(project.get("dependencies", []))
    for deps in project.get("optional-dependencies", {}).values():
        results.extend(deps)

    uv = data.get("tool", {}).get("uv", {})

    # dev-dependencies: first-class declared requirements (legacy uv flat list)
    # constraint-dependencies / override-dependencies are intentionally excluded:
    # they express version floors on transitive deps where bare >= is correct usage.
    field = uv.get("dev-dependencies", [])
    if isinstance(field, list):
        results.extend(d for d in field if isinstance(d, str))

    # Grouped fields (dev, optional)
    for section_name in ("dev", "optional"):
        uv_section = uv.get(section_name, {})
        if isinstance(uv_section, list):
            results.extend(uv_section)
        elif isinstance(uv_section, dict):
            for deps in uv_section.values():
                results.extend(deps)

    # dependency-groups (PEP 735)
    for deps in data.get("dependency-groups", {}).values():
        results.extend(d for d in deps if isinstance(d, str))

    return results


def find_line_numbers(bad_deps: set[str]) -> dict[str, int]:
    """Return {dep_string: line_number} by scanning the raw file."""
    lines = PYPROJECT_PATH.read_text().splitlines()
    found: dict[str, int] = {}
    for lineno, line in enumerate(lines, start=1):
        m = _DEP_LINE.match(line)
        if m and m.group(1) in bad_deps:
            found[m.group(1)] = lineno
    return found


def annotate(dep: str, lineno: int | None) -> None:
    msg = f"Prefer ~= over >=: {dep!r} uses an unbounded floor. Use ~=X.Y or >=X,<Y instead."
    if IN_GITHUB_ACTIONS:
        if lineno is not None:
            print(f"::error file=pyproject.toml,line={lineno},title=Version specifier::{msg}")
        else:
            print(f"::error file=pyproject.toml,title=Version specifier::{msg}")
    else:
        loc = f"pyproject.toml:{lineno}" if lineno is not None else "pyproject.toml"
        print(f"  {loc}: {msg}")


def main() -> int:
    with open(PYPROJECT_PATH, "rb") as f:
        data = tomllib.load(f)

    violations = [dep for dep in collect_deps(data) if _is_unbounded_gte(dep)]

    if not violations:
        print("check-version-specifiers: OK")
        return 0

    line_numbers = find_line_numbers(set(violations))

    print("check-version-specifiers: FAIL — unbounded >= specifiers found in pyproject.toml")
    if not IN_GITHUB_ACTIONS:
        print()
        print("Prefer ~= (compatible release) over >= (unbounded floor).")
        print("  ~=X.Y    allows >=X.Y, <(X+1)    (minor-compat)")
        print("  ~=X.Y.Z  allows >=X.Y.Z, <X.(Y+1) (patch-compat)")
        print("If you need a wider range, use >=X,<Y to make the ceiling explicit.")
        print()

    for dep in violations:
        annotate(dep, line_numbers.get(dep))

    if not IN_GITHUB_ACTIONS:
        print()
    print(f"{len(violations)} violation(s) found.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
