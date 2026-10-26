"""The query that judges the cost planner's estimates.

q-error is ``greatest(estimate / actual, actual / estimate)``: 1 is a perfect estimate and 10 is an order of
magnitude off in either direction. The planner's exit bar is a median below 3 and a p90 below 10 for events
scans. Rows without an estimate are excluded so the metric only judges queries the planner saw. A query that read
nothing counts as one row read, so an estimate of thousands over an empty range shows up as the miss it is
instead of dropping out. Failed queries
are excluded because their ``read_rows`` reflect where they stopped, not what they would have read. Only the
initial query counts: ClickHouse logs one row per shard subquery too, each repeating the parent's tags, and
they would otherwise multiply ``queries`` by the shard count.
Byte accuracy excludes missing byte estimates without excluding those queries from row accuracy.
The ``query_log`` table is team scoped like every HogQL table, so the report covers the calling team only.
"""


def cost_estimate_accuracy_hogql(days: int = 7) -> str:
    """HogQL over ``query_log`` grouping q-error by plan fingerprint for the last ``days`` days."""
    return f"""
SELECT
    plan_fingerprint,
    count() AS queries,
    quantile(0.5)(greatest(estimated_rows / greatest(read_rows, 1), greatest(read_rows, 1) / estimated_rows)) AS median_rows_q_error,
    quantile(0.9)(greatest(estimated_rows / greatest(read_rows, 1), greatest(read_rows, 1) / estimated_rows)) AS p90_rows_q_error,
    if(countIf(estimated_bytes > 0 AND read_bytes > 0) > 0,
        quantileIf(0.5)(
            greatest(estimated_bytes / nullIf(read_bytes, 0), read_bytes / nullIf(estimated_bytes, 0)),
            estimated_bytes > 0 AND read_bytes > 0),
        NULL) AS median_bytes_q_error,
    if(countIf(estimated_bytes > 0 AND read_bytes > 0) > 0,
        quantileIf(0.9)(
            greatest(estimated_bytes / nullIf(read_bytes, 0), read_bytes / nullIf(estimated_bytes, 0)),
            estimated_bytes > 0 AND read_bytes > 0),
        NULL) AS p90_bytes_q_error
FROM query_log
WHERE event_time >= now() - toIntervalDay({int(days)})
    AND status = 'QueryFinish'
    AND is_initial_query
    AND plan_fingerprint != ''
    AND estimated_rows > 0
GROUP BY plan_fingerprint
ORDER BY queries DESC
"""
