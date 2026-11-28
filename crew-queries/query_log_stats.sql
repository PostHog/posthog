-- Read back the benchmark runs by their log_comment. Run per region after run_bench.sh.
SELECT
    log_comment,
    query_duration_ms,
    read_rows,
    formatReadableSize(read_bytes) AS read_bytes,
    formatReadableSize(memory_usage) AS peak_memory,
    memory_usage AS peak_memory_bytes,
    result_rows,
    exception_code,
    event_time,
    hostName() AS host
FROM clusterAllReplicas(posthog, system, query_log)
WHERE event_date >= today() - 1
    AND type IN ('QueryFinish', 'ExceptionWhileProcessing')
    AND is_initial_query
    AND log_comment LIKE 'slbench|REGION|%'
ORDER BY log_comment, event_time
LIMIT 1000
