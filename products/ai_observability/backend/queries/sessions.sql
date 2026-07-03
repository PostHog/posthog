/*
-- Session aggregation query.
-- Groups events by trace_id first (inner query), then by session_id (outer query).
--
-- All AI event types can carry $ai_session_id, but cost/latency data lives
-- on $ai_generation and $ai_embedding events.
-- A single-level GROUP BY session_id would filter out all child events.
--
-- Cost is summed only from $ai_generation and $ai_embedding events (per data model).
-- Latency prefers the trace-level $ai_latency, falling back to summing children.
*/

SELECT
    session_id,
    count() as traces,
    sum(spans) as spans,
    sum(generations) as generations,
    sum(embeddings) as embeddings,
    sum(errors) as errors,
    argMin(trace_distinct_id, trace_first_seen) as distinct_id,
    -- Distinct tool names called across the whole session. $ai_tools_called is a
    -- comma-separated string per generation (and can repeat within one), so we
    -- concat all of them, split, and dedupe - same shape as traces_query_runner.
    arrayFilter(
        x -> x != '',
        arrayDistinct(splitByChar(',', arrayStringConcat(groupArray(trace_tools), ',')))
    ) as tools,
    round(sum(trace_cost), 4) as total_cost,
    round(sum(trace_latency), 2) as total_latency,
    min(trace_first_seen) as first_seen,
    max(last_seen) as last_seen
FROM (
    SELECT
        anyIf(properties.$ai_session_id, isNotNull(properties.$ai_session_id) AND properties.$ai_session_id != '') as session_id,
        countIf(event = '$ai_span') as spans,
        countIf(event = '$ai_generation') as generations,
        countIf(event = '$ai_embedding') as embeddings,
        countIf(properties.$ai_is_error = 'true') as errors,
        argMin(distinct_id, timestamp) as trace_distinct_id,
        -- groupUniqArrayIf instead of groupArrayIf to dedup and keep it small
        arrayStringConcat(
            groupUniqArrayIf(
                toString(properties.$ai_tools_called),
                event = '$ai_generation'
                AND isNotNull(properties.$ai_tools_called)
                AND toString(properties.$ai_tools_called) != ''
            ),
            ','
        ) as trace_tools,
        sumIf(toFloat(properties.$ai_total_cost_usd), event IN ('$ai_generation', '$ai_embedding')) as trace_cost,
        coalesce(
            anyIf(toFloat(properties.$ai_latency), event = '$ai_trace' AND isNotNull(properties.$ai_latency)),
            sumIf(toFloat(properties.$ai_latency), event IN ('$ai_generation', '$ai_embedding', '$ai_span'))
        ) as trace_latency,
        min(timestamp) as trace_first_seen,
        max(timestamp) as last_seen
    FROM events
    WHERE event IN ('$ai_generation', '$ai_span', '$ai_embedding', '$ai_trace')
        AND isNotNull(properties.$ai_trace_id)
        AND properties.$ai_trace_id != ''
        AND {filters}
    GROUP BY properties.$ai_trace_id
    HAVING session_id != '' AND isNotNull(session_id)
)
GROUP BY session_id
ORDER BY __ORDER_BY__ __ORDER_DIRECTION__
LIMIT __LIMIT__
OFFSET __OFFSET__
