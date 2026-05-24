# ruff: noqa: T201, E402, I001
# CLI benchmark tool: print() is the report channel, and the imports
# are deferred until after `django.setup()` so the order is intentional.
"""Side-by-side parser performance benchmark — backend-agnostic.

`--oracle` defaults to `cpp-json`. `--candidate` is REQUIRED (no
default) — the Python backend is several orders of magnitude slower
than cpp on most queries and would take tens of minutes per row, so
we refuse to default to a useless target. Pass any other backend
explicitly when one is available in a feature branch.

The query corpus mirrors what the diagnostic PBT runner uses, so
bench timings line up with parity numbers from the same workload.

Run from repo root:

    CANDIDATE_BACKEND=<some-fast-backend> \\
        PYTHONPATH=. python posthog/hogql/scripts/parser_bench.py

Queries the candidate can't parse are flagged and the row is skipped.
For comparable queries the script reports per-call microseconds and a
`oracle/candidate` ratio.

The script is intentionally dependency-free beyond what's already in
the backend environment so it can stay around as a quick perf sanity
check as parser implementations evolve.
"""

import argparse
import os
import sys
import timeit
from typing import Any

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

from posthog.hogql.parser import HogQLParserShadowMismatch, clear_parse_caches, parse_expr, parse_select
from posthog.hogql.scripts._diagnostic_common import _abort_on_shadow_mismatch, _probe_backend

DEFAULT_N = 1_000  # iterations per row; override with --n

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
    # Worst-case backtracking probe — twelve BETWEENs in an array
    # literal, with each body chosen to absorb the separator `AND`
    # into a non-AND-rooted subtree (lambda body, AS-alias, named-arg,
    # ternary else). For a hand-rolled parser that resolves BETWEEN
    # by speculating across the body's `low AND high` split this
    # forces the slowest recovery path on every BETWEEN, and the last
    # four rows nest an inner BETWEEN inside the outer's body via
    # parens — so the inner is re-parsed once per outer speculation
    # alternative, doubling speculation work.
    #
    # For ANTLR ALL(*) (cpp) this is just twelve linear-lookahead
    # disambiguations — the ratio against `between` (a single trivial
    # BETWEEN) is the speculation-overhead signal: if `nasty_backtrack`
    # is significantly slower per BETWEEN than `between` on the
    # candidate, speculation cost is showing up.
    "nasty_backtrack": """[
        x1 BETWEEN lambda a : a AND b1,
        x2 BETWEEN col AS y2 AND c2,
        x3 BETWEEN p := 1 AND b3,
        x4 BETWEEN c1 ? c2 : c3 AND b4,
        x5 BETWEEN lambda e : e AND b5,
        x6 BETWEEN q := 2 AND b6,
        x7 BETWEEN d AS y7 AND b7,
        x8 BETWEEN f1 ? f2 : f3 AND b8,
        x9  BETWEEN lambda g : (h BETWEEN col AS i AND j) AND b9,
        x10 BETWEEN lambda k : (l BETWEEN p2 := 3 AND m) AND b10,
        x11 BETWEEN col AS y11 AND (n BETWEEN f4 ? f5 : f6 AND o),
        x12 BETWEEN q2 := 4 AND (r BETWEEN lambda s : s AND t)
    ]""",
    "mixed_and_or": """
        (event = '$pageview' OR event = '$autocapture' OR event = '$identify')
        AND timestamp > now()
        AND properties.foo IN ('Chrome', 'Firefox', 'Safari')
        AND (properties.url LIKE '%admin%' OR properties.url LIKE '%dashboard%')
        AND NOT (properties.os = 'Linux' AND properties.device = 'Desktop')
    """,
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


def run(parse_fn, n: int) -> float:
    """Per-call microseconds for `n` iterations of `parse_fn()`. The
    caller is expected to pre-bind the query (and backend) via a
    closure so this stays a single-arity callable. Clears the cache
    before each invocation so we measure cold parse cost rather than
    the cache hit path."""

    def body() -> Any:
        clear_parse_caches()
        return parse_fn()

    # Warm up to surface errors before we time.
    body()
    secs = timeit.timeit(body, number=n)
    return secs / n * 1e6


def bench(
    label: str,
    parse_fn,
    queries: dict[str, str],
    n: int,
    oracle: str,
    candidate: str,
) -> int:
    # Some rows have per-query iteration overrides (slow cpp queries
    # would otherwise burn minutes), so make that explicit in the
    # header — a reader correlating header `N` to a row's µs needs to
    # know the row may have used a different N.
    # Show only overrides that actually take effect at this `n` — with a
    # small `--n` the `min(override, n)` ceiling collapses to `n`, so the
    # override is a no-op and listing it would mislead.
    overrides_in_use = {
        name: min(N_PER_QUERY[name], n) for name in queries if name in N_PER_QUERY and N_PER_QUERY[name] < n
    }
    override_note = f", overrides: {overrides_in_use}" if overrides_in_use else ""
    print(f"\n{label}  (N={n} per row, oracle={oracle}, candidate={candidate}{override_note})")
    print(f"{'query':<30} {'chars':>6} {'oracle(us)':>12} {'candidate(us)':>14} {'oracle/cand':>12}")
    print("-" * 78)

    oracle_total, cand_total, comparable = 0.0, 0.0, 0
    for name, q in queries.items():
        nq = min(N_PER_QUERY.get(name, n), n)
        # Annotate the row name when its N differs from the header so a
        # reader doesn't have to cross-reference the override map to
        # interpret the µs value.
        row_label = name if nq == n else f"{name} [N={nq}]"
        try:
            oracle_us = run(lambda q=q: parse_fn(q, backend=oracle), nq)
        except HogQLParserShadowMismatch as e:
            _abort_on_shadow_mismatch(oracle, e)
        except Exception as e:
            print(f"{row_label:<30} {len(q):>6} {'ERROR':>12} {'-':>14} {'-':>12}  ({oracle}: {e})")
            continue
        try:
            cand_us = run(lambda q=q: parse_fn(q, backend=candidate), nq)
        except HogQLParserShadowMismatch as e:
            _abort_on_shadow_mismatch(candidate, e)
        except Exception as e:
            print(f"{row_label:<30} {len(q):>6} {oracle_us:>12.3f} {'(skip)':>14} {'-':>12}  ({candidate}: {e})")
            continue
        ratio = oracle_us / cand_us if cand_us > 0 else float("nan")
        print(f"{row_label:<30} {len(q):>6} {oracle_us:>12.3f} {cand_us:>14.3f} {ratio:>11.1f}x")
        oracle_total += oracle_us
        cand_total += cand_us
        comparable += 1

    print("-" * 78)
    if comparable:
        # The time columns ARE arithmetic means of per-row times.
        # The ratio column is the ratio of those means
        # (equivalently `sum(oracle) / sum(cand)`), which weights each
        # row by absolute time spent — the right metric for an
        # "overall speedup" reading. Note this is NOT the arithmetic
        # mean of per-row ratios; on a corpus with vastly different
        # absolute times, that mean would over-weight cheap rows.
        overall = oracle_total / cand_total if cand_total > 0 else float("nan")
        print(
            f"{'mean (per-call µs)':<30} {'':>6} {oracle_total / comparable:>12.3f} "
            f"{cand_total / comparable:>14.3f} {overall:>11.1f}x  "
            f"(ratio sum-weighted; {comparable}/{len(queries)} comparable)"
        )
    return comparable


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
            "Backend under test (no default). The Python backend is an "
            "ANTLR-generated visitor and is several orders of magnitude "
            "slower than cpp on most queries — the bench would take tens "
            "of minutes per row — so this script intentionally has no "
            "default. Set CANDIDATE_BACKEND or pass --candidate to any "
            "other backend available in your environment."
        ),
    )
    parser.add_argument(
        "--n",
        type=int,
        default=DEFAULT_N,
        help=(
            f"Iterations per row (default: {DEFAULT_N}). Lower it for a quick "
            f"sanity check during grinding, e.g. --n 50. Per-query ceilings in "
            f"N_PER_QUERY still apply as min(ceiling, --n)."
        ),
    )
    args = parser.parse_args()
    if args.n < 1:
        print("ERROR: --n must be at least 1")
        return 2
    if not args.candidate:
        print(
            "ERROR: --candidate is required (no default). The Python "
            "backend is too slow to be a useful bench target; pass any "
            "other backend available in your environment."
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
    comparable += bench("parse_expr", parse_expr, EXPR_QUERIES, args.n, args.oracle, args.candidate)
    comparable += bench("parse_select", parse_select, SELECT_QUERIES, args.n, args.oracle, args.candidate)
    if comparable == 0:
        print(
            f"\nERROR: zero comparable rows — candidate {args.candidate!r} "
            f"failed every query. Backend is reachable (probe passed) but "
            f"can't parse any of the corpus; this is a regression, not a "
            f"config issue."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
