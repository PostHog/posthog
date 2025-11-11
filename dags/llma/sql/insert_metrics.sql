INSERT INTO llma_metrics_daily (date, team_id, metric_name, metric_value)
{% for event_type in event_types %}
SELECT
    date(timestamp) as date,
    team_id,
    '{{ event_type.lstrip('$') }}_count' as metric_name,
    count(distinct uuid) as metric_value
FROM events
WHERE event = '{{ event_type }}'
  AND timestamp >= toDateTime('{{ date_start }}', 'UTC')
  AND timestamp < toDateTime('{{ date_end }}', 'UTC')
GROUP BY date, team_id
HAVING metric_value > 0
{% if not loop.last %}
UNION ALL
{% endif %}
{% endfor %}
