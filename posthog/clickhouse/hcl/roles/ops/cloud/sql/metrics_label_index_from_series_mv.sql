SELECT
  team_id,
  metric_name,
  tupleElement(label_pair, 1) AS label_name,
  tupleElement(label_pair, 2) AS label_value,
  id
FROM
  posthog.metrics_series ARRAY JOIN JSONExtractKeysAndValues(labels_json, 'String') AS label_pair
