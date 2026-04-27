#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
# ruff: noqa: T201 allow print statements
"""
Verify ci-dagster.yml's path filter covers every module imported by dagster files.

Dagster test selection relies on a dorny/paths-filter allowlist in
.github/workflows/ci-dagster.yml. If a dagster file imports a module that
isn't covered, changes to that module won't trigger dagster tests on PRs —
the miss is only caught on master, after merge.

This script:
  1. Finds every dagster source file (posthog/dags/**, products/*/dags/**)
  2. Extracts imports via AST
  3. Resolves each internal (posthog / ee / products / common) import to a
     concrete file path
  4. Checks every resolved path is matched by at least one filter pattern

Usage:
    uv run .github/scripts/check-dagster-paths.py
"""

import re
import ast
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci-dagster.yml"

INTERNAL_PREFIXES = ("posthog.", "ee.", "products.", "common.")


def find_dag_files() -> list[Path]:
    files = list((REPO_ROOT / "posthog" / "dags").rglob("*.py"))
    for dags_dir in (REPO_ROOT / "products").glob("*/dags"):
        files.extend(dags_dir.rglob("*.py"))
    files.extend((REPO_ROOT / "ee" / "billing" / "dags").rglob("*.py"))
    return files


def extract_imports(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return set()
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level != 0 or not node.module:
                continue
            out.add(node.module)
            # `from pkg import submodule` — submodule may itself be a module
            for alias in node.names:
                out.add(f"{node.module}.{alias.name}")
    return out


def resolve_module(module: str) -> Path | None:
    """Resolve a dotted module name to a file under REPO_ROOT.

    Walks up the hierarchy so `from posthog.utils import foo` resolves to
    posthog/utils.py (the attribute `foo` isn't a submodule). Namespace
    packages (directories with no __init__.py, e.g. posthog/hogql/) resolve
    to a probe path under the directory so filter patterns matching the dir
    are correctly recognized as covering the import.
    """
    parts = module.split(".")
    while parts:
        py_file = REPO_ROOT.joinpath(*parts).with_suffix(".py")
        if py_file.is_file():
            return py_file.relative_to(REPO_ROOT)
        init_file = REPO_ROOT.joinpath(*parts, "__init__.py")
        if init_file.is_file():
            return init_file.relative_to(REPO_ROOT)
        dir_candidate = REPO_ROOT.joinpath(*parts)
        if dir_candidate.is_dir() and any(dir_candidate.rglob("*.py")):
            return dir_candidate.relative_to(REPO_ROOT) / "__namespace_probe__.py"
        parts.pop()
    return None


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Convert a dorny/paths-filter (micromatch) pattern to a regex.

    Supports `**/` (zero-or-more path segments), `**` (cross-segment wildcard),
    and `*` (single-segment wildcard) — enough for the patterns we use.
    """
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def load_filter_patterns() -> list[str]:
    data = yaml.safe_load(WORKFLOW.read_text())
    for job in data.get("jobs", {}).values():
        for step in job.get("steps", []) or []:
            if step.get("id") == "filter":
                filters_yaml = step["with"]["filters"]
                return yaml.safe_load(filters_yaml).get("dagster", [])
    raise RuntimeError("Could not find the `filter` step in ci-dagster.yml")


def main() -> int:
    patterns = load_filter_patterns()
    regexes = [glob_to_regex(p) for p in patterns]

    dag_files = find_dag_files()
    print(f"Scanning {len(dag_files)} dagster files against {len(patterns)} filter patterns...")

    importers_by_module: dict[str, set[Path]] = {}
    for f in dag_files:
        for module in extract_imports(f):
            if not module.startswith(INTERNAL_PREFIXES):
                continue
            importers_by_module.setdefault(module, set()).add(f)

    missing: dict[str, tuple[Path, set[Path]]] = {}
    for module, importers in importers_by_module.items():
        resolved = resolve_module(module)
        if resolved is None:
            continue
        file_path = resolved.as_posix()
        if not any(r.match(file_path) for r in regexes):
            missing[module] = (resolved, importers)

    if missing:
        print("\nDagster path filter is missing coverage for the following modules:\n")
        for module, (resolved, importers) in sorted(missing.items()):
            print(f"  {module}  →  {resolved}")
            for imp in sorted(importers):
                print(f"      imported by {imp.relative_to(REPO_ROOT)}")
        print(
            "\nAdd a matching path to the `dagster:` filter in "
            ".github/workflows/ci-dagster.yml, or broaden an existing pattern."
        )
        return 1

    print(f"All {len(importers_by_module)} internal imports are covered.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
