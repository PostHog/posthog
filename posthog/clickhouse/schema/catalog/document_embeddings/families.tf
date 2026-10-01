module "partitioned_sharded_posthog_document_embeddings_family" {
  source = "../../lib/table_family"

  name     = "distributed_posthog_document_embeddings"
  database = var.database
  columns  = local.sharded_posthog_document_embeddings_buffer_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["inserted_at"]
    partition_by = "toMonday(timestamp)"
    order_by     = "(team_id, toDate(timestamp), product, document_type, model_name, rendering, cityHash64(document_id))"
    ttl          = var.ttl ? "timestamp + toIntervalMonth(3)" : null
    settings     = "index_granularity = 512, ttl_only_drop_parts = 1"
    indexes = [
      { name = "kafka_timestamp_minmax_partitioned_sharded_posthog_document_embeddings", expression = "_timestamp", type = "minmax", granularity = 3 },
    ]
  }
  sharding_key = "cityHash64(document_id)"
  deployment = merge({
    cluster = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["partitioned_sharded_posthog_document_embeddings", "distributed_posthog_document_embeddings", "writable_posthog_document_embeddings"], name) }
  })
  names = { storage = "partitioned_sharded_posthog_document_embeddings", write = "writable_posthog_document_embeddings" }
}

module "sharded_posthog_document_embeddings_buffer_family" {
  source = "../../lib/table_family"

  name     = "posthog_document_embeddings_buffer"
  database = var.database
  columns  = local.sharded_posthog_document_embeddings_buffer_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["inserted_at"]
    partition_by = "toDate(inserted_at)"
    order_by     = "(inserted_at, model_name, cityHash64(document_id))"
    ttl          = var.ttl ? "inserted_at + toIntervalDay(1)" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  routing = {
    read = false
  }
  sharding_key = "cityHash64(document_id)"
  kafka = {
    topic          = "clickhouse_document_embeddings"
    consumer_group = "clickhouse_document_embeddings"
    arguments      = "settings"
    columns = [
      { name = "team_id", type = "Int64" },
      { name = "product", type = "LowCardinality(String)" },
      { name = "document_type", type = "LowCardinality(String)" },
      { name = "model_name", type = "LowCardinality(String)" },
      { name = "rendering", type = "LowCardinality(String)" },
      { name = "document_id", type = "String" },
      { name = "timestamp", type = "DateTime64(3, 'UTC')" },
      { name = "inserted_at", type = "DateTime64(3, 'UTC')" },
      { name = "content", type = "String" },
      { name = "metadata", type = "String" },
      { name = "embedding", type = "Array(Float64)" },
    ]
    settings = {}
  }
  mv_select = <<-SQL
team_id,
    product,
    document_type,
    model_name,
    rendering,
    document_id,
    timestamp,
    _timestamp AS inserted_at,
    coalesce(content, '') AS content,
    coalesce(metadata, '{}') AS metadata,
    embedding,
    _timestamp,
    _offset,
    _partition
  SQL
  deployment = merge({
    cluster          = "posthog"
    kafka_collection = "msk_cluster"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_posthog_document_embeddings_buffer", "writable_posthog_document_embeddings_buffer", "posthog_document_embeddings_kafka_to_buffer_mv", "kafka_posthog_document_embeddings"], name) }
  })
  names = { mv = "posthog_document_embeddings_kafka_to_buffer_mv", kafka = "kafka_posthog_document_embeddings" }
}

module "sharded_posthog_document_embeddings_text_embedding_3_large_3072_family" {
  source = "../../lib/table_family"

  name     = "distributed_posthog_document_embeddings_text_embedding_3_large_3072"
  database = var.database
  columns  = local.sharded_posthog_document_embeddings_text_embedding_3_large_3072_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["inserted_at"]
    partition_by = "toMonday(timestamp)"
    order_by     = "(team_id, toDate(timestamp), product, document_type, rendering, cityHash64(document_id))"
    ttl          = var.ttl ? "timestamp + toIntervalMonth(3)" : null
    settings     = "index_granularity = 512, ttl_only_drop_parts = 1"
    indexes = [
      { name = "kafka_timestamp_minmax_sharded_posthog_document_embeddings_text_embedding_3_large_3072", expression = "_timestamp", type = "minmax", granularity = 3 },
      { name = "embedding_idx_l2", expression = "embedding", type = "vector_similarity('hnsw', 'L2Distance', 3072)", granularity = 100000000 },
      { name = "embedding_idx_cosine", expression = "embedding", type = "vector_similarity('hnsw', 'cosineDistance', 3072)", granularity = 100000000 },
    ]
    constraints = [
      { name = "embedding_dimension_check", check = "length(embedding) = 3072" },
    ]
  }
  sharding_key = "cityHash64(document_id)"
  deployment = merge({
    cluster = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_posthog_document_embeddings_text_embedding_3_large_3072", "distributed_posthog_document_embeddings_text_embedding_3_large_3072", "writable_posthog_document_embeddings_text_embedding_3_large_3072"], name) }
  })
  names = { storage = "sharded_posthog_document_embeddings_text_embedding_3_large_3072", write = "writable_posthog_document_embeddings_text_embedding_3_large_3072" }
}

module "sharded_posthog_document_embeddings_text_embedding_3_small_1536_family" {
  source = "../../lib/table_family"

  name     = "distributed_posthog_document_embeddings_text_embedding_3_small_1536"
  database = var.database
  columns  = local.sharded_posthog_document_embeddings_text_embedding_3_large_3072_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["inserted_at"]
    partition_by = "toMonday(timestamp)"
    order_by     = "(team_id, toDate(timestamp), product, document_type, rendering, cityHash64(document_id))"
    ttl          = var.ttl ? "timestamp + toIntervalMonth(3)" : null
    settings     = "index_granularity = 512, ttl_only_drop_parts = 1"
    indexes = [
      { name = "kafka_timestamp_minmax_sharded_posthog_document_embeddings_text_embedding_3_small_1536", expression = "_timestamp", type = "minmax", granularity = 3 },
      { name = "embedding_idx_l2", expression = "embedding", type = "vector_similarity('hnsw', 'L2Distance', 1536)", granularity = 100000000 },
      { name = "embedding_idx_cosine", expression = "embedding", type = "vector_similarity('hnsw', 'cosineDistance', 1536)", granularity = 100000000 },
    ]
    constraints = [
      { name = "embedding_dimension_check", check = "length(embedding) = 1536" },
    ]
  }
  sharding_key = "cityHash64(document_id)"
  deployment = merge({
    cluster = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_posthog_document_embeddings_text_embedding_3_small_1536", "distributed_posthog_document_embeddings_text_embedding_3_small_1536", "writable_posthog_document_embeddings_text_embedding_3_small_1536"], name) }
  })
  names = { storage = "sharded_posthog_document_embeddings_text_embedding_3_small_1536", write = "writable_posthog_document_embeddings_text_embedding_3_small_1536" }
}
