"""Compare Python, PyO3-direct, and PyO3-mirror feature extractors.

Run from repo root after `maturin develop --release` in this dir:
    python common/hogql_visitors_rs/bench/compare.py
"""

# ruff: noqa: T201, E402, B023, I001

import os
import django
import timeit

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

from posthog.hogql.feature_extractor import extract_hogql_features as extract_python
from posthog.hogql.parser import parse_select

import hogql_visitors_rs


QUERIES = {
    "tiny": "SELECT 1",
    "events_simple": "SELECT count() FROM events WHERE event = '$exception'",
    "events_in_clause": "SELECT count() FROM events WHERE event IN ('$ai_generation', '$ai_span', '$ai_trace')",
    "join_persons": "SELECT * FROM events AS e JOIN persons AS p ON p.id = e.person_id WHERE e.event = '$ai_generation'",
    "subquery_with_filters": (
        "SELECT day_start, sum(c) FROM ("
        "  SELECT count() AS c, toStartOfDay(timestamp) AS day_start, properties.foo AS f"
        "  FROM events WHERE event = '$pageview' AND timestamp > now() - INTERVAL 30 DAY"
        "  GROUP BY day_start, f HAVING c > 10"
        ") GROUP BY day_start ORDER BY day_start LIMIT 50"
    ),
    "trends_like_breakdown": (
        "SELECT groupArray(date)[1], arrayMap(x -> sum(x), counts), breakdown_value FROM ("
        "  SELECT day_start, sum(count) OVER (PARTITION BY breakdown_value ORDER BY day_start) AS counts,"
        "         breakdown_value FROM ("
        "    SELECT count(DISTINCT person_id) AS count, toStartOfDay(timestamp) AS day_start,"
        "           properties.$some_property AS breakdown_value FROM events"
        "    WHERE event = 'sign up' AND timestamp > now() - INTERVAL 7 DAY"
        "    GROUP BY day_start, breakdown_value"
        "  ) GROUP BY day_start, breakdown_value, counts ORDER BY day_start"
        ") GROUP BY breakdown_value LIMIT 50"
    ),
}

ITERATIONS = 5000


def run() -> None:
    print(f"{'query':<28} {'py µs':>10} {'rs-py µs':>10} {'rs-mirror µs':>14} {'rs-mirror×N=5':>15}")
    print("-" * 80)
    for name, sql in QUERIES.items():
        parsed = parse_select(sql)

        t_py = timeit.timeit(lambda: extract_python(parsed), number=ITERATIONS) / ITERATIONS * 1e6
        t_rs_py = (
            timeit.timeit(lambda: hogql_visitors_rs.extract_features_py(parsed), number=ITERATIONS) / ITERATIONS * 1e6
        )
        t_rs_mirror = (
            timeit.timeit(lambda: hogql_visitors_rs.extract_features_via_mirror(parsed), number=ITERATIONS)
            / ITERATIONS
            * 1e6
        )

        # Stand-in for "5 different visitors over the same converted AST" —
        # see README for the architecture this points toward.
        def five() -> None:
            for _ in range(5):
                hogql_visitors_rs.extract_features_via_mirror(parsed)

        t_rs_mirror5 = timeit.timeit(five, number=ITERATIONS // 5) / (ITERATIONS // 5) * 1e6

        print(f"{name:<28} {t_py:>10.2f} {t_rs_py:>10.2f} {t_rs_mirror:>14.2f} {t_rs_mirror5:>15.2f}")


if __name__ == "__main__":
    run()
