/*
Trace Counts - Unique traces (distinct $ai_trace_id)

Counts the number of unique traces by counting distinct $ai_trace_id values
across all AI event types. A trace may contain multiple events (generations, spans, etc).

Produces metric: ai_trace_id_count

Example: If there are 10 events belonging to 3 unique trace_ids, this counts 3.
Compare with event_counts.sql which would count all 10 events individually.
*/

SELECT
    date(timestamp) as date,
    team_id,
    'ai_trace_id_count' as metric_name,
    toFloat64(count(DISTINCT JSONExtractString(properties, '$ai_trace_id'))) as metric_value
FROM events
WHERE event IN ({% for event_type in event_types %}'{{ event_type }}'{% if not loop.last %}, {% endif %}{% endfor %})
  AND timestamp >= toDateTime('{{ date_start }}', 'UTC')
  AND timestamp < toDateTime('{{ date_end }}', 'UTC')
  AND JSONExtractString(properties, '$ai_trace_id') != ''
GROUP BY date, team_id
