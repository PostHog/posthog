/*
Event Error Rates - Percentage of events with errors by type

Calculates what percentage of events of each type had an error.
An event is considered errored if $ai_error is set or $ai_is_error is true.

Produces metrics: ai_generation_error_rate, ai_embedding_error_rate, etc.

Example: If 2 out of 10 generation events had errors, this reports 20.0%.
Compare with trace_error_rates.sql which reports % of traces with any error.
*/

SELECT
    date(timestamp) as date,
    team_id,
    concat(substring(event, 2), '_error_rate') as metric_name,
    round(
        countIf(
            (JSONExtractRaw(properties, '$ai_error') != '' AND JSONExtractRaw(properties, '$ai_error') != 'null')
            OR JSONExtractBool(properties, '$ai_is_error') = true
        ) * 100.0 / count(*),
        2
    ) as metric_value
FROM events
WHERE event IN ({% for event_type in event_types %}'{{ event_type }}'{% if not loop.last %}, {% endif %}{% endfor %})
  AND timestamp >= toDateTime('{{ date_start }}', 'UTC')
  AND timestamp < toDateTime('{{ date_end }}', 'UTC')
GROUP BY date, team_id, event
