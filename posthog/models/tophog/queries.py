from datetime import datetime

from posthog.clickhouse.client import sync_execute

TOPHOG_QUERY = """
WITH filtered AS (
    SELECT *
    FROM tophog
    WHERE timestamp >= %(date_from)s AND timestamp <= %(date_to)s
    {filters}
)
SELECT metric, type, key, total, obs, pipelines, lanes
FROM (
    SELECT
        *,
        ROW_NUMBER() OVER (PARTITION BY metric, type ORDER BY total DESC) AS rn
    FROM (
        SELECT
            metric,
            type,
            key,
            CASE type
                WHEN 'max' THEN max(value)
                WHEN 'avg' THEN sum(value * count) / sum(count)
                ELSE sum(value)
            END AS total,
            sum(count) AS obs,
            arraySort(groupUniqArray(pipeline)) AS pipelines,
            arraySort(groupUniqArray(lane)) AS lanes
        FROM filtered
        GROUP BY metric, type, key
    )
)
WHERE rn <= 10
ORDER BY metric, type, rn
"""

FILTER_OPTIONS_QUERY = """
SELECT DISTINCT pipeline, lane
FROM tophog
WHERE timestamp >= %(date_from)s AND timestamp <= %(date_to)s
ORDER BY pipeline, lane
"""


def query_tophog_metrics(
    date_from: datetime,
    date_to: datetime,
    pipeline: str | None = None,
    lane: str | None = None,
) -> list[dict]:
    filters: list[str] = []
    params: dict[str, object] = {"date_from": date_from, "date_to": date_to}

    if pipeline:
        filters.append("AND pipeline = %(pipeline)s")
        params["pipeline"] = pipeline
    if lane:
        filters.append("AND lane = %(lane)s")
        params["lane"] = lane

    query = TOPHOG_QUERY.format(filters=" ".join(filters))
    rows = sync_execute(query, params)

    return [
        {
            "metric": metric,
            "type": type_,
            "key": key,
            "total": total,
            "obs": obs,
            "pipelines": pipelines,
            "lanes": lanes,
        }
        for metric, type_, key, total, obs, pipelines, lanes in rows
    ]


def query_tophog_filter_options(
    date_from: datetime,
    date_to: datetime,
) -> tuple[list[str], list[str]]:
    params: dict[str, datetime] = {"date_from": date_from, "date_to": date_to}
    rows = sync_execute(FILTER_OPTIONS_QUERY, params)

    pipelines = sorted({row[0] for row in rows})
    lanes = sorted({row[1] for row in rows})
    return pipelines, lanes
