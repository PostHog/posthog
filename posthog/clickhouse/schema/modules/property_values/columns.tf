# Column lists that more than one object uses.

locals {
  property_values_columns = [
    { name = "team_id", type = "Int64", codec = "DoubleDelta, ZSTD(1)" },
    { name = "property_type", type = "LowCardinality(String)" },
    { name = "property_key", type = "LowCardinality(String)" },
    { name = "property_value", type = "String" },
    { name = "property_count", type = "SimpleAggregateFunction(sum, UInt64)" },
    { name = "last_seen", type = "SimpleAggregateFunction(max, DateTime)", default_expression = "now()" },
  ]
}
