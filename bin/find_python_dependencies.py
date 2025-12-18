#!/usr/bin/env python3
"""
Find all local Python dependencies for a given entrypoint file.

This script uses grimp to build an import graph and find all upstream
dependencies (modules that the entrypoint imports, directly or transitively).
This is useful for determining which files need to trigger a rebuild of a worker.

Usage:
    python bin/find_python_dependencies.py posthog.temporal.subscriptions
    # Output: {"dependencies": ["posthog/utils.py", ...]}

    # Check if any changed files affect a worker
    python bin/find_python_dependencies.py posthog.temporal.subscriptions --check-changes "posthog/utils.py posthog/unrelated_file.py"
    # Output: {"affected": true, "matching_files": ["posthog/utils.py"]}
"""

import os
import sys
import json
import argparse
from pathlib import Path

import grimp

# Add repository root to Python path so grimp can find the packages
REPO_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

# All local Python packages in the repository
LOCAL_PACKAGES = ("posthog", "ee", "products", "common")


def build_import_graph(packages: tuple[str, ...]) -> grimp.ImportGraph:
    return grimp.build_graph(*packages)


def module_to_file(module: str) -> str | None:
    """
    Convert a module name (posthog.utils) to its file path (posthog/utils/__init__.py).
    """
    path = module.replace(".", "/")

    # Check for module.py first, then module/__init__.py
    if os.path.isfile(f"{path}.py"):
        return f"{path}.py"
    if os.path.isfile(f"{path}/__init__.py"):
        return f"{path}/__init__.py"

    return None


def find_all_dependency_files(graph: grimp.ImportGraph, entrypoint_module: str) -> set[str]:
    """
    Find all files that the entrypoint depends on.
    """
    module_dependencies = graph.find_upstream_modules(entrypoint_module)
    # Include the entrypoint itself to catch changes in the module itself.
    module_dependencies.add(entrypoint_module)
    file_dependencies = set()

    for module in module_dependencies:
        if file_path := module_to_file(module):
            file_dependencies.add(file_path)

    return file_dependencies


def check_if_changes_affect_entrypoint(
    graph: grimp.ImportGraph,
    entrypoint_module: str,
    changed_files: list[str],
) -> tuple[bool, list[str]]:
    """
    Check if any of the changed files are in the dependency tree of the entrypoint.
    """
    dependency_files = find_all_dependency_files(graph, entrypoint_module)

    # Normalize paths for comparison
    normalized_deps = {os.path.normpath(f) for f in dependency_files}
    normalized_changes = {os.path.normpath(f) for f in changed_files if f.endswith(".py")}

    matching = normalized_deps & normalized_changes

    return bool(matching), sorted(matching)


def main():
    parser = argparse.ArgumentParser(
        description="Find all local Python dependencies for a given entrypoint module.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "entrypoint",
        help="Module path to analyze (e.g., posthog.temporal.subscriptions)",
    )
    parser.add_argument(
        "--check-changes",
        metavar="FILES",
        help="Space-separated list of changed files to check against dependencies",
    )

    args = parser.parse_args()

    # Validate entrypoint format
    if "/" in args.entrypoint or args.entrypoint.endswith(".py"):
        sys.stderr.write(
            f"Error: Entrypoint should be a module path (e.g., 'posthog.temporal.subscriptions'), "
            f"not a file path ('{args.entrypoint}')\n"
        )
        sys.exit(1)

    try:
        sys.stderr.write(f"Building import graph for packages: {', '.join(LOCAL_PACKAGES)}...\n")
        graph = build_import_graph(LOCAL_PACKAGES)
        sys.stderr.write("Import graph built successfully.\n")

        if args.check_changes:
            changed_files = args.check_changes.split()
            affected, matching = check_if_changes_affect_entrypoint(graph, args.entrypoint, changed_files)
            sys.stdout.write(json.dumps({"affected": affected, "matching_files": matching}) + "\n")
        else:
            dependency_files = find_all_dependency_files(graph, args.entrypoint)
            sys.stdout.write(json.dumps({"dependencies": sorted(dependency_files)}) + "\n")

    except Exception as e:
        sys.stderr.write(f"Error detecting dependency relationship: {e}\n")
        sys.stderr.write("Falling back to assuming all changes affect the entrypoint.\n")
        if args.check_changes:
            # Err on the side of re-building in case we run into an error.
            sys.stdout.write(json.dumps({"affected": True, "matching_files": []}) + "\n")
        else:
            sys.stdout.write(json.dumps({"dependencies": []}) + "\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
