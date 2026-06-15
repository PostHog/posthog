# ruff: noqa: T201, E402
"""Edge-case-corpus parser-parity diagnostic.

Runs the oracle and candidate parsers over a **local file** of candidate
queries instead of pulling them from production, then reports where they
disagree and (by default) shrinks each divergence to a minimal repro.

This is the "think really hard about edge cases" arm of the parity loop in
[`rust/hogql/parser/README.md`](../../../rust/hogql/parser/README.md): a
human — or a background agent told to brainstorm adversarial grammar
surface — writes candidate queries to a file, and this script grinds them
the same way `log_corpus_diagnostic.py` grinds production traffic. The
Metabase download, redaction, and AI-consent gating are all irrelevant
here (the input is locally authored), so this script is just
`load_query_file` → parity grind → shrink → failure dump.

## Input formats

Picked by extension (see `load_query_file`):

- `.jsonl` — one JSON value per line. A bare string is the query; an object
  uses the first present of `query` / `hogql` / `hog`. Best for an agent to
  emit, and unambiguous for multi-line queries.
- `.json` — a JSON array of the same items.
- `.sql` / `.hog` / `.txt` — block text. Split on `-- ===` rulers (so a
  `*.failures.sql` dump from another diagnostic round-trips straight back
  in) or, failing that, on blank lines.

## Usage

    # Brainstorm edge cases into a file, then grind + shrink them:
    PYTHONPATH=. python posthog/hogql/scripts/edge_corpus_diagnostic.py \\
        --input /tmp/edge_cases.jsonl

    # Hog programs instead of SELECT queries, no shrinking:
    PYTHONPATH=. python posthog/hogql/scripts/edge_corpus_diagnostic.py \\
        --input /tmp/edge_programs.hog --rule program --no-shrink-failures

Shrinking is ON by default here (minimal repros are the whole point of the
edge-case arm); pass `--no-shrink-failures` to skip it. Shrinking needs the
optional `hogql-parser-parity` dependency group
(`uv sync --group hogql-parser-parity`).
"""

from __future__ import annotations

import os
import sys
import argparse
import traceback
from pathlib import Path

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

from posthog.hogql.scripts._diagnostic_common import (
    _probe_backend,
    load_query_file,
    print_corpus_summary,
    repo_relative,
    run_corpus_parity,
    shrink_failures,
    write_failures,
)
from posthog.hogql.scripts._shrink import is_available as shrinkray_available

REPO_ROOT = Path(__file__).resolve().parents[3]

# Failure-dump extension per rule — `.hog` for programs, `.sql` otherwise.
_FAILURE_SUFFIX = {"expr": ".sql", "select": ".sql", "program": ".hog"}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Path to the edge-case query file (.jsonl / .json / .sql / .hog / .txt)",
    )
    p.add_argument(
        "--rule",
        choices=("expr", "select", "program"),
        default="select",
        help="Parser rule the queries should parse as (default: select)",
    )
    p.add_argument(
        "--oracle",
        default=os.environ.get("ORACLE_BACKEND", "cpp-json"),
        help="Source-of-truth backend (default: cpp-json)",
    )
    p.add_argument(
        "--candidate",
        default=os.environ.get("CANDIDATE_BACKEND", "rust-json"),
        help="Backend under test (default: rust-json; override for forks)",
    )
    p.add_argument(
        "--write-failures",
        metavar="PATH",
        default=None,
        help="Output file for failing queries (default: <input>.failures.<sql|hog> alongside the input)",
    )
    p.add_argument(
        "--shrink-failures",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Reduce each failing query to a minimal repro via shrinkray (default: on)",
    )
    p.add_argument("--verbose", action="store_true", help="Print one line per AST mismatch")
    args = p.parse_args()

    # Fail fast on a bad backend name.
    for label, backend in (("oracle", args.oracle), ("candidate", args.candidate)):
        err = _probe_backend(args.rule, backend)
        if err is not None:
            print(f"ERROR: {label} backend {backend!r} unavailable: {err}")
            return 1
    if args.oracle == args.candidate:
        print(
            f"WARNING: --oracle and --candidate are both {args.oracle!r} — "
            f"this is not a parity check; every query will trivially 'pass'."
        )
    if args.shrink_failures and not shrinkray_available():
        print(
            "ERROR: --shrink-failures needs shrinkray, which isn't installed.\n"
            "  install it with `uv sync --group hogql-parser-parity`, or pass --no-shrink-failures"
        )
        return 1

    print(f"=== Edge-case corpus diagnostic: rule={args.rule} oracle={args.oracle} candidate={args.candidate} ===")
    print()

    # 1. Load.
    try:
        rows = load_query_file(args.input)
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        return 1
    if not rows:
        print(f"ERROR: no queries found in {repo_relative(args.input, REPO_ROOT)}")
        return 1
    print(f"Loaded {len(rows)} queries from {repo_relative(args.input, REPO_ROOT)}")

    # 2. Parity grind.
    print()
    print("Running parity check (oracle then candidate per query)…")
    print()
    result = run_corpus_parity(
        rows,
        rule=args.rule,
        oracle=args.oracle,
        candidate=args.candidate,
        verbose=args.verbose,
        noun="query",
    )
    print_corpus_summary(result, oracle=args.oracle, candidate=args.candidate)

    # 3. Shrink + failure dump.
    failures = result.failures
    if failures and args.shrink_failures:
        print()
        print(f"Shrinking {len(failures)} failing queries via shrinkray…")
        failures = shrink_failures(failures, rule=args.rule, oracle=args.oracle, candidate=args.candidate)
    if failures:
        suffix = ".failures" + _FAILURE_SUFFIX[args.rule]
        out_path = Path(args.write_failures) if args.write_failures else args.input.with_suffix(suffix)
        write_failures(out_path, failures, REPO_ROOT, title="edge_corpus_failures")
        print()
        print(f"Wrote {len(failures)} failing queries to {repo_relative(out_path, REPO_ROOT)}")

    return 130 if result.interrupted else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
