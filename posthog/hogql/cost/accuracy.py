"""The query that judges the cost planner's estimates.

q-error is ``greatest(estimate / actual, actual / estimate)``: 1 is a perfect estimate and 10 is an order of
magnitude off in either direction. The planner's exit bar is a median below 3 and a p90 below 10 for events
scans. Rows without an estimate are excluded so the metric only judges queries the planner saw. Failed queries
are excluded because their ``read_rows`` reflect where they stopped, not what they would have read. Only the
initial query counts: ClickHouse logs one row per shard subquery too, each repeating the parent's tags, and
they would otherwise multiply ``queries`` by the shard count.
"""


def cost_estimate_accuracy_hogql(days: int = 7) -> str:
    """HogQL over ``query_log`` grouping q-error by plan fingerprint for the last ``days`` days."""
    return f"""
SELECT
    plan_fingerprint,
    count() AS queries,
    quantile(0.5)(greatest(estimated_rows / read_rows, read_rows / estimated_rows)) AS median_rows_q_error,
    quantile(0.9)(greatest(estimated_rows / read_rows, read_rows / estimated_rows)) AS p90_rows_q_error,
    quantile(0.5)(greatest(estimated_bytes / read_bytes, read_bytes / estimated_bytes)) AS median_bytes_q_error,
    quantile(0.9)(greatest(estimated_bytes / read_bytes, read_bytes / estimated_bytes)) AS p90_bytes_q_error
FROM query_log
WHERE event_date >= today() - {int(days)}
    AND status = 'QueryFinish'
    AND is_initial_query
    AND plan_fingerprint != ''
    AND estimated_rows > 0
    AND read_rows > 0
    AND estimated_bytes > 0
    AND read_bytes > 0
GROUP BY plan_fingerprint
ORDER BY queries DESC
"""
