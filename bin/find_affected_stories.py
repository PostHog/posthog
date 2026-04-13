#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""
Find storybook stories affected by a set of changed files.

This is the storybook equivalent of bin/find_affected_tests.py. It mirrors the
same architecture so that .github/workflows/ci-storybook-selection-shadow.yml
can emit SHADOW_METRICS in a format comparable to the backend shadow.

PROTOTYPE SCOPE (step 1 / measurement only):
  - Predicts which *.stories.{ts,tsx} files could have rendered differently
    based on changed files in a PR.
  - Does NOT run storybook, does NOT gate CI, does NOT change what
    ci-storybook.yml actually runs. Pure telemetry.
  - Uses a conservative heuristic predictor (see below). A future iteration
    can replace the predictor with a webpack-stats-based module graph (the
    equivalent of grimp's import graph for Python).

PREDICTION HEURISTIC (deliberately simple for v1):
  1. If any changed file matches FULL_RUN_PATTERNS (storybook config, global
     styles, test-runner, schema, etc.) → mode=full with a reason.
  2. If no frontend-relevant files changed at all → mode=selective with an
     empty affected list (no stories could have rendered differently).
  3. Otherwise we scan every story file once for string references to each
     changed file's basename (without extension). A story is considered
     affected if it imports anything whose final path segment matches a
     changed file. This is a 1-hop, conservative approximation:
       - Over-predicts when names collide (e.g. two `utils.ts` in different
         dirs; we include both).
       - Under-predicts transitive changes (A imports B imports C; if C
         changes and no story directly imports C, we miss it).
     Neither is acceptable long-term — the goal is to observe the
     prediction vs. the ground truth (stories whose snapshots actually
     changed) and calibrate before promoting to enforce.

Outputs JSON to stdout:
  - mode: "selective" or "full"
  - affected_stories: list of story file paths (selective only)
  - affected_story_count / total_story_count
  - suggested_shards: recommended matrix size if we were selecting
  - affected_duration_seconds / total_duration_seconds: rough estimates

Usage:
    # From stdin (one changed file per line)
    git diff --name-only origin/master...HEAD | uv run bin/find_affected_stories.py --stdin

    # From CLI
    uv run bin/find_affected_stories.py --changed-files "frontend/src/lib/Foo.tsx"

    # Verify dorny-frontend patterns in ci-storybook.yml are accounted for
    uv run bin/find_affected_stories.py --check-sync

    # Force full run
    FORCE_FULL_STORIES=1 uv run bin/find_affected_stories.py --stdin
"""

from __future__ import annotations

import os
import re
import sys
import json
import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.resolve()

# Directories under which stories live. Matches the `stories` globs in
# common/storybook/.storybook/main.ts.
STORY_ROOTS = (
    "frontend/src",
    "products",
    "common/mosaic/storybook",
)
STORY_FILE_RE = re.compile(r"\.stories\.(ts|tsx|mdx|js|jsx)$")

# Directories we scan when tracing source → story via filename references.
# Kept tight to avoid huge regex scans; expand if we find missed paths.
SOURCE_SCAN_ROOTS = (
    "frontend/src",
    "products",
    "common/mosaic",
    "common/storybook",
    "ee/frontend",
)

# Top-level directories that never affect stories (backend, infra, etc.).
# If every changed file sits under one of these, mode=selective with empty
# affected list.
NON_FRONTEND_PREFIXES = (
    "posthog/",
    "ee/posthog/",
    "rust/",
    "nodejs/",
    "bin/",
    "docker/",
    "docs/",
    "funnel-udf/",
    "services/",
    "plugin-server/",
)

# Files whose change forces a full storybook run: global styles, storybook
# config, test-runner, tailwind, schema, manifests. Substring-matched against
# each changed path, same convention as FULL_RUN_PATTERNS in find_affected_tests.py.
# Keep in sync with the dorny frontend filter in .github/workflows/ci-storybook.yml
# — `--check-sync` verifies coverage.
FULL_RUN_PATTERNS = (
    # Storybook configuration & harness
    ".storybook/",
    "common/storybook/.storybook/",
    "common/storybook/package.json",
    "common/storybook/tailwind.config.js",
    # Global styling — Tailwind, theme tokens, base SCSS all affect every story
    "common/tailwind/",
    "frontend/src/styles/",
    "common/mosaic/storybook/theme.css",
    "tailwind.config.js",
    "tailwind.config.ts",
    # Shared test harness & mocks
    "frontend/src/mocks/",
    "frontend/src/setup.jest.ts",
    "common/storybook/tsconfig.json",
    "frontend/tsconfig.json",
    # Generated schema / product manifests — drive many stories' code paths
    "frontend/src/queries/schema/",
    "frontend/src/queries/schema.json",
    "products/**/manifest.tsx",  # handled via substring below for simplicity
    "manifest.tsx",
    "frontend/src/products.tsx",
    "frontend/src/products.json",
    # Root package / lockfile — dependency change can alter any rendering
    "package.json",
    "pnpm-lock.yaml",
    ".nvmrc",
    # CI configuration touches matrix composition
    ".github/workflows/ci-storybook.yml",
    ".github/workflows/ci-storybook-selection-shadow.yml",
    "playwright.config.ts",
    # esbuild / common build config
    "common/esbuilder/",
)

# Dorny-frontend patterns from ci-storybook.yml that don't require a full run.
# None today — every current dorny entry is either covered by FULL_RUN_PATTERNS
# or by SOURCE_SCAN_ROOTS via import matching. Listed for symmetry with
# bin/find_affected_tests.py; update if the dorny filter gains a pattern that
# deliberately doesn't imply a storybook rebuild.
GATE_ONLY_PATTERNS: tuple[str, ...] = ()

# Max changed files before we give up and declare full run.
MAX_CHANGED_FILES = 100

# Matches backend: 10 minutes target per shard.
TARGET_SHARD_SECONDS = 10 * 60

# Rough per-story render cost in seconds. Based on 368 stories × ~2 themes ×
# ~3 s average / 16 shards ≈ 3–4 min per shard. Refined once we ship
# per-story duration telemetry.
AVG_STORY_DURATION_SECONDS = 6.0

# Current matrix cost assumptions for the job summary. Informational only —
# adjust if ci-storybook.yml changes.
CURRENT_CHROMIUM_SHARDS = 16
CURRENT_WEBKIT_SHARDS = 4
SHARD_OVERHEAD_MINUTES = 3


# ---------------------------------------------------------------------------
# Story discovery
# ---------------------------------------------------------------------------


def discover_story_files() -> list[str]:
    """Walk STORY_ROOTS and return all story file paths (repo-relative)."""
    stories: list[str] = []
    for root in STORY_ROOTS:
        root_path = REPO_ROOT / root
        if not root_path.exists():
            continue
        for path in root_path.rglob("*"):
            if not path.is_file():
                continue
            if STORY_FILE_RE.search(path.name):
                stories.append(str(path.relative_to(REPO_ROOT)))
    return sorted(stories)


# ---------------------------------------------------------------------------
# Full-run classification
# ---------------------------------------------------------------------------


def requires_full_run(changed_file: str) -> str | None:
    """Return a reason string if `changed_file` forces a full run, else None."""
    for pattern in FULL_RUN_PATTERNS:
        if pattern in changed_file:
            return f"changed file matches full-run pattern '{pattern}': {changed_file}"
    return None


def is_non_frontend(changed_file: str) -> bool:
    return any(changed_file.startswith(prefix) for prefix in NON_FRONTEND_PREFIXES)


# ---------------------------------------------------------------------------
# Heuristic 1-hop import detector
# ---------------------------------------------------------------------------

# We scan story text for the bare filename (no extension) of each changed
# source file. This catches the common patterns:
#   import Foo from './Foo'
#   import { bar } from 'scenes/foo/Foo'
#   import '~/lib/Foo'
# without needing a TS resolver.
#
# We ignore very short stems (<= 3 chars) to avoid flooding matches for
# names like `a.ts` or `id.ts`. Those fall through to FULL_RUN_PATTERNS or
# the MAX_CHANGED_FILES bailout.

MIN_STEM_LENGTH = 4


def _stem_of(path: str) -> str | None:
    name = os.path.basename(path)
    stem = re.sub(r"\.(ts|tsx|js|jsx|mjs|cjs|mdx)$", "", name)
    if len(stem) < MIN_STEM_LENGTH:
        return None
    # Avoid too-generic stems
    if stem in {"index", "types", "utils", "helpers", "constants"}:
        return None
    return stem


def find_affected_stories(changed_source_files: list[str], all_stories: list[str]) -> tuple[list[str], list[str]]:
    """
    Return (affected_stories, stems_not_found).

    A story is affected if its file text references any changed source file's
    stem (e.g. "FooBar"). Reference is a word-boundary substring match, which
    tolerates relative, absolute, and alias paths without TS resolver.
    """
    stems: list[str] = []
    stems_not_found: list[str] = []
    stem_to_source: dict[str, str] = {}
    for f in changed_source_files:
        stem = _stem_of(f)
        if stem is None:
            continue
        if stem not in stem_to_source:
            stems.append(stem)
            stem_to_source[stem] = f

    if not stems:
        return [], stems_not_found

    # Build a single combined regex to scan each story once.
    # \b ensures we don't match "Foo" inside "Foobar".
    combined = re.compile(r"\b(" + "|".join(re.escape(s) for s in stems) + r")\b")
    found_stems: set[str] = set()
    affected: set[str] = set()

    for story in all_stories:
        try:
            text = (REPO_ROOT / story).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        matches = combined.findall(text)
        if not matches:
            continue
        affected.add(story)
        found_stems.update(matches)

    for stem in stems:
        if stem not in found_stems:
            stems_not_found.append(stem_to_source[stem])

    return sorted(affected), stems_not_found


# ---------------------------------------------------------------------------
# dorny sync check
# ---------------------------------------------------------------------------


def parse_dorny_frontend_patterns() -> list[str]:
    """Extract the frontend filter patterns from ci-storybook.yml."""
    ci_storybook = REPO_ROOT / ".github" / "workflows" / "ci-storybook.yml"
    if not ci_storybook.exists():
        return []
    lines = ci_storybook.read_text().splitlines()

    patterns: list[str] = []
    in_frontend = False
    pattern_indent: int | None = None
    for line in lines:
        stripped = line.strip()
        if stripped == "frontend:":
            in_frontend = True
            continue
        if not in_frontend:
            continue
        if not stripped or stripped.startswith("#"):
            continue
        # Measure leading whitespace to detect when we've left the filter block.
        indent = len(line) - len(line.lstrip())
        if stripped.startswith("- "):
            if pattern_indent is None:
                pattern_indent = indent
            elif indent < pattern_indent:
                # Dedented back to a parent context — block has ended.
                break
            pattern = stripped[2:].strip().strip("'\"")
            patterns.append(pattern)
        else:
            # Non-list line inside the block → another key at a shallower indent.
            break
    return patterns


def pattern_is_covered(pattern: str) -> bool:
    base = pattern.rstrip("/*").rstrip("{}")
    # Covered by story scan roots?
    for root in STORY_ROOTS:
        if base == root or base.startswith(root + "/"):
            return True
    for root in SOURCE_SCAN_ROOTS:
        if base == root or base.startswith(root + "/"):
            return True
    # Covered by full-run patterns?
    for full in FULL_RUN_PATTERNS:
        if full in base or base in full:
            return True
    for gate in GATE_ONLY_PATTERNS:
        if gate in base or base in gate:
            return True
    # Glob patterns like 'common/{esbuilder,mosaic,storybook,tailwind}/**'
    if "{" in pattern and "}" in pattern:
        brace = re.search(r"\{([^}]+)\}", pattern)
        if brace:
            options = brace.group(1).split(",")
            prefix = pattern[: brace.start()]
            suffix = pattern[brace.end() :].rstrip("/*")
            for opt in options:
                candidate = f"{prefix}{opt}{suffix}".rstrip("/*")
                if pattern_is_covered(candidate):
                    continue
                return False
            return True
    return False


def check_sync() -> None:
    patterns = parse_dorny_frontend_patterns()
    if not patterns:
        sys.stderr.write("ERROR: could not parse any frontend patterns from ci-storybook.yml\n")
        sys.exit(1)
    uncovered = [p for p in patterns if not pattern_is_covered(p)]
    if uncovered:
        sys.stderr.write("ERROR: dorny frontend patterns not covered by find_affected_stories.py:\n")
        for p in uncovered:
            sys.stderr.write(f"  - {p}\n")
        sys.stderr.write(
            "\nAdd each pattern to FULL_RUN_PATTERNS (forces full storybook run),\n"
            "GATE_ONLY_PATTERNS (gate only, no story impact), or extend\n"
            "STORY_ROOTS / SOURCE_SCAN_ROOTS in bin/find_affected_stories.py.\n"
        )
        sys.exit(1)
    sys.stderr.write(f"OK: all {len(patterns)} dorny frontend patterns are covered\n")


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def output_full(reason: str, total_stories: int) -> None:
    sys.stdout.write(json.dumps({"mode": "full", "reason": reason, "total_story_count": total_stories}) + "\n")


def output_selective(
    affected: list[str],
    total_stories: int,
) -> None:
    affected_duration = len(affected) * AVG_STORY_DURATION_SECONDS
    total_duration = total_stories * AVG_STORY_DURATION_SECONDS
    # 2x safety factor — match backend's `DURATION_SAFETY_FACTOR`
    suggested_shards = max(1, int((affected_duration * 2) / TARGET_SHARD_SECONDS) + 1)
    sys.stdout.write(
        json.dumps(
            {
                "mode": "selective",
                "affected_stories": affected,
                "affected_story_count": len(affected),
                "total_story_count": total_stories,
                "suggested_shards": suggested_shards,
                "affected_duration_seconds": round(affected_duration),
                "total_duration_seconds": round(total_duration),
            }
        )
        + "\n"
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    os.chdir(REPO_ROOT)

    parser = argparse.ArgumentParser(
        description="Find story files affected by changed source files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--changed-files", help="Space-separated list of changed paths")
    parser.add_argument("--stdin", action="store_true", help="Read one path per line from stdin")
    parser.add_argument("--check-sync", action="store_true", help="Verify dorny frontend patterns are covered")
    parser.add_argument("--build-only", action="store_true", help="Print story discovery stats and exit")
    args = parser.parse_args()

    if args.check_sync:
        check_sync()
        return

    stories = discover_story_files()
    sys.stderr.write(f"Discovered {len(stories)} story files\n")

    if args.build_only:
        sys.stderr.write(f"Story roots scanned: {', '.join(STORY_ROOTS)}\n")
        return

    if args.stdin:
        changed = [line.strip() for line in sys.stdin if line.strip()]
    elif args.changed_files:
        changed = args.changed_files.split()
    else:
        sys.stderr.write("Error: provide --changed-files, --stdin, --check-sync, or --build-only\n")
        sys.exit(1)

    sys.stderr.write(f"Changed files: {len(changed)}\n")

    if os.environ.get("FORCE_FULL_STORIES"):
        output_full("FORCE_FULL_STORIES env var set", len(stories))
        return

    if len(changed) > MAX_CHANGED_FILES:
        output_full(
            f"too many changed files ({len(changed)} > {MAX_CHANGED_FILES})",
            len(stories),
        )
        return

    # Classify changes
    frontend_changes: list[str] = []
    for f in changed:
        reason = requires_full_run(f)
        if reason is not None:
            output_full(reason, len(stories))
            return
        if is_non_frontend(f):
            continue
        frontend_changes.append(f)

    if not frontend_changes:
        sys.stderr.write("No frontend-relevant files changed — affected=[]\n")
        output_selective([], len(stories))
        return

    # Any story files changed directly? Those are definitely affected.
    directly_changed_stories = [f for f in frontend_changes if STORY_FILE_RE.search(f)]
    source_changes = [f for f in frontend_changes if not STORY_FILE_RE.search(f)]

    affected_from_source, not_found = find_affected_stories(source_changes, stories)
    affected = sorted(set(directly_changed_stories) | set(affected_from_source))

    if not_found:
        sys.stderr.write(
            f"Heuristic could not trace {len(not_found)} source file(s) to a story — "
            f"these may still transitively affect stories: {', '.join(not_found[:5])}\n"
        )

    sys.stderr.write(
        f"Affected stories: {len(affected)} "
        f"(direct={len(directly_changed_stories)}, via-source={len(affected_from_source)})\n"
    )
    output_selective(affected, len(stories))


if __name__ == "__main__":
    main()
