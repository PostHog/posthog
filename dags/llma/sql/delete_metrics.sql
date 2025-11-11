ALTER TABLE llma_metrics_daily
DELETE WHERE date >= '{{ date_start }}' AND date < '{{ date_end }}'
