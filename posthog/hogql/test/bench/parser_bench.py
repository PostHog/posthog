# ruff: noqa: T201, E402, I001
# CLI benchmark tool: print() is the report channel, and the imports
# are deferred until after `django.setup()` so the order is intentional.
"""Side-by-side parser performance benchmark — backend-agnostic.

Defaults to comparing `cpp-json` vs `python` (the two backends master
ships). Pass `--candidate <backend>` (or set `CANDIDATE_BACKEND=<...>`)
to swap in a feature-branch backend like `rust-json` /
`rust-backtrack-json`. The query corpus is the same one the diagnostic
PBT runner uses, so bench timings line up with the parity numbers.

Run from repo root:
    # Default: cpp-json vs python (works in master out of the box)
    PYTHONPATH=. flox activate -- python posthog/hogql/test/bench/parser_bench.py

    # Compare cpp against a hand-rolled rust port in a feature branch
    CANDIDATE_BACKEND=rust-backtrack-json PYTHONPATH=. python posthog/hogql/test/bench/parser_bench.py

Queries the candidate can't parse are flagged and the row is skipped.
For comparable queries the script reports per-call microseconds and a
`oracle/candidate` ratio.

This script is intentionally dependency-free beyond what's already in
the backend environment so it's safe to keep around as a quick perf
sanity check while the parser port grows.
"""

import argparse
import os
import sys
import timeit
from typing import Any

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

from posthog.hogql.parser import clear_parse_caches, parse_expr, parse_select

N_EXPR = 1_000
N_SELECT = 1_000

# Per-query iteration overrides for queries cpp parses too slowly for
# the default N. Total wall-clock per row should stay well under a
# minute; cpp can be ~250ms+ on `pathological_deep` so 1000 iterations
# would burn 4+ minutes before rust's row even starts.
N_PER_QUERY: dict[str, int] = {
    "pathological_deep": 100,
}

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
    # Worst-case backtracking probe — five BETWEENs in an array literal,
    # each body forces parse_between_body's slowest alt (greedy parse +
    # source-scan + bounded re-parse) by absorbing the separator AND
    # into a non-AND-rooted subtree (lambda body, AS-alias, named-arg,
    # ternary else, lambda body again). For a hand-rolled
    # backtracking parser this is the kind of construct that should
    # stress the speculation path the most; for ANTLR ALL(*) it's just
    # five linear-lookahead disambiguations. If this row's
    # oracle/candidate ratio is significantly worse than `between`,
    # speculation overhead is showing up.
    "nasty_backtrack": (
        "["
        "x1 BETWEEN lambda a : a AND b1, "
        "x2 BETWEEN col AS y2 AND c2, "
        "x3 BETWEEN p := 1 AND b3, "
        "x4 BETWEEN c1 ? c2 : c3 AND b4, "
        "x5 BETWEEN lambda e : e AND b5"
        "]"
    ),
    "mixed_and_or": (
        "(event = '$pageview' OR event = '$autocapture' OR event = '$identify') "
        "AND timestamp > now() AND properties.foo IN ('Chrome', 'Firefox', 'Safari') "
        "AND (properties.url LIKE '%admin%' OR properties.url LIKE '%dashboard%') "
        "AND NOT (properties.os = 'Linux' AND properties.device = 'Desktop')"
    ),
}

SELECT_QUERIES: dict[str, str] = {
    "tiny": "SELECT 1",
    "events_simple": "SELECT count() FROM events WHERE event = '$exception'",
    "events_in_clause": "SELECT count() FROM events WHERE event IN ('$ai_generation', '$ai_span', '$ai_trace')",
    "join_persons": (
        "SELECT e.event, e.timestamp, p.id FROM events AS e "
        "JOIN persons AS p ON p.id = e.person_id WHERE e.event = '$ai_generation'"
    ),
    "subquery_with_filters": (
        "SELECT day_start, sum(c) FROM ("
        "  SELECT count() AS c, toStartOfDay(timestamp) AS day_start, properties.foo AS f"
        "  FROM events WHERE event = '$pageview' AND timestamp > now() - INTERVAL 30 DAY"
        "  GROUP BY day_start, f HAVING c > 10"
        ") GROUP BY day_start ORDER BY day_start LIMIT 50"
    ),
    "trends_like_breakdown": (
        "SELECT groupArray(day_start)[1], arrayMap(x -> sum(x), counts), breakdown_value FROM ("
        "  SELECT day_start, sum(count) OVER (PARTITION BY breakdown_value ORDER BY day_start) AS counts,"
        "         breakdown_value FROM ("
        "    SELECT count(DISTINCT person_id) AS count, toStartOfDay(timestamp) AS day_start,"
        "           properties.$some_property AS breakdown_value FROM events"
        "    WHERE event = 'sign up' AND timestamp > now() - INTERVAL 7 DAY"
        "    GROUP BY day_start, breakdown_value"
        "  ) GROUP BY day_start, breakdown_value, counts ORDER BY day_start"
        ") GROUP BY breakdown_value LIMIT 50"
    ),
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


def run(parse_fn, q: str, n: int) -> float:
    """Per-call microseconds for `n` iterations of `parse_fn(q)`. Clears
    the cache before each invocation so we measure cold parse cost rather
    than the cache hit path."""

    def body() -> Any:
        clear_parse_caches()
        return parse_fn(q)

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
    print(f"\n{label}  (N={n} per row, oracle={oracle}, candidate={candidate})")
    print(f"{'query':<22} {'chars':>6} {'oracle(us)':>12} {'candidate(us)':>14} {'oracle/cand':>12}")
    print("-" * 70)

    oracle_total, cand_total, comparable = 0.0, 0.0, 0
    for name, q in queries.items():
        nq = N_PER_QUERY.get(name, n)
        try:
            oracle_us = run(lambda q=q: parse_fn(q, backend=oracle), q, nq)  # type: ignore[arg-type]
        except Exception as e:
            print(f"{name:<22} {len(q):>6} {'ERROR':>12} {'-':>14} {'-':>12}  ({oracle}: {e})")
            continue
        try:
            cand_us = run(lambda q=q: parse_fn(q, backend=candidate), q, nq)  # type: ignore[arg-type]
        except Exception:
            print(f"{name:<22} {len(q):>6} {oracle_us:>12.3f} {'(skip)':>14} {'-':>12}")
            continue
        ratio = oracle_us / cand_us if cand_us > 0 else float("nan")
        print(f"{name:<22} {len(q):>6} {oracle_us:>12.3f} {cand_us:>14.3f} {ratio:>11.1f}x")
        oracle_total += oracle_us
        cand_total += cand_us
        comparable += 1

    print("-" * 70)
    if comparable:
        overall = oracle_total / cand_total if cand_total > 0 else float("nan")
        print(
            f"{'mean':<22} {'':>6} {oracle_total / comparable:>12.3f} "
            f"{cand_total / comparable:>14.3f} {overall:>11.1f}x  ({comparable}/{len(queries)} comparable)"
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
            "slower than cpp/rust on most queries (the bench would take "
            "tens of minutes per row), so this script intentionally has "
            "no default. Set CANDIDATE_BACKEND or pass --candidate to a "
            "fast backend like `rust-json` / `rust-backtrack-json`."
        ),
    )
    args = parser.parse_args()
    if not args.candidate:
        print(
            "ERROR: --candidate is required (no default). The Python "
            "backend is too slow to be a useful bench target — pass a "
            "fast backend like `rust-json` or `rust-backtrack-json`."
        )
        return 2
    bench("parse_expr", parse_expr, EXPR_QUERIES, N_EXPR, args.oracle, args.candidate)
    bench("parse_select", parse_select, SELECT_QUERIES, N_SELECT, args.oracle, args.candidate)
    return 0


if __name__ == "__main__":
    sys.exit(main())
