"""Benchmark WebStatsTableQueryRunner result equality across branches.

Usage:
    DJANGO_SETTINGS_MODULE=posthog.settings python .notes/web_stats_bench.py > /tmp/results-<label>.json
"""
import json
import sys

import django

django.setup()

from posthog.clickhouse.query_tagging import tag_queries  # noqa: E402
from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner  # noqa: E402
from posthog.models import Team  # noqa: E402
from posthog.schema import (  # noqa: E402
    CustomEventConversionGoal,
    DateRange,
    WebStatsBreakdown,
    WebStatsTableQuery,
)


CASES = [
    # (label, kwargs)
    ("page_default", {"breakdownBy": WebStatsBreakdown.PAGE}),
    ("page_bounce_rate", {"breakdownBy": WebStatsBreakdown.PAGE, "includeBounceRate": True}),
    ("page_avg_time", {"breakdownBy": WebStatsBreakdown.PAGE, "includeAvgTimeOnPage": True}),
    (
        "page_conversion_goal",
        {
            "breakdownBy": WebStatsBreakdown.PAGE,
            "conversionGoal": CustomEventConversionGoal(customEventName="signed_up"),
        },
    ),
    ("initial_page_bounce", {"breakdownBy": WebStatsBreakdown.INITIAL_PAGE, "includeBounceRate": True}),
    ("frustration_metrics", {"breakdownBy": WebStatsBreakdown.FRUSTRATION_METRICS}),
    ("browser", {"breakdownBy": WebStatsBreakdown.BROWSER}),
    ("country", {"breakdownBy": WebStatsBreakdown.COUNTRY}),
    ("initial_utm_source", {"breakdownBy": WebStatsBreakdown.INITIAL_UTM_SOURCE}),
]


def run() -> dict[str, object]:
    tag_queries(product="web_analytics", feature="query")
    team = Team.objects.get(pk=1)
    out: dict[str, object] = {}
    for label, kwargs in CASES:
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="-30d"),
            properties=[],
            limit=10,
            **kwargs,
        )
        runner = WebStatsTableQueryRunner(team=team, query=query)
        try:
            response = runner.calculate()
            out[label] = {
                "results": response.results,
                "columns": getattr(response, "columns", None),
                "types": getattr(response, "types", None),
            }
        except Exception as exc:
            out[label] = {"error": f"{type(exc).__name__}: {exc}"}
    return out


if __name__ == "__main__":
    print(json.dumps(run(), default=str, indent=2, sort_keys=True))
