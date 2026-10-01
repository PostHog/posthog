# Column lists that more than one object uses.

locals {
  kafka_tophog_columns = [
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "metric", type = "LowCardinality(String)" },
    { name = "type", type = "LowCardinality(String)" },
    { name = "key", type = "Map(LowCardinality(String), String)" },
    { name = "value", type = "Float64" },
    { name = "count", type = "UInt64" },
    { name = "pipeline", type = "LowCardinality(String)" },
    { name = "lane", type = "LowCardinality(String)" },
    { name = "labels", type = "Map(LowCardinality(String), String)" },
  ]

  sharded_tophog_columns = [
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "metric", type = "LowCardinality(String)" },
    { name = "type", type = "LowCardinality(String)", default_expression = "'sum'" },
    { name = "key", type = "Map(LowCardinality(String), String)" },
    { name = "value", type = "Float64" },
    { name = "count", type = "UInt64", default_expression = "0" },
    { name = "pipeline", type = "LowCardinality(String)" },
    { name = "lane", type = "LowCardinality(String)" },
    { name = "labels", type = "Map(LowCardinality(String), String)" },
  ]
}
