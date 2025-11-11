{% for event_type in event_types %}
{% set metric_name = event_type.lstrip('$') + '_count' %}
SELECT
    date(timestamp) as date,
    team_id,
    '{{ metric_name }}' as metric_name,
    toFloat64(count(*)) as metric_value
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
