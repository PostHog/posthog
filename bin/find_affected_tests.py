#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "grimp==3.13",
# ]
# ///
"""
Find test files affected by a set of changed source files.

Builds an import graph with grimp, computes a reverse dependency map
(source file -> test files), then outputs the set of test files that
transitively depend on any of the changed files.

Outputs JSON to stdout:
  - mode: "selective" (only run affected tests) or "full" (run everything)
  - affected_tests: list of test file paths (only when mode=selective)
  - suggested_shards: recommended shard count based on estimated duration

Usage:
    # From CLI
    uv run bin/find_affected_tests.py --changed-files "posthog/api/user.py posthog/models/team.py"

    # From stdin (one file per line)
    git diff --name-only origin/master...HEAD | uv run bin/find_affected_tests.py --stdin

    # Force full mode
    FORCE_FULL_TESTS=1 uv run bin/find_affected_tests.py --changed-files "posthog/api/user.py"

    # Just build and print map stats (no affected-test lookup)
    uv run bin/find_affected_tests.py --build-only
"""

import os
import re
import ast
import sys
import json
import time
import argparse
from collections import defaultdict
from pathlib import Path

import grimp

REPO_ROOT = Path(__file__).parent.parent.resolve()
DURATIONS_PATH = REPO_ROOT / ".test_durations"

LOCAL_PACKAGES = ("posthog", "ee", "products", "common")

# Patterns that identify test files
TEST_FILE_RE = re.compile(r"(^|/)test_[^/]*\.py$")
EVAL_FILE_RE = re.compile(r"(^|/)eval_[^/]*\.py$")

# Files/patterns that force a full test run when changed.
# Uses substring matching: any changed file containing one of these triggers a full run.
# Keep in sync with the dorny backend filter in .github/workflows/ci-backend.yml
# — run `--check-sync` to verify.
FULL_RUN_PATTERNS = (
    # Python infrastructure
    "conftest.py",
    "posthog/settings/",
    "posthog/test/",
    "manage.py",
    "pyproject.toml",
    "uv.lock",
    "requirements.txt",
    "requirements-dev.txt",
    "pytest.ini",
    "mypy.ini",
    ".test_durations",
    # CI / Docker infrastructure
    ".github/workflows/ci-backend.yml",
    ".github/clickhouse-versions.json",
    "docker-compose",
    "docker/clickhouse/",
    "bin/wait-for-docker",
    "bin/ci-wait-for-docker",
    # Non-Python files that affect generated Python code or test behavior
    "frontend/src/queries/schema.json",
    "frontend/src/products.json",  # Loaded at runtime by posthog/products.py
    "frontend/public/email/",
    "rust/feature-flags/src/properties/property_models.rs",
    "common/plugin_transpiler/src",
)

# Patterns in the dorny backend filter that don't affect test selection.
# These exist in dorny's gate to be conservative, but changing them alone
# doesn't require running any Python tests. Listed here so --check-sync
# can verify full coverage of the dorny list.
GATE_ONLY_PATTERNS = (
    "bin/build-schema-latest-versions.py",
    "bin/build-taxonomy-json.py",
    "bin/check_uv_python_compatibility.py",
    "bin/find_python_dependencies.py",
    "bin/granian_metrics.py",
    "bin/ty.py",
    "bin/unit_metrics.py",
)

# Max changed files before we give up and run everything
MAX_CHANGED_FILES = 50

# Target duration per shard in seconds (matches turbo-discover.js)
TARGET_SHARD_SECONDS = 10 * 60


def is_test_module(module: str, file_path: str | None) -> bool:
    if file_path is None:
        return False
    return bool(TEST_FILE_RE.search(file_path) or EVAL_FILE_RE.search(file_path))


def module_to_file(module: str) -> str | None:
    path = module.replace(".", "/")
    if os.path.isfile(f"{path}.py"):
        return f"{path}.py"
    if os.path.isfile(f"{path}/__init__.py"):
        return f"{path}/__init__.py"
    return None


def _ast_get_imports(filepath: str) -> set[str]:
    """Parse import statements from a Python file using the AST."""
    try:
        with open(filepath) as fh:
            source = fh.read()
        tree = ast.parse(source, filename=filepath)
    except (SyntaxError, UnicodeDecodeError, OSError):
        return set()

    file_imports: set[str] = set()
    dir_parts = os.path.dirname(filepath).replace("/", ".").split(".")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                file_imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                file_imports.add(node.module)
            elif node.level > 0:
                # Relative import — resolve from current package
                base_parts = dir_parts[: max(0, len(dir_parts) - node.level + 1)]
                if node.module:
                    file_imports.add(".".join([*base_parts, node.module]))
                elif node.names:
                    for alias in node.names:
                        file_imports.add(".".join([*base_parts, alias.name]))
    return file_imports


def _build_ast_reverse_map(
    grimp_files: set[str],
    grimp_test_files: set[str],
) -> tuple[dict[str, set[str]], set[str], set[str]]:
    """Build a reverse map for files grimp can't discover (missing __init__.py).

    Uses AST-based import parsing as a fallback. Only records edges that land
    on AST-only source files — grimp handles re-exports correctly so we defer
    to it for everything it can see. BFS seeds from both AST-only tests and
    grimp-visible tests, so grimp-test → AST-source dependencies are captured.

    Returns (reverse_map, ast_test_files, ast_source_files).
    """
    # Discover all .py files on disk under LOCAL_PACKAGES
    all_py: set[str] = set()
    for pkg in LOCAL_PACKAGES:
        for root, dirs, files in os.walk(pkg):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in files:
                if f.endswith(".py"):
                    all_py.add(os.path.join(root, f))

    # Files grimp missed
    ast_only_files = all_py - grimp_files

    if not ast_only_files:
        return {}, set(), set()

    # Build module->file mapping for ALL files (needed to resolve imports)
    module_to_filepath: dict[str, str] = {}
    for f in all_py:
        if f.endswith("/__init__.py"):
            mod = f[:-12].replace("/", ".")
        else:
            mod = f[:-3].replace("/", ".")
        module_to_filepath[mod] = f

    # Classify ast-only files into test and source
    ast_test_files: set[str] = set()
    ast_source_files: set[str] = set()
    for f in ast_only_files:
        if TEST_FILE_RE.search(f) or EVAL_FILE_RE.search(f):
            ast_test_files.add(f)
        else:
            ast_source_files.add(f)

    # For each ast-only test file, parse its imports and resolve to files.
    # BFS to find transitive dependencies.
    reverse_map: dict[str, set[str]] = defaultdict(set)

    # Cache parsed imports
    import_cache: dict[str, set[str]] = {}

    def resolve_imports(filepath: str) -> set[str]:
        """Resolve a file's imports to file paths."""
        if filepath in import_cache:
            return import_cache[filepath]

        raw_imports = _ast_get_imports(filepath)
        resolved: set[str] = set()
        for imp in raw_imports:
            parts = imp.split(".")
            for i in range(len(parts), 0, -1):
                candidate = ".".join(parts[:i])
                if candidate in module_to_filepath:
                    resolved.add(module_to_filepath[candidate])
                    break
        import_cache[filepath] = resolved
        return resolved

    # Seed BFS from both AST-only tests and grimp-visible tests. The latter
    # lets us catch grimp-test → AST-source edges that grimp itself misses.
    for test_file in ast_test_files | grimp_test_files:
        # BFS for transitive deps
        visited: set[str] = set()
        queue = [test_file]
        while queue:
            current = queue.pop()
            if current in visited:
                continue
            visited.add(current)
            for dep in resolve_imports(current):
                if dep not in visited:
                    queue.append(dep)

        # Only map ast-only source files — grimp already covers its own
        for dep_file in visited:
            if dep_file != test_file and dep_file in ast_source_files:
                reverse_map[dep_file].add(test_file)

    return reverse_map, ast_test_files, ast_source_files


def build_reverse_map() -> tuple[dict[str, list[str]], int, set[str]]:
    """Build reverse dependency map: source file -> test files that import it.

    Uses grimp for proper import resolution (handles re-exports, package
    structure), then supplements with AST-based parsing for files in
    directories missing __init__.py that grimp can't discover.

    Returns (reverse_map, total_test_count, all_known_source_files).
    all_known_source_files includes every non-test file discovered by either
    grimp or the AST fallback — files present here but absent from reverse_map
    have zero test dependents, so changing them cannot break any test.
    """
    start = time.monotonic()
    sys.stderr.write(f"Building import graph for packages: {', '.join(LOCAL_PACKAGES)}...\n")

    # Ensure repo root is on sys.path so grimp can find local packages
    repo_root_str = str(REPO_ROOT)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)

    graph = grimp.build_graph(*LOCAL_PACKAGES)

    elapsed_graph = time.monotonic() - start
    sys.stderr.write(f"Import graph built in {elapsed_graph:.1f}s ({len(graph.modules)} modules)\n")

    all_modules = graph.modules

    # Classify modules as test or source
    test_modules: set[str] = set()
    module_files: dict[str, str] = {}

    for module in all_modules:
        file_path = module_to_file(module)
        if file_path:
            module_files[module] = file_path
            if is_test_module(module, file_path):
                test_modules.add(module)

    sys.stderr.write(f"Found {len(test_modules)} test modules, {len(module_files)} total modules\n")

    # For each test module, find its upstream (transitive) dependencies
    # Then invert: source_file -> [test_files]
    reverse_map: dict[str, set[str]] = defaultdict(set)

    processed = 0
    for test_module in sorted(test_modules):
        test_file = module_files[test_module]

        try:
            upstream = graph.find_upstream_modules(test_module)
        except Exception as e:
            sys.stderr.write(f"  Warning: could not resolve deps for {test_module}: {e}\n")
            continue

        for dep_module in upstream:
            if dep_module in module_files and dep_module not in test_modules:
                dep_file = module_files[dep_module]
                reverse_map[dep_file].add(test_file)

        processed += 1
        if processed % 100 == 0:
            sys.stderr.write(f"  Processed {processed}/{len(test_modules)} test modules...\n")

    elapsed_grimp = time.monotonic() - start
    sys.stderr.write(f"grimp map covers {len(reverse_map)} source files (built in {elapsed_grimp:.1f}s)\n")

    # AST fallback for files grimp can't discover
    grimp_files = set(module_files.values())
    grimp_test_files = {module_files[m] for m in test_modules}
    ast_reverse, ast_tests, ast_sources = _build_ast_reverse_map(grimp_files, grimp_test_files)

    if ast_reverse:
        for source_file, tests in ast_reverse.items():
            reverse_map[source_file].update(tests)

    # all_known_source_files: every non-test file we analyzed (grimp + AST).
    # Files present here but absent from reverse_map have zero test dependents.
    all_known_source_files: set[str] = set()
    for module, file_path in module_files.items():
        if module not in test_modules:
            all_known_source_files.add(file_path)
    all_known_source_files.update(ast_sources)

    elapsed_total = time.monotonic() - start
    sys.stderr.write(
        f"AST fallback added {len(ast_tests)} test files, {len(ast_sources)} source files "
        f"({len(ast_reverse)} mapped) in {elapsed_total - elapsed_grimp:.1f}s\n"
    )
    sys.stderr.write(f"Total map covers {len(reverse_map)} source files\n")

    return (
        {k: sorted(v) for k, v in sorted(reverse_map.items())},
        len(test_modules) + len(ast_tests),
        all_known_source_files,
    )


def output_full(reason: str) -> None:
    sys.stdout.write(json.dumps({"mode": "full", "reason": reason}) + "\n")


def output_selective(
    affected_tests: list[str],
    suggested_shards: int,
    total_test_count: int,
    affected_duration_seconds: float = 0,
    total_duration_seconds: float = 0,
) -> None:
    sys.stdout.write(
        json.dumps(
            {
                "mode": "selective",
                "affected_tests": affected_tests,
                "affected_test_count": len(affected_tests),
                "total_test_count": total_test_count,
                "suggested_shards": max(1, suggested_shards),
                "affected_duration_seconds": round(affected_duration_seconds),
                "total_duration_seconds": round(total_duration_seconds),
            }
        )
        + "\n"
    )


def requires_full_run(changed_file: str) -> bool:
    for pattern in FULL_RUN_PATTERNS:
        if pattern in changed_file:
            return True
    return False


def parse_dorny_backend_patterns() -> list[str]:
    """Extract the backend filter patterns from ci-backend.yml."""
    ci_backend = REPO_ROOT / ".github" / "workflows" / "ci-backend.yml"
    lines = ci_backend.read_text().splitlines()

    patterns: list[str] = []
    in_backend = False
    for line in lines:
        stripped = line.strip()
        # Look for "backend:" at the start of a filter group
        if stripped == "backend:":
            in_backend = True
            continue
        if in_backend:
            if stripped.startswith("- "):
                # Strip "- " prefix and surrounding quotes
                pattern = stripped[2:].strip().strip("'\"")
                patterns.append(pattern)
            elif stripped and not stripped.startswith("#"):
                # Hit the next filter group (e.g. "legacy:")
                break
    return patterns


def pattern_is_covered(pattern: str) -> bool:
    """Check if a dorny pattern is covered by LOCAL_PACKAGES, FULL_RUN_PATTERNS, or GATE_ONLY_PATTERNS."""
    # Strip trailing glob characters (*, /, **)
    base = pattern.rstrip("/*")

    # Covered by import graph?
    for pkg in LOCAL_PACKAGES:
        if base == pkg or base.startswith(pkg + "/"):
            return True

    # Covered by full-run patterns? (substring match, same as requires_full_run)
    for full_pat in FULL_RUN_PATTERNS:
        if full_pat in base or base in full_pat:
            return True

    # Explicitly marked as gate-only?
    for gate_pat in GATE_ONLY_PATTERNS:
        if gate_pat in base or base in gate_pat:
            return True

    return False


def check_sync() -> None:
    """Verify all dorny backend patterns are covered by find_affected_tests.py."""
    patterns = parse_dorny_backend_patterns()
    if not patterns:
        sys.stderr.write("ERROR: could not parse any backend patterns from ci-backend.yml\n")
        sys.exit(1)

    uncovered: list[str] = []
    for pattern in patterns:
        if not pattern_is_covered(pattern):
            uncovered.append(pattern)

    if uncovered:
        sys.stderr.write("ERROR: dorny backend patterns not covered by find_affected_tests.py:\n")
        for p in uncovered:
            sys.stderr.write(f"  - {p}\n")
        sys.stderr.write(
            "\nAdd each pattern to FULL_RUN_PATTERNS (forces full test run) or\n"
            "GATE_ONLY_PATTERNS (dorny gate only, no test impact) in bin/find_affected_tests.py\n"
        )
        sys.exit(1)
    else:
        sys.stderr.write(f"OK: all {len(patterns)} dorny backend patterns are covered\n")


def load_durations() -> dict[str, float]:
    if not DURATIONS_PATH.exists():
        return {}
    try:
        return json.loads(DURATIONS_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def estimate_duration(test_files: list[str], durations: dict[str, float]) -> float:
    test_file_set = set(test_files)
    total = 0.0
    for test_id, dur in durations.items():
        # test_id is like "posthog/api/test/test_user.py::TestUser::test_create"
        file_part = test_id.split("::")[0]
        if file_part in test_file_set:
            total += dur
    return total


def estimate_total_duration(durations: dict[str, float]) -> float:
    return sum(durations.values())


def main():
    os.chdir(REPO_ROOT)

    parser = argparse.ArgumentParser(
        description="Find test files affected by changed source files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--changed-files",
        help="Space-separated list of changed file paths",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Read changed files from stdin (one per line)",
    )
    parser.add_argument(
        "--build-only",
        action="store_true",
        help="Just build and print map stats, don't look up affected tests",
    )
    parser.add_argument(
        "--check-sync",
        action="store_true",
        help="Verify all dorny backend patterns in ci-backend.yml are covered",
    )
    args = parser.parse_args()

    if args.check_sync:
        check_sync()
        return

    # Build-only mode: just print stats
    if args.build_only:
        reverse_map, _, _all_source = build_reverse_map()
        all_test_files: set[str] = set()
        for tests in reverse_map.values():
            all_test_files.update(tests)
        top_fanout = sorted(reverse_map.items(), key=lambda x: len(x[1]), reverse=True)[:10]
        sys.stderr.write(f"\nSource files mapped: {len(reverse_map)}\n")
        sys.stderr.write(f"Test files covered:  {len(all_test_files)}\n")
        sys.stderr.write("\nTop fan-out (source files affecting most tests):\n")
        for source, tests in top_fanout:
            sys.stderr.write(f"  {source}: {len(tests)} tests\n")
        return

    # Force full mode via env var
    if os.environ.get("FORCE_FULL_TESTS"):
        output_full("FORCE_FULL_TESTS env var set")
        return

    # Parse changed files
    if args.stdin:
        changed_files = [line.strip() for line in sys.stdin if line.strip()]
    elif args.changed_files:
        changed_files = args.changed_files.split()
    else:
        sys.stderr.write("Error: provide --changed-files, --stdin, or --build-only\n")
        sys.exit(1)

    # Filter to Python files only
    py_files = [f for f in changed_files if f.endswith(".py")]
    non_py_files = [f for f in changed_files if not f.endswith(".py")]

    sys.stderr.write(f"Changed files: {len(changed_files)} total, {len(py_files)} Python\n")

    if not py_files:
        # No Python files changed — no backend tests needed
        # (but non-Python changes like YAML/Docker might still need full run)
        for f in non_py_files:
            if requires_full_run(f):
                output_full(f"non-Python file requires full run: {f}")
                return
        output_selective([], 0, 0)
        return

    # Check for too many changes
    if len(py_files) > MAX_CHANGED_FILES:
        output_full(f"too many changed files ({len(py_files)} > {MAX_CHANGED_FILES})")
        return

    # Check for files that force full run
    for f in changed_files:
        if requires_full_run(f):
            output_full(f"changed file matches full-run pattern: {f}")
            return

    # Build the dependency map
    reverse_map, total_test_count, all_known_source_files = build_reverse_map()

    # Look up affected tests
    affected: set[str] = set()
    unmapped_files: list[str] = []
    no_dep_files: list[str] = []

    for changed_file in py_files:
        # Only files under LOCAL_PACKAGES can appear in the import graph.
        # Skip anything outside (bin/, tools/, scripts/, etc.)
        top_dir = changed_file.split("/")[0] if "/" in changed_file else ""
        if top_dir not in LOCAL_PACKAGES:
            continue

        normalized = os.path.normpath(changed_file)
        if normalized in reverse_map:
            affected.update(reverse_map[normalized])
        elif changed_file in reverse_map:
            affected.update(reverse_map[changed_file])
        else:
            # Check if the changed file is itself a test file
            basename = os.path.basename(changed_file)
            if basename.startswith("test_") or basename.startswith("eval_"):
                affected.add(changed_file)
            elif normalized in all_known_source_files or changed_file in all_known_source_files:
                # grimp/AST analyzed this file — no test depends on it.
                # Changing it cannot break any test through import deps.
                no_dep_files.append(changed_file)
            else:
                unmapped_files.append(changed_file)

    if no_dep_files:
        sys.stderr.write(
            f"Skipped {len(no_dep_files)} file(s) with no test dependencies: {', '.join(no_dep_files[:5])}\n"
        )

    if unmapped_files:
        output_full(f"unmapped files (not in dependency map): {', '.join(unmapped_files[:5])}")
        return

    affected_sorted = sorted(affected)
    sys.stderr.write(f"Affected test files: {len(affected_sorted)}\n")

    # Estimate duration and suggest shard count
    durations = load_durations()
    affected_duration = estimate_duration(affected_sorted, durations)
    total_duration = estimate_total_duration(durations)
    # Apply safety factor (durations underpredict by ~2x per turbo-discover.js)
    suggested_shards = max(1, int((affected_duration * 2) / TARGET_SHARD_SECONDS) + 1)

    sys.stderr.write(f"Estimated duration: {affected_duration:.0f}s, suggested shards: {suggested_shards}\n")

    output_selective(affected_sorted, suggested_shards, total_test_count, affected_duration, total_duration)


if __name__ == "__main__":
    main()
