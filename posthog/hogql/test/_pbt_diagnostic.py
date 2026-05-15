"""Diagnostic PBT runner: oracle backend vs candidate backend.

Reuses the strategies from `test_parser_grammar_pbt.py` (the
auto-generated grammar PBT introduced in PR #58627) but runs as an
ad-hoc CLI rather than a pytest collection. Backend-agnostic:
defaults to `cpp-json` vs `python` (the two backends shipped in
master); point `--candidate` at any other backend in a feature
branch that adds one.

Distinct from the pytest PBT in five ways:

1. **AST node-type pair categorization.** Each ast_mismatch is
   bucketed by `(oracle.root_node, candidate.root_node)` so the
   dominant divergence classes surface immediately — no manual
   eyeballing of 200-line AST dumps.
2. **Diff-only AST output.** When printing a sample mismatch, walk
   both ASTs together and print only the path from root to the first
   differing node.
3. **Auto-shrinker (`--shrink-failures`).** For each ast_mismatch
   and reject, run a delete-one-token reducer that keeps the smallest
   variant which still triggers the same divergence shape. Drops
   typical PBT failures from 200+ chars to <50.
4. **Optional JSONL persistence (`--write-divergences PATH`).** Drop
   one JSON line per failing example for cross-run analysis or
   regression-corpus extraction.
5. **Reject categorization.** Group `candidate_reject` queries by the
   error message + leading-token signature so recurring shapes
   surface even though there's no AST to diff against.

The leading underscore in this file's name keeps pytest's collector
from picking it up.

Typical usage:

    # Default: cpp-json vs python (works in master out of the box)
    PYTHONPATH=. python posthog/hogql/test/_pbt_diagnostic.py --n 5000

    # With auto-shrinking on every failure
    PYTHONPATH=. python posthog/hogql/test/_pbt_diagnostic.py \\
        --n 5000 --shrink-failures

    # Persist for later analysis / corpus extraction
    PYTHONPATH=. python posthog/hogql/test/_pbt_diagnostic.py \\
        --write-divergences /tmp/divergences.jsonl --shrink-failures
"""

# ruff: noqa: T201 (this is a CLI script — print is the output channel)
# ruff: noqa: E402 (django.setup() must run between import django and the
#                   project-app imports below)

from __future__ import annotations

import os
import re
import sys
import json
import argparse
import traceback
import dataclasses
from collections import Counter
from typing import Any

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

from hypothesis import given, settings

from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.test._generated_grammar_strategies import expr_strategy, select_strategy
from posthog.hogql.test.test_parser_grammar_pbt import _PBT_SETTINGS, _apply_jiggle, _try_parse

# ---------------------------------------------------------------------------
# AST diff path
# ---------------------------------------------------------------------------


def _node_type(node: Any) -> str:
    """Top-level AST node type label, e.g. `Call` / `ExprCall` / `Not`."""
    return type(node).__name__ if node is not None else "<None>"


def _node_fields(node: Any) -> list[tuple[str, Any]]:
    """Return (field_name, value) pairs for an AST node in declaration
    order. HogQL AST nodes are dataclasses (with `__slots__`), so
    `dataclasses.fields()` is the canonical accessor. Non-dataclass
    leaves return `[]` and fall through to the value-terminal branch
    in `_diff_path`."""
    if not dataclasses.is_dataclass(node):
        return []
    return [(f.name, getattr(node, f.name, None)) for f in dataclasses.fields(node)]


def _diff_path(oracle: Any, candidate: Any, path: list | None = None, depth: int = 0) -> list:
    """Walk both ASTs together; return the sequence of `.field` / `[i]`
    breadcrumbs from root to the first divergence, terminating with a
    3-tuple `(label, oracle_repr, candidate_repr)` showing what
    actually differs.

    Recursion is depth-bounded so pathological deep trees don't blow
    the stack."""
    path = path or []
    if depth > 64:
        return [*path, ("<depth-limit>", repr(oracle)[:120], repr(candidate)[:120])]
    if oracle == candidate:
        return path
    o_t = _node_type(oracle)
    c_t = _node_type(candidate)
    if o_t != c_t:
        return [*path, ("<type>", o_t, c_t)]

    if isinstance(oracle, list) and isinstance(candidate, list):
        if len(oracle) != len(candidate):
            return [*path, ("<len>", str(len(oracle)), str(len(candidate)))]
        for i, (a, b) in enumerate(zip(oracle, candidate)):
            if a != b:
                return _diff_path(a, b, [*path, f"[{i}]"], depth + 1)
        return path
    if isinstance(oracle, dict) and isinstance(candidate, dict):
        if set(oracle) != set(candidate):
            return [*path, ("<keys>", str(sorted(oracle)), str(sorted(candidate)))]
        for k in oracle:
            if oracle[k] != candidate[k]:
                return _diff_path(oracle[k], candidate[k], [*path, f"[{k!r}]"], depth + 1)
        return path
    o_fields = _node_fields(oracle)
    c_fields = dict(_node_fields(candidate))
    if o_fields:
        for name, ov in o_fields:
            cv = c_fields.get(name)
            if ov == cv:
                continue
            return _diff_path(ov, cv, [*path, f".{name}"], depth + 1)
        return [*path, ("<unequal-but-fields-match>", repr(oracle)[:120], repr(candidate)[:120])]
    return [*path, ("<value>", repr(oracle), repr(candidate))]


def _format_diff_path(steps: list) -> str:
    """Format a diff path as breadcrumbs ending with the differing
    oracle/candidate values."""
    if not steps:
        return "  (no diff)"
    breadcrumbs: list[str] = []
    terminal: tuple[str, str, str] | None = None
    for step in steps:
        if isinstance(step, tuple):
            terminal = step
        else:
            breadcrumbs.append(step)
    label = "root" + "".join(breadcrumbs)
    if terminal is None:
        return f"  {label}: (no terminal value)"
    field, o_repr, c_repr = terminal
    return f"  {label}{field}\n    oracle:    {o_repr[:200]}\n    candidate: {c_repr[:200]}"


# ---------------------------------------------------------------------------
# Divergence shape (used as a stable bucket key for shrinking)
# ---------------------------------------------------------------------------
#
# Two divergences are "the same shape" if they reach the same terminal
# diff at the same root-type pair, OR they're the same kind of reject
# (matching error message). The shrinker keeps reducing the query as
# long as the shape stays the same.


@dataclasses.dataclass(frozen=True)
class DivergenceShape:
    """Structural-only divergence descriptor — designed so two examples
    of the same divergence (with different leaf values) compare equal.

    For ast_mismatch:
      - `kind` = "ast_mismatch"
      - `root_pair` = (oracle_root_type, candidate_root_type)
      - `terminal_kind` = the kind tag of the final diff step
        (`<type>` / `<value>` / `<keys>` / `<len>` /
        `<unequal-but-fields-match>` / `<depth-limit>`).
      - `terminal_types` = for `<type>` terminals only, the
        (oracle_type, candidate_type) pair that diverged. None for
        all other terminal kinds — those are inherently structural.

    For candidate_reject:
      - `kind` = "candidate_reject"
      - `reject_signature` = the normalised error message
    """

    kind: str
    root_pair: tuple[str, str] | None = None
    terminal_kind: str | None = None
    terminal_types: tuple[str, str] | None = None
    reject_signature: str | None = None


def _ast_mismatch_shape(root_pair: tuple[str, str], steps: list) -> DivergenceShape:
    """Build a structural DivergenceShape for an ast_mismatch given the
    root-type pair and the diff-path output. Accepts both tuple-form
    steps (in-memory) and list-form (after JSON round-trip). Leaf
    VALUES of `<value>`, `<keys>`, `<len>` are intentionally dropped —
    two divergences are "the same shape" if they reach the same kind
    of leaf at the same root, regardless of which specific value
    differed."""
    terminal: tuple[str, str, str] | None = None
    for s in reversed(steps):
        if isinstance(s, tuple) and len(s) == 3:
            terminal = s
            break
        if isinstance(s, list) and len(s) == 3 and all(isinstance(x, str) for x in s):
            terminal = (s[0], s[1], s[2])
            break
    if terminal is None:
        return DivergenceShape(kind="ast_mismatch", root_pair=root_pair)
    kind_tag = terminal[0]
    types = (terminal[1], terminal[2]) if kind_tag == "<type>" else None
    return DivergenceShape(
        kind="ast_mismatch",
        root_pair=root_pair,
        terminal_kind=kind_tag,
        terminal_types=types,
    )


def _reject_error(query: str, rule: str, backend: str) -> str:
    """Capture the candidate's reject error message, normalised to
    drop the position-dependent `got <token>` payload so two rejects
    on the same root cause group together. Only called for queries
    `_try_parse` already returned `False` for, so `BaseHogQLError`
    is the only exception type we expect — anything else would have
    already aborted the run upstream."""
    parser_fn = parse_expr if rule == "expr" else parse_select
    try:
        parser_fn(query, backend=backend)  # type: ignore[arg-type]
    except BaseHogQLError as e:
        return _normalize_error(str(e))
    return "(unexpected: parse succeeded)"


_GOT_RE = re.compile(r"got\s+\S+", re.IGNORECASE)


def _normalize_error(msg: str) -> str:
    """Strip position-dependent suffixes so similar rejects bucket
    together. e.g. `expected ), got Keyword(Order)` and `expected ),
    got Number` collapse to `expected ), got <X>`."""
    return _GOT_RE.sub("got <X>", msg)[:120]


def _shape_for(
    query: str,
    rule: str,
    oracle_backend: str,
    candidate_backend: str,
) -> DivergenceShape | None:
    """Determine the divergence shape of `query`, or None if there's
    no divergence between oracle and candidate."""
    o_ok, o_ast = _try_parse(query, rule, oracle_backend)
    if not o_ok:
        return None  # oracle reject — not a divergence we care about
    c_ok, c_ast = _try_parse(query, rule, candidate_backend)
    if not c_ok:
        return DivergenceShape(
            kind="candidate_reject",
            reject_signature=_reject_error(query, rule, candidate_backend),
        )
    if o_ast == c_ast:
        return None
    return _ast_mismatch_shape((_node_type(o_ast), _node_type(c_ast)), _diff_path(o_ast, c_ast))


# ---------------------------------------------------------------------------
# Auto-shrinker
# ---------------------------------------------------------------------------
#
# Hypothesis has its own shrinker but we're running queries that already
# escaped from a Hypothesis trial — by the time the diagnostic sees them,
# Hypothesis has moved on. We re-run our own delete-one-token reducer so
# each printed failure is a small repro the human can paste into a unit
# test.


_TOKEN_RE = re.compile(r"\s+|[^\s]+")


def _tokenize_for_shrink(query: str) -> list[str]:
    """Split into shrinker units. We use whitespace-or-non-whitespace
    runs so paren matching is preserved (a token like `(` or `)` is a
    single shrinker unit). The original whitespace is retained so we
    can re-join faithfully."""
    return [m.group(0) for m in _TOKEN_RE.finditer(query)]


def _shrink_query(
    query: str,
    rule: str,
    oracle_backend: str,
    candidate_backend: str,
    target_shape: DivergenceShape,
    max_passes: int = 5,
) -> str:
    """Greedy delete-one-token shrinker. Each pass walks every token
    and drops it (and its trailing whitespace) if the resulting query
    still triggers the same divergence shape. Stops when a pass
    removes nothing or after `max_passes`. Linear in
    tokens × passes — fine for ~50-300-token PBT queries."""
    current = query
    for _ in range(max_passes):
        tokens = _tokenize_for_shrink(current)
        # Try delete each non-whitespace token (and any trailing
        # whitespace token) in turn.
        improved = False
        i = 0
        while i < len(tokens):
            if tokens[i].isspace():
                i += 1
                continue
            # Build a candidate with tokens[i] removed (plus any
            # immediately-following whitespace token).
            drop_to = i + 1
            if drop_to < len(tokens) and tokens[drop_to].isspace():
                drop_to += 1
            candidate = "".join(tokens[:i] + tokens[drop_to:])
            if not candidate.strip():
                i += 1
                continue
            shape = _shape_for(candidate, rule, oracle_backend, candidate_backend)
            if shape == target_shape:
                current = candidate
                tokens = _tokenize_for_shrink(current)
                improved = True
                # Don't advance i — the next token slid into this slot.
                continue
            i += 1
        if not improved:
            break
    return current


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _print_failure_sample(
    query: str,
    rule: str,
    oracle: str,
    candidate: str,
    target_shape: DivergenceShape,
    *,
    shrink: bool,
    diff_steps: list | None = None,
) -> None:
    """Print one sample failure for either ast_mismatch (with diff path)
    or candidate_reject (no diff path). If `shrink` is set, reduce the
    query and print the shrunk form with a length hint. For
    ast_mismatch samples, pass `diff_steps` so the diff path renders
    against the original — or, when shrunk, against a freshly-parsed
    pair from the reduced query for fidelity."""
    shrunk = _shrink_query(query, rule, oracle, candidate, target_shape) if shrink else query
    if shrink and shrunk != query:
        print(f"  query (shrunk {len(query)} -> {len(shrunk)}): {shrunk!r}")
        if diff_steps is not None:
            _, o_s = _try_parse(shrunk, rule, oracle)
            _, c_s = _try_parse(shrunk, rule, candidate)
            print(_format_diff_path(_diff_path(o_s, c_s)))
    else:
        print(f"  query: {query!r}")
        if diff_steps is not None:
            print(_format_diff_path(diff_steps))


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--n", type=int, default=int(os.environ.get("N", "500")))
    parser.add_argument("--rule", choices=("expr", "select"), default="expr")
    parser.add_argument("--jiggle", action="store_true")
    parser.add_argument(
        "--oracle",
        default=os.environ.get("ORACLE_BACKEND", "cpp-json"),
        help="Source-of-truth backend (default: cpp-json)",
    )
    parser.add_argument(
        "--candidate",
        default=os.environ.get("CANDIDATE_BACKEND", "python"),
        help="Backend under test (default: python; override in feature branches that add a third backend)",
    )
    parser.add_argument(
        "--max-mismatch-samples",
        type=int,
        default=3,
        help="Per category, max sample mismatches to print (default: 3)",
    )
    parser.add_argument(
        "--print-rejects",
        action="store_true",
        help="Also print sample candidate-rejected queries (oracle accepted)",
    )
    parser.add_argument(
        "--shrink-failures",
        action="store_true",
        help="Run an auto-shrinker on each printed failure to produce a minimal repro",
    )
    parser.add_argument(
        "--write-divergences",
        metavar="PATH",
        default=None,
        help="Write JSONL with one entry per failing example (query + diff path)",
    )
    args = parser.parse_args()
    oracle = args.oracle
    candidate = args.candidate

    # Sanity-probe the backends so we fail fast with a clear error
    # rather than mid-run with cryptic Hypothesis output.
    for label, backend in (("oracle", oracle), ("candidate", candidate)):
        try:
            _try_parse("1", args.rule, backend)
        except Exception as e:
            print(f"ERROR: {label} backend {backend!r} unavailable: {e}")
            return 1

    counts: Counter[str] = Counter()
    mismatch_buckets: dict[tuple[str, str], list[tuple[str, list]]] = {}
    reject_buckets: dict[str, list[str]] = {}

    base_strategy = expr_strategy() if args.rule == "expr" else select_strategy()
    strategy = base_strategy.flatmap(_apply_jiggle) if args.jiggle else base_strategy

    # Stream JSONL during the run rather than collecting everything in
    # memory. `jsonl_file` is None when --write-divergences isn't set.
    jsonl_file = open(args.write_divergences, "w") if args.write_divergences else None
    jsonl_count = 0

    def write_record(rec: dict, shape_for_shrink: DivergenceShape | None) -> None:
        nonlocal jsonl_count
        if jsonl_file is None:
            return
        if args.shrink_failures and shape_for_shrink is not None:
            rec["query_shrunk"] = _shrink_query(rec["query"], args.rule, oracle, candidate, shape_for_shrink)
        if "diff_path" in rec:
            rec["diff_path"] = [list(s) if isinstance(s, tuple) else s for s in rec["diff_path"]]
        jsonl_file.write(json.dumps(rec) + "\n")
        jsonl_count += 1

    # Reuse the pytest PBT's shared settings (deadline=None, slow /
    # filter-too-much suppression) and only override `max_examples`
    # from the CLI flag. The pytest PBT deliberately leaves
    # `data_too_large` unsuppressed — same signal here.
    @given(query=strategy)
    @settings(parent=_PBT_SETTINGS, max_examples=args.n)
    def run(query: str) -> None:
        counts["total"] += 1

        o_ok, o_ast = _try_parse(query, args.rule, oracle)
        if not o_ok:
            counts["oracle_reject"] += 1
            return

        c_ok, c_ast = _try_parse(query, args.rule, candidate)
        if not c_ok:
            counts["candidate_reject"] += 1
            sig = _reject_error(query, args.rule, candidate)
            reject_buckets.setdefault(sig, []).append(query)
            write_record(
                {
                    "kind": "candidate_reject",
                    "rule": args.rule,
                    "oracle": oracle,
                    "candidate": candidate,
                    "query": query,
                    "reject_signature": sig,
                },
                DivergenceShape(kind="candidate_reject", reject_signature=sig),
            )
            return

        if o_ast == c_ast:
            counts["match"] += 1
            return

        counts["ast_mismatch"] += 1
        bucket = (_node_type(o_ast), _node_type(c_ast))
        steps = _diff_path(o_ast, c_ast)
        mismatch_buckets.setdefault(bucket, []).append((query, steps))
        write_record(
            {
                "kind": "ast_mismatch",
                "rule": args.rule,
                "oracle": oracle,
                "candidate": candidate,
                "query": query,
                "oracle_root": bucket[0],
                "candidate_root": bucket[1],
                "diff_path": steps,
            },
            _ast_mismatch_shape(bucket, steps),
        )

    try:
        run()
    except Exception:
        traceback.print_exc()
    finally:
        if jsonl_file is not None:
            jsonl_file.close()

    # ---- Summary ----------------------------------------------------------
    print()
    print(
        f"=== PBT run: rule={args.rule} oracle={oracle} candidate={candidate} "
        f"jiggle={args.jiggle} max_examples={args.n} ==="
    )
    for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {k:32s} {v}")

    # ---- ast_mismatch categorization + samples ----------------------------
    if mismatch_buckets:
        total = sum(len(v) for v in mismatch_buckets.values())
        print()
        print(f"=== ast_mismatch categories ({total} total) ===")
        sorted_mismatch_buckets = sorted(mismatch_buckets.items(), key=lambda kv: -len(kv[1]))
        for (o_t, c_t), examples in sorted_mismatch_buckets:
            print(f"  {o_t} vs {c_t}: {len(examples)}")
        print()
        print(f"=== Sample mismatches (up to {args.max_mismatch_samples} per category) ===")
        for (o_t, c_t), examples in sorted_mismatch_buckets:
            print(f"\n--- {o_t} vs {c_t} ({len(examples)} total) ---")
            for query, steps in examples[: args.max_mismatch_samples]:
                _print_failure_sample(
                    query,
                    args.rule,
                    oracle,
                    candidate,
                    _ast_mismatch_shape((o_t, c_t), steps),
                    shrink=args.shrink_failures,
                    diff_steps=steps,
                )

    # ---- candidate_reject categorization + samples ------------------------
    if reject_buckets and (args.print_rejects or args.shrink_failures):
        total = sum(len(v) for v in reject_buckets.values())
        print()
        print(f"=== candidate_reject categories ({total} total) ===")
        sorted_reject_buckets = sorted(reject_buckets.items(), key=lambda kv: -len(kv[1]))
        for sig, queries in sorted_reject_buckets:
            print(f"  [{len(queries):3d}] {sig}")
        if args.print_rejects:
            print()
            print(f"=== Sample candidate_rejects (up to {args.max_mismatch_samples} per category) ===")
            for sig, queries in sorted_reject_buckets:
                print(f"\n--- {sig} ({len(queries)} total) ---")
                shape = DivergenceShape(kind="candidate_reject", reject_signature=sig)
                for query in queries[: args.max_mismatch_samples]:
                    _print_failure_sample(query, args.rule, oracle, candidate, shape, shrink=args.shrink_failures)

    if args.write_divergences:
        print()
        print(f"=== Wrote {jsonl_count} divergence records to {args.write_divergences} ===")

    return 0


if __name__ == "__main__":
    sys.exit(main())
