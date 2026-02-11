from collections import defaultdict

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.shortcuts import render

from posthog.clickhouse.client import sync_execute

TOPHOG_QUERY = """
SELECT metric, key, total, pipeline, lane
FROM (
    SELECT
        metric,
        key,
        sum(value) AS total,
        any(pipeline) AS pipeline,
        any(lane) AS lane,
        ROW_NUMBER() OVER (PARTITION BY metric ORDER BY sum(value) DESC) AS rn
    FROM tophog
    WHERE timestamp >= now() - INTERVAL 5 MINUTE
    {filters}
    GROUP BY metric, key
)
WHERE rn <= 10
ORDER BY metric, rn
"""

FILTER_OPTIONS_QUERY = """
SELECT DISTINCT pipeline, lane
FROM tophog
WHERE timestamp >= now() - INTERVAL 1 HOUR
ORDER BY pipeline, lane
"""


def tophog_dashboard_view(request):
    if not request.user.is_staff:
        raise PermissionDenied

    filter_options = sync_execute(FILTER_OPTIONS_QUERY)
    pipelines = sorted({row[0] for row in filter_options})
    lanes = sorted({row[1] for row in filter_options})

    selected_pipeline = request.GET.get("pipeline", "")
    selected_lane = request.GET.get("lane", "")

    filters = []
    params: dict[str, str] = {}
    if selected_pipeline:
        filters.append("AND pipeline = %(pipeline)s")
        params["pipeline"] = selected_pipeline
    if selected_lane:
        filters.append("AND lane = %(lane)s")
        params["lane"] = selected_lane

    query = TOPHOG_QUERY.format(filters=" ".join(filters))
    rows = sync_execute(query, params)

    metrics: dict[str, list[dict]] = defaultdict(list)
    for metric, key, total, pipeline, lane in rows:
        metrics[metric].append(
            {
                "key": key,
                "value": total,
                "pipeline": pipeline,
                "lane": lane,
            }
        )

    context = {
        **admin.site.each_context(request),
        "title": "TopHog Dashboard",
        "metrics": dict(metrics),
        "pipelines": pipelines,
        "lanes": lanes,
        "selected_pipeline": selected_pipeline,
        "selected_lane": selected_lane,
    }
    return render(request, "admin/tophog.html", context)
