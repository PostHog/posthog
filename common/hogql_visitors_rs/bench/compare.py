"""Compare Python, PyO3-direct, and PyO3-mirror feature extractors.

Run from repo root after `maturin develop --release` in this dir:
    python common/hogql_visitors_rs/bench/compare.py

Reports total ms for 5000 invocations across four variants so the
conversion overhead of strategy B is visible alongside the visitor cost.
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

N = 5000


def run() -> None:
    header = (
        f"{'query':<24} "
        f"{'python (ms)':>12} "
        f"{'A: PyO3 (ms)':>14} "
        f"{'B: full (ms)':>14} "
        f"{'B: visit only (ms)':>20} "
        f"{'B: convert (ms)':>16}"
    )
    print(header)
    print("-" * len(header))
    print(f"{'(total for ' + str(N) + ' calls)':<24}")
    print()

    for name, sql in QUERIES.items():
        parsed = parse_select(sql)
        mirror = hogql_visitors_rs.to_mirror(parsed)  # pre-converted, reused across iters

        t_py = timeit.timeit(lambda: extract_python(parsed), number=N) * 1000
        t_a = timeit.timeit(lambda: hogql_visitors_rs.extract_features_py(parsed), number=N) * 1000
        t_b_full = timeit.timeit(lambda: hogql_visitors_rs.extract_features_via_mirror(parsed), number=N) * 1000
        t_b_visit = timeit.timeit(lambda: hogql_visitors_rs.extract_features_from_mirror(mirror), number=N) * 1000
        t_b_convert = t_b_full - t_b_visit  # implied — the leftover after subtracting the visit-only cost

        print(f"{name:<24} {t_py:>12.2f} {t_a:>14.2f} {t_b_full:>14.2f} {t_b_visit:>20.2f} {t_b_convert:>16.2f}")


if __name__ == "__main__":
    run()
