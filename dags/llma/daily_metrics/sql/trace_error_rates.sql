/*
Trace Error Rates - Percentage of traces with any error

Calculates what percentage of unique traces had at least one error event.
A trace is considered errored if ANY event within it has $ai_error set or $ai_is_error is true.

Produces metric: ai_trace_id_has_error_rate

Example: If 2 out of 8 unique traces had any error event, this reports 25.0%.
Compare with error_rates.sql which reports % of individual events with errors.

Note: A single erroring event in a trace makes the entire trace count as errored.
*/

SELECT
    date(timestamp) as date,
    team_id,
    'ai_trace_id_has_error_rate' as metric_name,
    round(
        countDistinctIf(
            JSONExtractString(properties, '$ai_trace_id'),
            (JSONExtractRaw(properties, '$ai_error') != '' AND JSONExtractRaw(properties, '$ai_error') != 'null')
            OR JSONExtractBool(properties, '$ai_is_error') = true
        ) * 100.0 / count(DISTINCT JSONExtractString(properties, '$ai_trace_id')),
        2
    ) as metric_value
FROM events
WHERE event IN ({% for event_type in event_types %}'{{ event_type }}'{% if not loop.last %}, {% endif %}{% endfor %})
  AND timestamp >= toDateTime('{{ date_start }}', 'UTC')
  AND timestamp < toDateTime('{{ date_end }}', 'UTC')
  AND JSONExtractString(properties, '$ai_trace_id') != ''
GROUP BY date, team_id
