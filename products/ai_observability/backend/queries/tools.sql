/*
-- Tool calls, results and unknown tools are extracted at ingestion time.
-- See: nodejs/src/ingestion/pipelines/ai/tools/
--
-- A tool's calls come from $ai_tools_called on the generation that made them. Its results come from
-- $ai_tool_results on the next generation, which received them, so a failure rate is failures over
-- results, not over calls. Each generation becomes one row per (tool, kind) item, so the table is
-- read once.
*/

SELECT
    tupleElement(item, 1) AS tool,
    countIf(tupleElement(item, 2) = 'call') AS total_calls,
    if(countIf(tupleElement(item, 2) = 'result') > 0, round(countIf(tupleElement(item, 2) = 'error') * 100 / countIf(tupleElement(item, 2) = 'result'), 1), NULL) AS failure_pct,
    countIf(tupleElement(item, 2) = 'error') AS failures,
    countIf(tupleElement(item, 2) = 'result') AS results,
    countIf(tupleElement(item, 2) = 'unknown') AS undefined_calls,
    argMaxIf(properties.$ai_tool_intent, timestamp, tupleElement(item, 2) = 'call' AND notEmpty(ifNull(properties.$ai_tool_intent, ''))) AS latest_intent,
    countDistinctIf(properties.$ai_trace_id, tupleElement(item, 2) = 'call' AND properties.$ai_trace_id != '') AS traces,
    uniqIf(distinct_id, tupleElement(item, 2) = 'call') AS users,
    countDistinctIf(properties.$ai_session_id, tupleElement(item, 2) = 'call' AND properties.$ai_session_id != '') AS sessions,
    uniqIf(toDate(timestamp), tupleElement(item, 2) = 'call') AS days_seen,
    if(total_calls > 0, round(countIf(tupleElement(item, 2) = 'call' AND position(properties.$ai_tools_called, ',') = 0) * 100 / total_calls), NULL) AS single_pct,
    min(timestamp) AS first_seen,
    max(timestamp) AS last_seen
FROM events
ARRAY JOIN arrayConcat(
    arrayMap(x -> tuple(x, 'call'), splitByChar(',', ifNull(properties.$ai_tools_called, ''))),
    arrayMap(x -> tuple(x, 'result'), splitByChar(',', ifNull(properties.$ai_tool_results, ''))),
    arrayMap(x -> tuple(x, 'error'), splitByChar(',', ifNull(properties.$ai_tool_errors, ''))),
    arrayMap(x -> tuple(x, 'unknown'), splitByChar(',', ifNull(properties.$ai_tools_unknown, '')))
) AS item
WHERE event = '$ai_generation'
    AND (properties.$ai_tools_called != '' OR properties.$ai_tool_results != '')
    AND tupleElement(item, 1) != ''
    AND {filters}
GROUP BY tool
ORDER BY __ORDER_BY__ __ORDER_DIRECTION__
LIMIT 100
