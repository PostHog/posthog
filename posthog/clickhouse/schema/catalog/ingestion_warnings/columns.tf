# Column lists that more than one object uses.

locals {
  kafka_ingestion_warnings_columns = [
    { name = "team_id", type = "Int64" },
    { name = "source", type = "LowCardinality(String)" },
    { name = "type", type = "String" },
    { name = "details", type = "String", codec = "ZSTD(3)" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
  ]

  sharded_ingestion_warnings_columns = concat(local.kafka_ingestion_warnings_columns, [
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ])

  ingestion_warnings_v2_columns = [
    { name = "team_id", type = "Int64" },
    { name = "source", type = "LowCardinality(String)" },
    { name = "type", type = "LowCardinality(String)" },
    { name = "details", type = "String" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "category", type = "LowCardinality(String)", default_expression = "coalesce(nullIf(JSONExtractString(details, 'category'), ''), 'unknown')" },
    { name = "severity", type = "LowCardinality(String)", default_expression = "coalesce(nullIf(JSONExtractString(details, 'severity'), ''), 'warning')" },
    { name = "pipeline_step", type = "LowCardinality(String)", default_expression = "coalesce(nullIf(JSONExtractString(details, 'pipelineStep'), ''), 'unknown')" },
    { name = "event_uuid", type = "Nullable(UUID)", default_expression = "toUUIDOrNull(JSONExtractString(details, 'eventUuid'))" },
    { name = "distinct_id", type = "Nullable(String)", default_expression = "nullIf(JSONExtractString(details, 'distinctId'), '')" },
    { name = "group_key", type = "Nullable(String)", default_expression = "nullIf(JSONExtractString(details, 'groupKey'), '')" },
    { name = "person_id", type = "Nullable(UUID)", default_expression = "toUUIDOrNull(JSONExtractString(details, 'personId'))" },
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ]
}
