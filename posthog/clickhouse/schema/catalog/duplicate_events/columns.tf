# Column lists that more than one object uses.

locals {
  duplicate_events_columns = [
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "event", type = "String" },
    { name = "source_uuid", type = "UUID" },
    { name = "duplicate_uuid", type = "UUID" },
    { name = "similarity_score", type = "Float64" },
    { name = "dedup_type", type = "LowCardinality(String)" },
    { name = "is_confirmed", type = "UInt8" },
    { name = "reason", type = "Nullable(String)" },
    { name = "version", type = "String" },
    { name = "different_property_count", type = "UInt32" },
    { name = "properties_similarity", type = "Float64" },
    { name = "source_message", type = "String" },
    { name = "duplicate_message", type = "String" },
    { name = "distinct_fields", type = "Array(Tuple(field_name String, original_value String, new_value String))" },
    { name = "inserted_at", type = "DateTime64(3, 'UTC')" },
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ]
}
