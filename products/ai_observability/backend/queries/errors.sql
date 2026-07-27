/*
-- Error normalization is done at ingestion time.
-- The $ai_error_normalized property contains the pre-computed normalized error message.
-- See: nodejs/src/ingestion/ai/errors/normalize-error.ts
--
-- This query uses HogQL property syntax (properties.$prop) to leverage materialized columns
-- for $ai_trace_id, $ai_session_id, and $ai_is_error for better performance.
*/

SELECT
    properties.$ai_error_normalized as error,
    countDistinctIf(properties.$ai_trace_id, properties.$ai_trace_id != '') as traces,
    countIf(event = '$ai_generation') as generations,
    countIf(event = '$ai_span') as spans,
    countIf(event = '$ai_embedding') as embeddings,
    countDistinctIf(properties.$ai_session_id, properties.$ai_session_id != '') as sessions,
    uniq(distinct_id) as users,
    uniq(toDate(timestamp)) as days_seen,
    min(timestamp) as first_seen,
    max(timestamp) as last_seen
FROM events
WHERE event IN ('$ai_generation', '$ai_span', '$ai_trace', '$ai_embedding')
    AND properties.$ai_is_error = 'true'
    AND {filters}
GROUP BY error
ORDER BY __ORDER_BY__ __ORDER_DIRECTION__
LIMIT 100
