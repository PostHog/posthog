"""Diagnostic PBT runner: oracle backend vs candidate backend.

Reuses the strategies from `test_parser_grammar_pbt.py` (the
auto-generated grammar PBT introduced in PR #58627) but runs as an
ad-hoc CLI rather than a pytest collection. Defaults to `cpp-json` vs
`rust-py` (the primary parity target — `rust-json` was a stepping
stone and may end up in a future wasm build, but isn't the primary
production candidate).

Distinct from the pytest PBT in five ways:

1. **AST node-type pair categorization.** Each ast_mismatch is
   bucketed by `(oracle.root_node, candidate.root_node)` so the
   dominant divergence classes surface immediately — no manual
   eyeballing of 200-line AST dumps.
2. **Diff-only AST output.** When printing a sample mismatch, walk
   both ASTs together and print only the path from root to the first
   differing node.
3. **Auto-shrinker (`--shrink-failures`).** For each ast_mismatch
   and reject, run shrinkray (via `_shrink` / `shrink_to_shape`) to
   reduce it to the smallest variant that still triggers the same
   divergence shape. Drops typical PBT failures from 200+ chars to a
   handful. Needs the optional `hogql-parser-parity` dependency group
   (`uv sync --group hogql-parser-parity`).
4. **Optional JSONL persistence (`--write-divergences PATH`).** Drop
   one JSON line per failing example for cross-run analysis or
   regression-corpus extraction.
5. **Reject categorization.** Group `candidate_reject` queries by the
   error message + leading-token signature so recurring shapes
   surface even though there's no AST to diff against.
6. **Crash bucketing.** A query that makes a backend raise a non-HogQL
   exception (`RecursionError`, a half-built parser's `RuntimeError`,
   …) is bucketed as `candidate_crash` / `oracle_crash` and the grind
   continues — surfacing the crash rather than aborting on it.

The shared parse / AST-diff / divergence-shape vocabulary lives in
`_diagnostic_common.py` alongside this script.

Typical usage:

    # Default: cpp-json vs rust-py
    PYTHONPATH=. python posthog/hogql/scripts/pbt_diagnostic.py --n 5000

    # With auto-shrinking on every failure
    PYTHONPATH=. python posthog/hogql/scripts/pbt_diagnostic.py \\
        --n 5000 --shrink-failures

    # Persist for later analysis / corpus extraction
    PYTHONPATH=. python posthog/hogql/scripts/pbt_diagnostic.py \\
        --write-divergences /tmp/divergences.jsonl --shrink-failures

    # While iterating on a parser version bump the pyproject pin references a
    # not-yet-published wheel, so `flox activate` is blocked. Run via the
    # worktree venv python directly, having rebuilt the parser .so locally
    # first (rust: `uv pip install -e rust/hogql/parser`; cpp: rebuild
    # `common/hogql_parser` and copy the built .so into `.flox/cache/venv`).
    # `--write-divergences` streams each finding as it's found, so a long run
    # that gets killed still leaves its divergences on disk:
    PYTHONPATH=. .flox/cache/venv/bin/python posthog/hogql/scripts/pbt_diagnostic.py \\
        --rule program --grammar-mutate --n 10000 --write-divergences /tmp/div.jsonl
"""

# ruff: noqa: T201 (this is a CLI script — print is the output channel)
# ruff: noqa: E402 (DJANGO_SETTINGS_MODULE must be set before the project-app
#                   imports below)

from __future__ import annotations

import os
import sys
import json
import argparse
import traceback
from collections import Counter
from collections.abc import Callable
from typing import Any

# Skip django.setup(): parser core only reads settings.TEST, so settings alone avoids ready()-hook DB/redis init.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")

from hypothesis import (
    assume,
    given,
    settings,
    strategies as st,
)

# Eager so a missing `hogql-parser-parity` dep group fails at script-load,
# not mid-grind where shrink_to_shape would lose every finding so far.
from posthog.hogql.scripts import _shrink  # noqa: F401
from posthog.hogql.scripts._diagnostic_common import (
    DivergenceShape,
    _ast_mismatch_shape,
    _diff_path,
    _format_diff_path,
    _node_type,
    _probe_backend,
    _safe_parse,
    asts_agree,
    shrink_to_shape,
)
from posthog.hogql.test._generated_grammar_strategies import (
    expr_strategy,
    fullTemplateString_strategy,
    program_strategy,
    select_strategy,
)
from posthog.hogql.test.test_parser_grammar_pbt import (
    _PBT_SETTINGS,
    _apply_grammar_mutation,
    _apply_jiggle,
    _apply_mutation,
)

# ---------------------------------------------------------------------------
# string_literal strategy
# ---------------------------------------------------------------------------
# No generated strategy (the unquoter isn't a grammar rule): build quoted literals over a branch-driving alphabet.
_SL_QUOTE_PAIRS = [("'", "'"), ('"', '"'), ("`", "`"), ("{", "}")]
# Excludes NUL: the cpp wheel's PyArg_ParseTuple("s") rejects it (ValueError) while PyO3's &str accepts it.
_SL_ALPHABET = "'\"`{}\\bfrnt0avxyo ab\n\té£"


def string_literal_strategy() -> st.SearchStrategy[str]:
    body = st.text(alphabet=_SL_ALPHABET, max_size=12)
    quoted = st.builds(lambda pair, b: pair[0] + b + pair[1], st.sampled_from(_SL_QUOTE_PAIRS), body)
    # Raw never-empty forms (mismatched/unquoted) exercise the SyntaxError path; min_size=1 so cpp never sees "".
    raw = st.text(alphabet=_SL_ALPHABET, min_size=1, max_size=14)
    return st.one_of(quoted, raw)


# ---------------------------------------------------------------------------
# Auto-shrinker
# ---------------------------------------------------------------------------
#
# Hypothesis has moved on by the time the diagnostic sees a failure, so we re-reduce via shrinkray (`shrink_to_shape`) to the smallest variant with the same divergence shape — a tight repro to paste into a unit test.


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _print_failure_sample(
    query: str,
    shrunk: str | None,
    rule: str,
    oracle: str,
    candidate: str,
    *,
    diff_steps: list | None = None,
) -> None:
    """Print one sample failure. The caller pre-computes the shrunken
    form (None if shrinking is off) — both this print path and the
    JSONL writer pull from the same pre-shrunk string so they never
    disagree on the minimal repro. For ast_mismatch samples, pass
    `diff_steps` so the diff path renders against the original; when
    a shrunk query is present, re-parse it for a fresh diff path."""
    if shrunk is not None and shrunk != query:
        print(f"  query (shrunk {len(query)} -> {len(shrunk)}): {shrunk!r}")
        if diff_steps is not None:
            _, o_s, _ = _safe_parse(shrunk, rule, oracle)
            _, c_s, _ = _safe_parse(shrunk, rule, candidate)
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
    parser.add_argument(
        "--rule",
        choices=("expr", "select", "program", "full_template_string", "string_literal"),
        default="expr",
    )
    parser.add_argument("--jiggle", action="store_true")
    parser.add_argument(
        "--mutate",
        action="store_true",
        help=(
            "Perturb each generated query into a near-miss invalid one "
            "(delete/duplicate/swap/inject/unbalance/truncate tokens). Floods "
            "the rejection path so the two-sided contract gets exercised — most "
            "outputs are queries the oracle rejects, surfacing any the candidate accepts."
        ),
    )
    parser.add_argument(
        "--grammar-mutate",
        action="store_true",
        help=(
            "Perturb each generated query into a structurally-plausible invalid one "
            "using grammar knowledge (empty a bracketed list, dictify a `{x}` "
            "placeholder, swap/duplicate a keyword, retype a literal, mismatch a "
            "bracket). Aimed at over-acceptance: near-miss shapes a parser is more "
            "likely to wrongly accept than the lexical junk `--mutate` mostly yields."
        ),
    )
    parser.add_argument(
        "--accepted-only",
        action="store_true",
        help=(
            "Make `--n` count only examples the ORACLE accepts: oracle "
            "rejects/crashes are `assume()`d out (Hypothesis keeps "
            "generating until --n oracle-accepted examples are reached), "
            "so the match denominator is exactly --n."
        ),
    )
    _BACKENDS = ("cpp-json", "rust-json", "rust-py")
    parser.add_argument(
        "--oracle",
        default=os.environ.get("ORACLE_BACKEND", "cpp-json"),
        choices=_BACKENDS,
        help="Source-of-truth backend (default: cpp-json)",
    )
    parser.add_argument(
        "--candidate",
        default=os.environ.get("CANDIDATE_BACKEND", "rust-py"),
        choices=_BACKENDS,
        help="Backend under test (default: rust-py)",
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
        err = _probe_backend(args.rule, backend)
        if err is not None:
            print(f"ERROR: {label} backend {backend!r} unavailable: {err}")
            return 1

    counts: Counter[str] = Counter()
    # Buckets store `(query, shrunk_or_none, steps_for_mismatch)`; we shrink ONCE per failure here and reuse it for both the JSONL writer and the summary print loop, since shrinking is the slow step and doing it twice is pure waste.
    mismatch_buckets: dict[tuple[str, str], list[tuple[str, str | None, list]]] = {}
    reject_buckets: dict[str, list[tuple[str, str | None]]] = {}
    # Two-sided contract: the oracle rejected but the candidate accepted —
    # the candidate took an invalid query. Bucketed by the candidate AST's
    # root node type so the dominant over-acceptance shapes surface.
    accept_reject_buckets: dict[str, list[tuple[str, str | None]]] = {}
    # A candidate that raises a non-HogQL exception (RecursionError, a
    # half-built backend's RuntimeError, …) is a finding in its own
    # right — `_safe_parse` catches it so one crashing query can't
    # abort the whole grind. Keyed by normalised `<ExcType>: …`.
    crash_buckets: dict[str, list[str]] = {}

    # `Callable[..., ...]` so the no-arg `string_literal_strategy` and the `depth`-taking grammar strategies unify.
    strategies_by_rule: dict[str, Callable[..., st.SearchStrategy[str]]] = {
        "expr": expr_strategy,
        "select": select_strategy,
        "program": program_strategy,
        "full_template_string": fullTemplateString_strategy,
        "string_literal": string_literal_strategy,
    }
    base_strategy = strategies_by_rule[args.rule]()
    strategy = base_strategy
    # Grammar-aware mutation runs first, on the clean space-separated query —
    # the whitespace jiggle below would otherwise break its tokenisation.
    if args.grammar_mutate:
        strategy = strategy.flatmap(_apply_grammar_mutation)
    if args.jiggle:
        strategy = strategy.flatmap(_apply_jiggle)
    if args.mutate:
        strategy = strategy.flatmap(_apply_mutation)

    # Stream JSONL during the run rather than collecting everything in
    # memory. Opened in the try-block below so the strategy
    # construction and decorator application above have no chance to
    # leak the handle.
    jsonl_file: Any = None
    jsonl_count = 0

    def write_record(rec: dict, shrunk: str | None) -> None:
        nonlocal jsonl_count
        if jsonl_file is None:
            return
        if shrunk is not None:
            rec["query_shrunk"] = shrunk
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

        o_status, o_ast, _ = _safe_parse(query, args.rule, oracle)
        if o_status == "crash":
            # The oracle (source of truth) crashing is its own kind of
            # finding — count it, but with no oracle AST there's
            # nothing to compare the candidate against, so stop here.
            counts["oracle_crash"] += 1
            if args.accepted_only:
                assume(False)
            return
        if o_status == "reject":
            # Two-sided contract: the oracle rejected, so the candidate
            # must reject too. A candidate that *accepts* took an invalid
            # query — the headline failure this contract exists to catch.
            counts["oracle_reject"] += 1
            rc_status, rc_ast, rc_detail = _safe_parse(query, args.rule, candidate)
            if rc_status == "ok":
                counts["candidate_accepts_oracle_reject"] += 1
                bucket = _node_type(rc_ast)
                shape = DivergenceShape(kind="candidate_accepts_oracle_reject")
                shrunk = shrink_to_shape(query, args.rule, oracle, candidate, shape) if args.shrink_failures else None
                accept_reject_buckets.setdefault(bucket, []).append((query, shrunk))
                write_record(
                    {
                        "kind": "candidate_accepts_oracle_reject",
                        "rule": args.rule,
                        "oracle": oracle,
                        "candidate": candidate,
                        "query": query,
                        "candidate_root": bucket,
                    },
                    shrunk,
                )
            elif rc_status == "crash":
                counts["candidate_crash"] += 1
                sig = rc_detail or "<no message>"
                crash_buckets.setdefault(sig, []).append(query)
                write_record(
                    {
                        "kind": "candidate_crash",
                        "rule": args.rule,
                        "oracle": oracle,
                        "candidate": candidate,
                        "query": query,
                        "crash_signature": sig,
                    },
                    None,
                )
            else:
                # Both rejected — the contract is satisfied.
                counts["both_reject"] += 1
            # `--accepted-only`: discard so this doesn't count toward
            # `max_examples` — Hypothesis regenerates until `--n`
            # oracle-accepted examples land.
            if args.accepted_only:
                assume(False)
            return

        c_status, c_ast, c_detail = _safe_parse(query, args.rule, candidate)
        if c_status == "reject":
            counts["candidate_reject"] += 1
            sig = c_detail or "<no message>"
            shape = DivergenceShape(kind="candidate_reject", reject_signature=sig)
            shrunk = shrink_to_shape(query, args.rule, oracle, candidate, shape) if args.shrink_failures else None
            reject_buckets.setdefault(sig, []).append((query, shrunk))
            write_record(
                {
                    "kind": "candidate_reject",
                    "rule": args.rule,
                    "oracle": oracle,
                    "candidate": candidate,
                    "query": query,
                    "reject_signature": sig,
                },
                shrunk,
            )
            return
        if c_status == "crash":
            # Not shrunk: a crash isn't a stable `DivergenceShape`, so
            # `_shrink_query` can't reduce toward it. Recorded full.
            counts["candidate_crash"] += 1
            sig = c_detail or "<no message>"
            crash_buckets.setdefault(sig, []).append(query)
            write_record(
                {
                    "kind": "candidate_crash",
                    "rule": args.rule,
                    "oracle": oracle,
                    "candidate": candidate,
                    "query": query,
                    "crash_signature": sig,
                },
                None,
            )
            return

        if asts_agree(o_ast, c_ast):
            counts["match"] += 1
            return

        counts["ast_mismatch"] += 1
        mismatch_bucket = (_node_type(o_ast), _node_type(c_ast))
        steps = _diff_path(o_ast, c_ast)
        shape = _ast_mismatch_shape(mismatch_bucket, steps)
        shrunk = shrink_to_shape(query, args.rule, oracle, candidate, shape) if args.shrink_failures else None
        mismatch_buckets.setdefault(mismatch_bucket, []).append((query, shrunk, steps))
        write_record(
            {
                "kind": "ast_mismatch",
                "rule": args.rule,
                "oracle": oracle,
                "candidate": candidate,
                "query": query,
                "oracle_root": mismatch_bucket[0],
                "candidate_root": mismatch_bucket[1],
                "diff_path": steps,
            },
            shrunk,
        )

    # `run()` can fail outright — a Hypothesis `FailedHealthCheck`, a
    # backend import error surfacing mid-run, an unopenable
    # `--write-divergences` path. We still print whatever summary we
    # have, but track the failure so the exit code reflects it: tooling
    # that invokes the diagnostic non-interactively must not read a
    # crashed run as success.
    run_ok = True
    try:
        if args.write_divergences:
            jsonl_file = open(args.write_divergences, "w")  # noqa: SIM115 — see finally
        run()
    except Exception:
        traceback.print_exc()
        run_ok = False
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

    # ---- rejection-parity: candidate accepted what the oracle rejected ----
    # The headline failure of the two-sided contract — a candidate that
    # parses an invalid query. Printed first (and samples shown by default,
    # not gated behind `--print-rejects`) because it's a correctness bug,
    # not the noisier "candidate is stricter than the oracle" reject class.
    if accept_reject_buckets:
        total = sum(len(v) for v in accept_reject_buckets.values())
        print()
        print(f"=== candidate_accepts_oracle_reject ({total} total — candidate took an INVALID query) ===")
        sorted_ar_buckets = sorted(accept_reject_buckets.items(), key=lambda kv: -len(kv[1]))
        for root, queries in sorted_ar_buckets:
            print(f"  candidate root {root}: {len(queries)}")
        print()
        print(f"=== Sample candidate_accepts_oracle_reject (up to {args.max_mismatch_samples} per root) ===")
        for root, queries in sorted_ar_buckets:
            print(f"\n--- candidate root {root} ({len(queries)} total) ---")
            for query, shrunk in queries[: args.max_mismatch_samples]:
                _print_failure_sample(query, shrunk, args.rule, oracle, candidate)

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
            for query, shrunk, steps in examples[: args.max_mismatch_samples]:
                _print_failure_sample(query, shrunk, args.rule, oracle, candidate, diff_steps=steps)

    # ---- candidate_reject categorization + samples ------------------------
    # The category summary always prints (parity with the ast_mismatch
    # category table); per-query samples stay gated behind `--print-rejects`
    # to keep the default output short.
    if reject_buckets:
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
                for query, shrunk in queries[: args.max_mismatch_samples]:
                    _print_failure_sample(query, shrunk, args.rule, oracle, candidate)

    # ---- candidate_crash categorization + samples -------------------------
    if crash_buckets:
        total = sum(len(v) for v in crash_buckets.values())
        print()
        print(f"=== candidate_crash categories ({total} total — non-HogQL exceptions) ===")
        sorted_crash_buckets = sorted(crash_buckets.items(), key=lambda kv: -len(kv[1]))
        # Distinct loop names from the reject block above: crash buckets hold
        # bare query strings, reject buckets hold (query, shrunk) pairs.
        for crash_sig, crash_queries in sorted_crash_buckets:
            print(f"  [{len(crash_queries):3d}] {crash_sig}")
        if args.print_rejects:
            print()
            print(f"=== Sample candidate_crashes (up to {args.max_mismatch_samples} per category) ===")
            for crash_sig, crash_queries in sorted_crash_buckets:
                print(f"\n--- {crash_sig} ({len(crash_queries)} total) ---")
                for crash_query in crash_queries[: args.max_mismatch_samples]:
                    print(f"  query: {crash_query!r}")

    if args.write_divergences:
        print()
        print(f"=== Wrote {jsonl_count} divergence records to {args.write_divergences} ===")

    return 0 if run_ok else 1


if __name__ == "__main__":
    sys.exit(main())
