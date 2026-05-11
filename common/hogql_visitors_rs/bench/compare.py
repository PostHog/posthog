"""Compare Python and Rust HogQL feature extractors.

Run from repo root after `maturin develop --release` in this dir:
    python common/hogql_visitors_rs/bench/compare.py

Reports total ms for 5000 invocations across:
  - python: the existing Python visitor running on the AST
  - A: read Python AST in place via PyO3 (intern'd attrs + cached type ptrs)
  - B: full = convert Python -> Rust mirror + walk; convert and visit shown
       separately so the amortisation case is visible.

The PR description includes a separate "python (original)" column captured
on the same machine before AST classes had __slots__; that comparison
isolates the slots speedup.
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
    # Pathological: 361 AST nodes. Shape modelled on a complex insight query
    # — multi-CTE, deeply nested subqueries, wide SELECT + WHERE, IN clauses
    # with many values, UNION ALL branches, multiple JOINs.
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
              AND properties.$current_url NOT LIKE '%admin%' AND properties.$current_url NOT LIKE '%internal%'
              AND properties.$current_url NOT LIKE '%test%' AND properties.$current_url NOT LIKE '%staging%'
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
              AND (p.properties.email != '' OR p.properties.$initial_referring_domain IS NOT NULL
                   OR p.properties.$initial_utm_source IS NOT NULL OR p.properties.$initial_utm_campaign IS NOT NULL)
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
            UNION ALL
            SELECT toStartOfDay(timestamp) AS day_start, count() AS count, 0 AS signups, 0 AS purchases,
                   properties.$some_property AS breakdown_value, properties.$browser AS browser,
                   properties.$os AS os, properties.$device_type AS device, properties.$current_url AS url
            FROM events
            WHERE event = '$web_vitals' AND timestamp > now() - INTERVAL 7 DAY
            GROUP BY day_start, breakdown_value, browser, os, device, url
        )
        SELECT groupArray(day_start)[1] AS first_day,
               arraySum(arrayMap(x -> x, groupArray(count))) AS total_count,
               arraySum(groupArray(signups)) AS total_signups,
               arraySum(groupArray(purchases)) AS total_purchases,
               breakdown_value, browser, os, device, count(DISTINCT url) AS distinct_urls
        FROM combined
        WHERE count > 1 AND (signups > 0 OR purchases > 0 OR breakdown_value LIKE '%marketing%')
        GROUP BY breakdown_value, browser, os, device
        HAVING total_count > 10
        ORDER BY total_count DESC, total_signups DESC, breakdown_value ASC
        LIMIT 1000
    """,
}

N = 5000


def run() -> None:
    header = f"{'query':<24} {'python':>9} {'A':>7} {'B: full':>9} {'B: convert':>12} {'B: visit':>10}"
    print(header)
    print("-" * len(header))
    print(f"{'(total ms / ' + str(N) + ' calls)':<24}")
    print()

    for name, sql in QUERIES.items():
        parsed = parse_select(sql)
        mirror = hogql_visitors_rs.to_mirror(parsed)

        t_py = timeit.timeit(lambda: extract_python(parsed), number=N) * 1000
        t_a = timeit.timeit(lambda: hogql_visitors_rs.extract_features_py(parsed), number=N) * 1000
        t_b_full = timeit.timeit(lambda: hogql_visitors_rs.extract_features_via_mirror(parsed), number=N) * 1000
        t_b_visit = timeit.timeit(lambda: hogql_visitors_rs.extract_features_from_mirror(mirror), number=N) * 1000
        t_b_convert = t_b_full - t_b_visit

        print(f"{name:<24} {t_py:>9.2f} {t_a:>7.2f} {t_b_full:>9.2f} {t_b_convert:>12.2f} {t_b_visit:>10.2f}")


if __name__ == "__main__":
    run()
