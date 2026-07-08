# ruff: noqa: T201, E402
"""Shrink one HogQL query, read from stdin, to a minimal parser-parity repro.

Reads a query on stdin, checks whether the oracle and candidate backends
disagree on it, and — if they do — writes the smallest variant that still
triggers the same divergence to **stdout** (via shrinkray). All diagnostic
chatter goes to stderr, so stdout is exactly the shrunk query and nothing
else, ready to capture in `$(...)` or pipe onward.

This is the single-query reducer for the parity loop in
[`rust/hogql/parser/README.md`](../../../rust/hogql/parser/README.md): a
human — or a background agent told to brainstorm adversarial grammar
surface — pipes in a query that diverges (or that they think might) and gets
the minimal repro back to paste into a regression test. It doubles as a
divergence check: a query the backends agree on exits non-zero with the
reason on stderr.

Exit codes: `0` — a divergence was found and its minimal form is on stdout;
`1` — no divergence to shrink, or a setup error (reason on stderr).

## Usage

    echo '<query>' | PYTHONPATH=. python posthog/hogql/scripts/shrink_query.py
    pbpaste | PYTHONPATH=. python posthog/hogql/scripts/shrink_query.py --rule program

Needs the optional `hogql-parser-parity` dependency group
(`uv sync --group hogql-parser-parity`).
"""

from __future__ import annotations

import os
import sys
import argparse

import django

# Keep stdout pristine (only the shrunk query, for `$(...)` capture): django setup/settings print chatter there, so point stdout at stderr before django.setup() — early enough that logging config binds to stderr too — and write the result to the saved real stdout.
_REAL_STDOUT = sys.stdout
sys.stdout = sys.stderr

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

from posthog.hogql.scripts._diagnostic_common import _probe_backend, _safe_parse, _shape_for, shrink_to_shape


def _explain_no_divergence(query: str, rule: str, oracle: str, candidate: str) -> str:
    """Human-readable reason `_shape_for` returned None — the input isn't a
    shrinkable divergence. Re-parses both backends to classify which of the
    no-divergence cases this is."""
    o_status, _, o_detail = _safe_parse(query, rule, oracle)
    c_status, _, c_detail = _safe_parse(query, rule, candidate)
    if o_status == "crash":
        return f"no divergence to shrink: oracle {oracle!r} crashed ({o_detail}) — nothing to compare against"
    if c_status == "crash":
        return (
            f"no divergence to shrink: candidate {candidate!r} crashed ({c_detail}) — "
            f"a crash isn't a stable shape to reduce toward; reproduce it directly"
        )
    if o_status == "reject" and c_status == "reject":
        return "no divergence to shrink: both backends reject this query (they agree)"
    return "no divergence to shrink: oracle and candidate produce identical ASTs (they agree)"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--rule",
        choices=("expr", "select", "program"),
        default="select",
        help="Parser rule the query should parse as (default: select)",
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
    args = p.parse_args()

    for label, backend in (("oracle", args.oracle), ("candidate", args.candidate)):
        err = _probe_backend(args.rule, backend)
        if err is not None:
            print(f"ERROR: {label} backend {backend!r} unavailable: {err}", file=sys.stderr)
            return 1

    # Read raw bytes and decode UTF-8 explicitly — the round trip must be
    # byte-exact and locale-independent (shrinkray works on UTF-8 bytes too).
    try:
        query = sys.stdin.buffer.read().decode("utf-8")
    except UnicodeDecodeError as e:
        print(f"ERROR: stdin is not valid UTF-8: {e}", file=sys.stderr)
        return 1
    if not query.strip():
        print("ERROR: no query on stdin", file=sys.stderr)
        return 1

    shape = _shape_for(query, args.rule, args.oracle, args.candidate)
    if shape is None:
        print(_explain_no_divergence(query, args.rule, args.oracle, args.candidate), file=sys.stderr)
        return 1

    shrunk = shrink_to_shape(query, args.rule, args.oracle, args.candidate, shape)
    print(f"shrunk {len(query)} -> {len(shrunk)} chars ({shape.kind})", file=sys.stderr)
    # Saved real stdout carries *only* the minimal query — exact bytes, no trailing newline added (a load-bearing one survives in `shrunk`).
    _REAL_STDOUT.write(shrunk)
    _REAL_STDOUT.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
