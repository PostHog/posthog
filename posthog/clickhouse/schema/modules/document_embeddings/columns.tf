# Column lists that more than one object uses.

locals {
  sharded_posthog_document_embeddings_text_embedding_3_large_3072_columns = [
    { name = "team_id", type = "Int64" },
    { name = "product", type = "LowCardinality(String)" },
    { name = "document_type", type = "LowCardinality(String)" },
    { name = "rendering", type = "LowCardinality(String)" },
    { name = "document_id", type = "String" },
    { name = "timestamp", type = "DateTime64(3, 'UTC')" },
    { name = "inserted_at", type = "DateTime64(3, 'UTC')" },
    { name = "content", type = "String", default_expression = "''" },
    { name = "metadata", type = "String", default_expression = "'{}'" },
    { name = "embedding", type = "Array(Float64)" },
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ]

  sharded_posthog_document_embeddings_buffer_columns = [
    { name = "team_id", type = "Int64" },
    { name = "product", type = "LowCardinality(String)" },
    { name = "document_type", type = "LowCardinality(String)" },
    { name = "model_name", type = "LowCardinality(String)" },
    { name = "rendering", type = "LowCardinality(String)" },
    { name = "document_id", type = "String" },
    { name = "timestamp", type = "DateTime64(3, 'UTC')" },
    { name = "inserted_at", type = "DateTime64(3, 'UTC')" },
    { name = "content", type = "String", default_expression = "''" },
    { name = "metadata", type = "String", default_expression = "'{}'" },
    { name = "embedding", type = "Array(Float64)" },
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ]
}
