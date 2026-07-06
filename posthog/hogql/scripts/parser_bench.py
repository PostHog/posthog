# ruff: noqa: T201, E402, I001
# CLI benchmark tool: print() is the report channel, and the imports
# are deferred until after `django.setup()` so the order is intentional.
"""Side-by-side parser performance benchmark — backend-agnostic.

`--oracle` defaults to `cpp-json`. `--candidate` is REQUIRED (no
default) so the backend under test is always stated explicitly — pass
e.g. `rust-py` or `rust-json`.

The query corpus mirrors what the diagnostic PBT runner uses, so
bench timings line up with parity numbers from the same workload.

Run from repo root:

    CANDIDATE_BACKEND=<some-fast-backend> \\
        PYTHONPATH=. python posthog/hogql/scripts/parser_bench.py

Queries the candidate can't parse are flagged and the row is skipped.
For comparable queries the script reports per-call microseconds and a
`oracle/candidate` ratio.

Statistical rigor: each query is timed across `--repeat` batches of
`--n` iterations each. Min / median / max are reported so noise can
be told apart from real changes — the default repeat count is sized
to surface clear medians without ballooning wall-clock.

**Noise floor caveat.** Empirically, back-to-back runs of the SAME
binary on the SAME machine drift by 5–7% on the per-rule sum, even at
N=1000 × 7 batches. The within-run min/max bands are tight (~1–2% of
median), but the between-run drift is larger — thermal, scheduler,
GC, and other system effects don't cancel out within a single bench
invocation. Treat single-run deltas under ~7% as inconclusive; for
optimization tracking, run the bench at least twice and look for
consistent direction across both runs. The ★★★ significance flag is
within-run noise-floor only and doesn't account for between-run
drift.

For tracking optimization gains, write results to JSON via
`--json-output PATH`, then re-run with `--compare PATH` to see the
per-query delta.

For deeper profiling, run the bench under `samply` or `py-spy`:

    samply record -- python posthog/hogql/scripts/parser_bench.py \\
        --candidate rust-py --n 5000 --repeat 1

Then open the resulting profile.json in samply's UI (https://profiler.firefox.com).

The script is intentionally dependency-free beyond what's already in
the backend environment so it can stay around as a quick perf sanity
check as parser implementations evolve.
"""

import argparse
import json
import os
import statistics
import sys
import timeit
from pathlib import Path
from typing import Any

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

from posthog.hogql.parser import HogQLParserShadowMismatch, clear_parse_caches, parse_expr, parse_select
from posthog.hogql.scripts._diagnostic_common import _abort_on_shadow_mismatch, _probe_backend

DEFAULT_N = 1_000  # iterations per batch; override with --n
DEFAULT_REPEAT = 5  # batches per query; override with --repeat

# Per-query iteration ceilings for queries cpp parses too slowly for
# the default N. Total wall-clock per row should stay well under a
# minute; cpp can be ~250ms+ on `pathological_deep` so 1000 iterations
# would burn 4+ minutes before the candidate row even starts. Applied
# as `min(override, n)` so they only ever LOWER the count — a small
# `--n` (e.g. a 50-iteration sanity check) is never raised back up.
N_PER_QUERY: dict[str, int] = {
    "pathological_deep": 100,
    # cpp is comparatively slow on this one; cap iterations so the row
    # stays a few seconds rather than tens.
    "nested_maybe_quadratic": 200,
}


def _nested_replace(depth: int) -> str:
    """`columns(* replace(… as b))` nested `depth` levels deep — the
    `nested_maybe_quadratic` bench query (see EXPR_QUERIES)."""
    inner = "a"
    for _ in range(depth):
        inner = f"columns(* replace({inner} as b))"
    return inner


def _between_trailing_chain(n: int) -> str:
    """`x BETWEEN lo1 AND hi1 BETWEEN lo2 AND hi2 …` — `n` links folded
    left-associatively through the Pratt loop (each high bound stops at the
    next BETWEEN). The `between_chain_20` bench query (see EXPR_QUERIES)."""
    return "x0 " + " ".join(f"BETWEEN lo{i} AND hi{i}" for i in range(1, n + 1))


def _between_and_chain(n: int) -> str:
    """`x1 BETWEEN a1 AND b1 AND x2 BETWEEN a2 AND b2 AND …` — `n` BETWEENs
    joined by AND, the production `WHERE`-clause shape the two-tier grammar
    fixed. The `between_and_chain_20` bench query (see EXPR_QUERIES)."""
    return " AND ".join(f"x{i} BETWEEN a{i} AND b{i}" for i in range(1, n + 1))


EXPR_QUERIES: dict[str, str] = {
    "int_literal": "1",
    "arith": "1 + 2 * 3",
    "parens": "(1 + 2) * 3",
    "field": "events.timestamp",
    "field_deep": "events.properties.foo.bar.baz",
    "compare": "events.event = '$pageview'",
    "in_clause": "event IN ('$ai_generation', '$ai_span', '$ai_trace')",
    "not_in_clause": "event NOT IN ('$pageview', '$autocapture')",
    "like": "url LIKE '%admin%'",
    "call_simple": "count()",
    "call_args": "toStartOfDay(timestamp)",
    "call_nested": "if(event = '$pageview', 1, 0)",
    "and_or": "event = 'a' AND (status = 'ok' OR status = 'pending')",
    "is_null": "events.foo IS NULL",
    "between": "value BETWEEN 1 AND 10",
    "ternary": "x > 0 ? x : -x",
    "alias": "count() AS total",
    "tuple_access": "t.1",
    "typical_where": "event = '$pageview' AND timestamp > now() AND properties.foo = 'bar'",
    "and_chain_10": "a = 1 AND b = 2 AND c = 3 AND d = 4 AND e = 5 AND f = 6 AND g = 7 AND h = 8 AND i = 9 AND j = 10",
    # Deep/wide BETWEEN probe — twelve BETWEENs in an array literal, the
    # last four nesting an inner BETWEEN inside the outer's bounds via
    # parens. BETWEEN binds at the comparison tier, so its bounds are
    # value-tier and cannot swallow the array's separator commas or a
    # trailing AND chain — there is no speculative low/high split to
    # recover from. This row guards against a parse-time blow-up on a
    # dense array of nested BETWEENs (the ratio against `between`, a
    # single trivial BETWEEN, should stay roughly linear in the count).
    "nasty_backtrack": """[
        x1 BETWEEN a1 + 1 AND b1,
        x2 BETWEEN f(c2) AND c2 * 2,
        x3 BETWEEN p3 AND b3 AND c3,
        x4 BETWEEN c1 AND c3,
        x5 BETWEEN e5 % 3 AND b5,
        x6 BETWEEN q6 AND b6,
        x7 BETWEEN d7 AND b7,
        x8 BETWEEN f1 AND f3,
        x9  BETWEEN (h BETWEEN i9 AND j9) AND b9,
        x10 BETWEEN (l BETWEEN m10 AND n10) AND b10,
        x11 BETWEEN y11 AND (n BETWEEN o11 AND p11),
        x12 BETWEEN q12 AND (r BETWEEN s12 AND t12)
    ]""",
    "mixed_and_or": """
        (event = '$pageview' OR event = '$autocapture' OR event = '$identify')
        AND timestamp > now()
        AND properties.foo IN ('Chrome', 'Firefox', 'Safari')
        AND (properties.url LIKE '%admin%' OR properties.url LIKE '%dashboard%')
        AND NOT (properties.os = 'Linux' AND properties.device = 'Desktop')
    """,
    # Deep BETWEEN chains — the shapes that must stay linear in parse time.
    # `between_chain_20` folds trailing BETWEENs left-associatively;
    # `between_and_chain_20` is twenty BETWEENs joined by AND (the production
    # WHERE-clause shape). Per-call µs on either row growing faster than the
    # link count means a super-linear regression on the BETWEEN path.
    "between_chain_20": _between_trailing_chain(20),
    "between_and_chain_20": _between_and_chain(20),
    # Deeply-nested `columns(* replace(… as b))`. Each REPLACE item
    # parse runs a forward scan (`find_replace_item_as_pos`, and the
    # sibling `find_cast_separator_pos`) to locate the item's
    # separating `AS`; that scan is O(remaining input) and re-runs at
    # every nesting level, so a hand-rolled parser is O(N^2) here
    # while ANTLR (cpp) stays linear. This row is the canary for that
    # scan: if the candidate's per-call µs — or the cpp/candidate
    # ratio — degrades, the AS-position scan has regressed. The scan
    # constant is a raw byte walk, so at this depth the candidate
    # should still parse it in well under a millisecond.
    "nested_maybe_quadratic": _nested_replace(50),
}

SELECT_QUERIES: dict[str, str] = {
    "tiny": "SELECT 1",
    "events_simple": "SELECT count() FROM events WHERE event = '$exception'",
    "events_in_clause": "SELECT count() FROM events WHERE event IN ('$ai_generation', '$ai_span', '$ai_trace')",
    "join_persons": """
        SELECT e.event, e.timestamp, p.id FROM events AS e
        JOIN persons AS p ON p.id = e.person_id
        WHERE e.event = '$ai_generation'
    """,
    "subquery_with_filters": """
        SELECT day_start, sum(c) FROM (
            SELECT count() AS c, toStartOfDay(timestamp) AS day_start, properties.foo AS f
            FROM events
            WHERE event = '$pageview' AND timestamp > now() - INTERVAL 30 DAY
            GROUP BY day_start, f
            HAVING c > 10
        )
        GROUP BY day_start ORDER BY day_start LIMIT 50
    """,
    "trends_like_breakdown": """
        SELECT groupArray(day_start)[1], arrayMap(x -> sum(x), counts), breakdown_value FROM (
            SELECT day_start,
                   sum(count) OVER (PARTITION BY breakdown_value ORDER BY day_start) AS counts,
                   breakdown_value
            FROM (
                SELECT count(DISTINCT person_id) AS count, toStartOfDay(timestamp) AS day_start,
                       properties.$some_property AS breakdown_value FROM events
                WHERE event = 'sign up' AND timestamp > now() - INTERVAL 7 DAY
                GROUP BY day_start, breakdown_value
            )
            GROUP BY day_start, breakdown_value, counts
            ORDER BY day_start
        )
        GROUP BY breakdown_value LIMIT 50
    """,
    "pathological_deep": """
        WITH active_users AS (
            SELECT distinct_id, min(timestamp) AS first_seen, max(timestamp) AS last_seen, count() AS event_count,
                   sum(if(event = '$pageview', 1, 0)) AS pageview_count,
                   sum(if(event = '$autocapture', 1, 0)) AS autocapture_count,
                   sum(if(event = 'sign up', 1, 0)) AS signup_count,
                   sum(if(event = 'product viewed', 1, 0)) AS product_count,
                   sum(if(event = 'purchase', 1, 0)) AS purchase_count
            FROM events
            WHERE timestamp > now() - INTERVAL 30 DAY
              AND event IN ('$pageview', '$autocapture', 'sign up', 'product viewed', 'item added to cart',
                            'purchase', 'subscription started', 'subscription cancelled', '$identify', '$set',
                            '$exception', '$web_vitals', '$ai_generation', '$feature_flag_called')
              AND properties.$browser IN ('Chrome', 'Firefox', 'Safari', 'Edge', 'Opera', 'Brave')
              AND properties.$os IN ('macOS', 'Windows', 'Linux', 'iOS', 'Android')
            GROUP BY distinct_id
            HAVING event_count > 3 AND pageview_count > 1
        ),
        breakdown_pre AS (
            SELECT toStartOfDay(e.timestamp) AS day_start, e.properties.$some_property AS breakdown_value,
                   e.properties.$browser AS browser, e.properties.$os AS os,
                   e.properties.$device_type AS device, e.properties.$current_url AS url,
                   count(DISTINCT e.person_id) AS count,
                   sum(if(e.event = 'sign up', 1, 0)) AS signups,
                   sum(if(e.event = 'purchase', 1, 0)) AS purchases
            FROM events AS e
            JOIN active_users AS au ON e.distinct_id = au.distinct_id
            LEFT JOIN persons AS p ON p.id = e.person_id
            WHERE e.event IN ('sign up', 'purchase', '$pageview', 'subscription started')
              AND e.timestamp > now() - INTERVAL 14 DAY
              AND e.properties.$ai_generation IS NULL AND e.properties.$exception IS NULL
              AND coalesce(e.properties.value, 0) > 0
            GROUP BY day_start, breakdown_value, browser, os, device, url
        ),
        combined AS (
            SELECT day_start, count, signups, purchases, breakdown_value, browser, os, device, url
            FROM breakdown_pre
            WHERE count > 5 AND signups > 0
            UNION ALL
            SELECT toStartOfDay(timestamp) AS day_start, count() AS count, 0 AS signups, 0 AS purchases,
                   properties.$some_property AS breakdown_value, properties.$browser AS browser,
                   properties.$os AS os, properties.$device_type AS device, properties.$current_url AS url
            FROM events
            WHERE event = '$exception' AND timestamp > now() - INTERVAL 7 DAY
            GROUP BY day_start, breakdown_value, browser, os, device, url
        )
        SELECT groupArray(day_start)[1] AS first_day,
               arraySum(arrayMap(x -> x, groupArray(count))) AS total_count,
               arraySum(groupArray(signups)) AS total_signups,
               arraySum(groupArray(purchases)) AS total_purchases,
               breakdown_value, browser, os, device, count(DISTINCT url) AS distinct_urls
        FROM combined
        GROUP BY breakdown_value, browser, os, device
    """,
}


# ============================================================================
# Statistics
# ============================================================================


class RowStat:
    """Per-(query, backend) timing summary across multiple batches."""

    __slots__ = ("samples_us", "n_per_batch")

    def __init__(self, samples_us: list[float], n_per_batch: int) -> None:
        # `samples_us` is one mean-per-call value per batch (already divided by the batch's iteration count). Kept around for downstream min / median / max / IQR / comparison.
        self.samples_us = samples_us
        self.n_per_batch = n_per_batch

    @property
    def median(self) -> float:
        return statistics.median(self.samples_us)

    @property
    def min(self) -> float:
        return min(self.samples_us)

    @property
    def max(self) -> float:
        return max(self.samples_us)

    @property
    def mean(self) -> float:
        return statistics.fmean(self.samples_us)

    def to_json(self) -> dict[str, Any]:
        return {
            "samples_us": self.samples_us,
            "n_per_batch": self.n_per_batch,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "RowStat":
        return cls(samples_us=list(data["samples_us"]), n_per_batch=int(data["n_per_batch"]))


def _format_us(us: float) -> str:
    """Per-call µs formatted for the human-readable table — wide enough to keep the column aligned across the corpus' three orders of magnitude (a few µs for `int_literal`, thousands for `pathological_deep`)."""
    return f"{us:>10.3f}"


# ============================================================================
# Bench runner
# ============================================================================


def time_one(parse_fn, n: int) -> float:
    """Per-call microseconds for `n` iterations of `parse_fn()`. The caller pre-binds query/backend via closure so this stays single-arity. Clears the cache before each invocation so we measure cold parse cost, not the cache hit path."""

    def body() -> Any:
        clear_parse_caches()
        return parse_fn()

    secs = timeit.timeit(body, number=n)
    return secs / n * 1e6


def run_query(parse_fn, q: str, backend: str, n: int, repeat: int) -> RowStat:
    """Run `parse_fn(q, backend=backend)` for `repeat` batches of `n` iterations each. One warm-up call up front to surface errors before timing.

    Returns a `RowStat` with one sample per batch (each sample is a per-call µs mean) so callers can inspect min/median/max + raw distribution. Re-clears the parse cache inside each batch via `time_one`'s body wrapper."""
    parse_fn(q, backend=backend)
    samples = [time_one(lambda: parse_fn(q, backend=backend), n) for _ in range(repeat)]
    return RowStat(samples_us=samples, n_per_batch=n)


# ============================================================================
# Single-run report
# ============================================================================


def bench(
    label: str,
    parse_fn,
    queries: dict[str, str],
    n: int,
    repeat: int,
    oracle: str,
    candidate: str,
) -> tuple[int, dict[str, dict[str, Any]]]:
    """Run the bench for one rule across the whole corpus.

    Returns `(comparable_count, results_dict)` where `results_dict` maps query name → {oracle: RowStat.to_json(), candidate: RowStat.to_json(), chars: int, error: optional[str]}. The caller assembles the rule-keyed top-level dict for JSON serialisation.
    """
    # Per-query iteration overrides (slow cpp queries would otherwise burn minutes) — surface them in the header so readers correlating header `N` to a row's µs know the row may have used a different N.
    # Show only overrides that actually take effect at this `n` — with a small `--n` the `min(override, n)` ceiling collapses to `n` and the override becomes a no-op.
    overrides_in_use = {
        name: min(N_PER_QUERY[name], n) for name in queries if name in N_PER_QUERY and N_PER_QUERY[name] < n
    }
    override_note = f", overrides: {overrides_in_use}" if overrides_in_use else ""
    print(f"\n{label}  (N={n} per batch × {repeat} batches, oracle={oracle}, candidate={candidate}{override_note})")
    print(
        f"{'query':<30} {'chars':>6} "
        f"{'oracle median':>14} {'(min..max)':>15} "
        f"{'cand median':>13} {'(min..max)':>15} "
        f"{'ratio':>7}"
    )
    print("-" * 105)

    results: dict[str, dict[str, Any]] = {}
    oracle_total, cand_total, comparable = 0.0, 0.0, 0
    for name, q in queries.items():
        nq = min(N_PER_QUERY.get(name, n), n)
        row_label = name if nq == n else f"{name} [N={nq}]"
        row: dict[str, Any] = {"chars": len(q)}
        try:
            oracle_stat = run_query(parse_fn, q, oracle, nq, repeat)
            row["oracle"] = oracle_stat.to_json()
        except HogQLParserShadowMismatch as e:
            _abort_on_shadow_mismatch(oracle, e)
        except Exception as e:
            row["error"] = f"oracle ({oracle}): {e}"
            results[name] = row
            print(f"{row_label:<30} {len(q):>6}  ERROR ({oracle}: {e})")
            continue
        try:
            cand_stat = run_query(parse_fn, q, candidate, nq, repeat)
            row["candidate"] = cand_stat.to_json()
        except HogQLParserShadowMismatch as e:
            _abort_on_shadow_mismatch(candidate, e)
        except Exception as e:
            row["error"] = f"candidate ({candidate}): {e}"
            results[name] = row
            print(f"{row_label:<30} {len(q):>6} {_format_us(oracle_stat.median)} (skip)  ({candidate}: {e})")
            continue
        ratio = oracle_stat.median / cand_stat.median if cand_stat.median > 0 else float("nan")
        print(
            f"{row_label:<30} {len(q):>6} "
            f"{_format_us(oracle_stat.median)} "
            f"({oracle_stat.min:>6.1f}..{oracle_stat.max:<6.1f}) "
            f"{_format_us(cand_stat.median)} "
            f"({cand_stat.min:>6.1f}..{cand_stat.max:<6.1f}) "
            f"{ratio:>6.1f}x"
        )
        oracle_total += oracle_stat.median
        cand_total += cand_stat.median
        comparable += 1
        results[name] = row

    print("-" * 105)
    if comparable:
        # Mean cells use per-row medians; overall ratio is `sum(oracle_median) / sum(cand_median)`, weighting each row by absolute time — the right metric for "overall speedup", since averaging per-row ratios would let cheap rows drown out expensive ones.
        overall = oracle_total / cand_total if cand_total > 0 else float("nan")
        print(
            f"{'mean (per-call µs)':<30} {'':>6} "
            f"{oracle_total / comparable:>14.3f} {'':>15} "
            f"{cand_total / comparable:>13.3f} {'':>15} "
            f"{overall:>6.1f}x  "
            f"(ratio sum-weighted; {comparable}/{len(queries)} comparable)"
        )
    return comparable, results


# ============================================================================
# Compare-mode report
# ============================================================================


def _significant(a: RowStat, b: RowStat) -> bool:
    """Significance gate: non-overlapping [min..max] ranges AND ≥5% relative delta. The 5% threshold sits at the upper edge of the 5–7% same-binary noise floor observed across repeat runs. Single-sample stats fall back to the relative-threshold-only check since they can't drive the non-overlap test."""
    if len(a.samples_us) <= 1 or len(b.samples_us) <= 1:
        return abs(a.median - b.median) / max(a.median, b.median, 1e-9) > 0.05
    non_overlap = a.max < b.min or b.max < a.min
    rel_delta = abs(a.median - b.median) / max(a.median, b.median, 1e-9)
    return non_overlap and rel_delta > 0.05


def _delta_str(before: float, after: float) -> str:
    """`+12.3%` / `-12.3%` for a row delta; falls back to `nan` if the baseline value was zero."""
    if before <= 0:
        return "nan"
    pct = (after - before) / before * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def compare(baseline_path: Path, current_data: dict[str, Any], candidate: str) -> None:
    """Diff a previous JSON result against the current run. Per-row delta + significance flag; sum-weighted-mean delta for each rule.

    `current_data` is the in-memory result dict the live run just built (rules → query → row). `baseline_path` points at a previous `--json-output` file; we compare candidate stats only — oracle stats are typically the same backend across runs, and even when they're not, a "candidate before vs candidate after" diff is what optimization runs want."""
    print(f"\n=== Compare candidate {candidate!r} vs baseline {baseline_path.as_posix()} ===\n")

    baseline_raw = json.loads(baseline_path.read_text())
    base_candidate = baseline_raw.get("meta", {}).get("candidate", "<unknown>")
    if base_candidate != candidate:
        print(
            f"NOTE: baseline candidate {base_candidate!r} differs from current {candidate!r} — "
            f"deltas compare two DIFFERENT backends, not the same backend before/after.\n"
        )

    for rule in ("parse_expr", "parse_select"):
        baseline_rows = baseline_raw.get("rules", {}).get(rule, {})
        current_rows = current_data.get("rules", {}).get(rule, {})
        if not baseline_rows or not current_rows:
            continue
        print(f"\n{rule} (candidate diff)")
        print(f"{'query':<30} {'before':>10} {'after':>10} {'delta':>10}  flag")
        print("-" * 75)
        before_total, after_total = 0.0, 0.0
        for name in current_rows:
            before_row = baseline_rows.get(name)
            after_row = current_rows.get(name)
            if before_row is None or "candidate" not in before_row or "candidate" not in after_row:
                continue
            before = RowStat.from_json(before_row["candidate"])
            after = RowStat.from_json(after_row["candidate"])
            flag = "★★★" if _significant(before, after) else ""
            improvement = before.median > after.median
            flag_color = flag + (" (faster)" if improvement and flag else (" (slower)" if flag else ""))
            print(
                f"{name:<30} {_format_us(before.median):>10} {_format_us(after.median):>10} "
                f"{_delta_str(before.median, after.median):>10}  {flag_color}"
            )
            before_total += before.median
            after_total += after.median
        print("-" * 75)
        if before_total > 0 and after_total > 0:
            print(
                f"{'sum (per-call µs)':<30} {before_total:>10.3f} {after_total:>10.3f} "
                f"{_delta_str(before_total, after_total):>10}"
            )


# ============================================================================
# CLI plumbing
# ============================================================================


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--oracle",
        default=os.environ.get("ORACLE_BACKEND", "cpp-json"),
        help="Source-of-truth backend (default: cpp-json)",
    )
    parser.add_argument(
        "--candidate",
        default=os.environ.get("CANDIDATE_BACKEND"),
        help=(
            "Backend under test (no default, so it's always stated "
            "explicitly). Set CANDIDATE_BACKEND or pass --candidate to a "
            "backend available in your environment, e.g. rust-py or rust-json."
        ),
    )
    parser.add_argument(
        "--n",
        type=int,
        default=DEFAULT_N,
        help=(
            f"Iterations per batch (default: {DEFAULT_N}). Lower it for a quick "
            f"sanity check during grinding, e.g. --n 50. Per-query ceilings in "
            f"N_PER_QUERY still apply as min(ceiling, --n)."
        ),
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=DEFAULT_REPEAT,
        help=(
            f"Batches per query (default: {DEFAULT_REPEAT}). Each batch is "
            f"`--n` iterations; we report median / min / max across the "
            f"batches so noise can be told apart from real changes. Set to 1 "
            f"for a quick run, 10+ for an optimization-tracking baseline."
        ),
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=None,
        help=(
            "Write the full result corpus to PATH as JSON. The file shape is "
            "`{meta: {…}, rules: {parse_expr: {query: {oracle, candidate, chars}}, "
            "parse_select: {…}}}`. Use with `--compare` on a future run to "
            "diff the two."
        ),
    )
    parser.add_argument(
        "--compare",
        type=Path,
        default=None,
        help=(
            "After running the bench, load a previous `--json-output` file at "
            "PATH and print a per-row delta with a significance flag (★★★ when "
            "the two runs' [min..max] ranges don't overlap, i.e., the change "
            "is larger than the noise floor)."
        ),
    )
    args = parser.parse_args()
    if args.n < 1:
        print("ERROR: --n must be at least 1")
        return 2
    if args.repeat < 1:
        print("ERROR: --repeat must be at least 1")
        return 2
    if not args.candidate:
        print(
            "ERROR: --candidate is required (no default); pass a backend "
            "available in your environment, e.g. rust-py or rust-json."
        )
        return 2

    # Sanity-probe both rules on both backends so a typo, a missing
    # backend, or a backend with partial rule coverage (e.g. expr only,
    # no select) fails immediately with a readable error rather than
    # tripping the per-row `except` on every query and silently
    # reporting zero comparable rows. We bench parse_expr AND
    # parse_select below, so probing only one rule would miss the
    # partial-implementation case entirely.
    for rule in ("expr", "select"):
        for label, backend in (("oracle", args.oracle), ("candidate", args.candidate)):
            err = _probe_backend(rule, backend)
            if err is not None:
                print(f"ERROR: {label} backend {backend!r} unavailable for rule {rule!r}: {err}")
                return 2

    comparable = 0
    rules_data: dict[str, dict[str, Any]] = {}
    expr_comparable, expr_rows = bench(
        "parse_expr", parse_expr, EXPR_QUERIES, args.n, args.repeat, args.oracle, args.candidate
    )
    select_comparable, select_rows = bench(
        "parse_select", parse_select, SELECT_QUERIES, args.n, args.repeat, args.oracle, args.candidate
    )
    comparable = expr_comparable + select_comparable
    rules_data["parse_expr"] = expr_rows
    rules_data["parse_select"] = select_rows

    if comparable == 0:
        print(
            f"\nERROR: zero comparable rows — candidate {args.candidate!r} "
            f"failed every query. Backend is reachable (probe passed) but "
            f"can't parse any of the corpus; this is a regression, not a "
            f"config issue."
        )
        return 1

    current_data = {
        "meta": {
            "oracle": args.oracle,
            "candidate": args.candidate,
            "n_per_batch": args.n,
            "repeats": args.repeat,
        },
        "rules": rules_data,
    }

    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(current_data, indent=2))
        print(f"\nWrote results to {args.json_output}")

    if args.compare:
        compare(args.compare, current_data, args.candidate)

    return 0


if __name__ == "__main__":
    sys.exit(main())
