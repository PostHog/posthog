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
  - Comment lines and non-dependency fields (requires-python, etc.) are skipped.

Usage:
    python .github/scripts/check-version-specifiers.py

Exit codes:
    0 - No unbounded >= specifiers found
    1 - One or more unbounded >= specifiers found (fix: replace with ~=)
"""

import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"

# Matches a PEP 508 requirement string that contains >= but no < or <= upper bound.
# We match the raw string because tomllib parses the value but not its operator semantics.
_HAS_GTE = re.compile(r">=")
_HAS_UPPER = re.compile(r"[<]=?")


def _is_unbounded_gte(spec: str) -> bool:
    """Return True if spec contains >= with no accompanying upper-bound operator."""
    if not _HAS_GTE.search(spec):
        return False
    # Strip the upper-bound test — only check the version operators, not the package name.
    # A requirement like "foo>=1.0,<2.0" has both >= and <, so it's bounded.
    return not _HAS_UPPER.search(spec)


def collect_deps(data: dict) -> list[tuple[str, str]]:
    """Return (section_label, requirement) pairs from all dependency lists."""
    results: list[tuple[str, str]] = []

    project = data.get("project", {})
    for dep in project.get("dependencies", []):
        results.append(("[project].dependencies", dep))

    for extra, deps in project.get("optional-dependencies", {}).items():
        for dep in deps:
            results.append((f"[project.optional-dependencies.{extra}]", dep))

    # uv tool sections
    for section_name in ("dev", "optional"):
        uv_deps = data.get("tool", {}).get("uv", {}).get(section_name, {})
        if isinstance(uv_deps, list):
            for dep in uv_deps:
                results.append((f"[tool.uv.{section_name}]", dep))
        elif isinstance(uv_deps, dict):
            for group, deps in uv_deps.items():
                for dep in deps:
                    results.append((f"[tool.uv.{section_name}.{group}]", dep))

    # dependency-groups (PEP 735)
    for group, deps in data.get("dependency-groups", {}).items():
        for dep in deps:
            if isinstance(dep, str):
                results.append((f"[dependency-groups.{group}]", dep))

    return results


def main() -> int:
    with open(PYPROJECT_PATH, "rb") as f:
        data = tomllib.load(f)

    violations: list[tuple[str, str]] = []
    for section, dep in collect_deps(data):
        if _is_unbounded_gte(dep):
            violations.append((section, dep))

    if not violations:
        print("check-version-specifiers: OK")
        return 0

    print("check-version-specifiers: FAIL — unbounded >= specifiers found in pyproject.toml")
    print()
    print("Prefer ~= (compatible release) over >= (unbounded floor).")
    print("  ~=X.Y    allows >=X.Y and <(X+1)  (minor-compat)")
    print("  ~=X.Y.Z  allows >=X.Y.Z and <X.(Y+1)  (patch-compat)")
    print("If you need a wider range, use >=X,<Y to make the ceiling explicit.")
    print()
    for section, dep in violations:
        print(f"  {section}: {dep!r}")
    print()
    print(f"{len(violations)} violation(s) found.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
