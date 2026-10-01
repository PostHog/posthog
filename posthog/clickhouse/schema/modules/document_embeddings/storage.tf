# Tables that hold data, and the materialized views between them.

module "partitioned_sharded_posthog_document_embeddings" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "partitioned_sharded_posthog_document_embeddings")
  database     = var.database
  name         = "partitioned_sharded_posthog_document_embeddings"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/posthog.partitioned_sharded_posthog_document_embeddings${var.zk_path_suffix}', '{replica}', inserted_at)"
  partition_by = "toMonday(timestamp)"
  order_by     = "(team_id, toDate(timestamp), product, document_type, model_name, rendering, cityHash64(document_id))"
  ttl          = var.ttl ? "timestamp + toIntervalMonth(3)" : null
  settings     = "index_granularity = 512, ttl_only_drop_parts = 1"
  columns      = local.sharded_posthog_document_embeddings_buffer_columns
  indexes = [
    { name = "kafka_timestamp_minmax_partitioned_sharded_posthog_document_embeddings", expression = "_timestamp", type = "minmax", granularity = 3 },
  ]
  override = try(var.overrides["partitioned_sharded_posthog_document_embeddings"], {})
}

module "posthog_document_embeddings_text_embedding_3_large_3072_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(var.exclude, "posthog_document_embeddings_text_embedding_3_large_3072_mv")
  database = var.database
  name     = "posthog_document_embeddings_text_embedding_3_large_3072_mv"
  to_table = "${var.database}.writable_posthog_document_embeddings_text_embedding_3_large_3072"
  query    = <<-SQL
    SELECT
        team_id,
        product,
        document_type,
        rendering,
        document_id,
        timestamp,
        inserted_at,
        content,
        metadata,
        embedding,
        _timestamp,
        _offset,
        _partition
    FROM ${var.database}.sharded_posthog_document_embeddings_buffer
    WHERE model_name = 'text-embedding-3-large-3072'
  SQL
  override = try(var.overrides["posthog_document_embeddings_text_embedding_3_large_3072_mv"], {})

  depends_on = [
    module.sharded_posthog_document_embeddings_buffer,
    module.writable_posthog_document_embeddings_text_embedding_3_large_3072,
  ]
}

module "posthog_document_embeddings_text_embedding_3_small_1536_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(var.exclude, "posthog_document_embeddings_text_embedding_3_small_1536_mv")
  database = var.database
  name     = "posthog_document_embeddings_text_embedding_3_small_1536_mv"
  to_table = "${var.database}.writable_posthog_document_embeddings_text_embedding_3_small_1536"
  query    = <<-SQL
    SELECT
        team_id,
        product,
        document_type,
        rendering,
        document_id,
        timestamp,
        inserted_at,
        content,
        metadata,
        embedding,
        _timestamp,
        _offset,
        _partition
    FROM ${var.database}.sharded_posthog_document_embeddings_buffer
    WHERE model_name = 'text-embedding-3-small-1536'
  SQL
  override = try(var.overrides["posthog_document_embeddings_text_embedding_3_small_1536_mv"], {})

  depends_on = [
    module.sharded_posthog_document_embeddings_buffer,
    module.writable_posthog_document_embeddings_text_embedding_3_small_1536,
  ]
}

module "sharded_posthog_document_embeddings_buffer" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_posthog_document_embeddings_buffer")
  database     = var.database
  name         = "sharded_posthog_document_embeddings_buffer"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/posthog.sharded_posthog_document_embeddings_buffer${var.zk_path_suffix}', '{replica}', inserted_at)"
  partition_by = "toDate(inserted_at)"
  order_by     = "(inserted_at, model_name, cityHash64(document_id))"
  ttl          = var.ttl ? "inserted_at + toIntervalDay(1)" : null
  settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  columns      = local.sharded_posthog_document_embeddings_buffer_columns
  override     = try(var.overrides["sharded_posthog_document_embeddings_buffer"], {})
}

module "sharded_posthog_document_embeddings_text_embedding_3_large_3072" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_posthog_document_embeddings_text_embedding_3_large_3072")
  database     = var.database
  name         = "sharded_posthog_document_embeddings_text_embedding_3_large_3072"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/posthog.sharded_posthog_document_embeddings_text_embedding_3_large_3072${var.zk_path_suffix}', '{replica}', inserted_at)"
  partition_by = "toMonday(timestamp)"
  order_by     = "(team_id, toDate(timestamp), product, document_type, rendering, cityHash64(document_id))"
  ttl          = var.ttl ? "timestamp + toIntervalMonth(3)" : null
  settings     = "index_granularity = 512, ttl_only_drop_parts = 1"
  columns      = local.sharded_posthog_document_embeddings_text_embedding_3_large_3072_columns
  indexes = [
    { name = "kafka_timestamp_minmax_sharded_posthog_document_embeddings_text_embedding_3_large_3072", expression = "_timestamp", type = "minmax", granularity = 3 },
    { name = "embedding_idx_l2", expression = "embedding", type = "vector_similarity('hnsw', 'L2Distance', 3072)", granularity = 100000000 },
    { name = "embedding_idx_cosine", expression = "embedding", type = "vector_similarity('hnsw', 'cosineDistance', 3072)", granularity = 100000000 },
  ]
  constraints = [
    { name = "embedding_dimension_check", check = "length(embedding) = 3072" },
  ]
  override = try(var.overrides["sharded_posthog_document_embeddings_text_embedding_3_large_3072"], {})
}

module "sharded_posthog_document_embeddings_text_embedding_3_small_1536" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_posthog_document_embeddings_text_embedding_3_small_1536")
  database     = var.database
  name         = "sharded_posthog_document_embeddings_text_embedding_3_small_1536"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/posthog.sharded_posthog_document_embeddings_text_embedding_3_small_1536${var.zk_path_suffix}', '{replica}', inserted_at)"
  partition_by = "toMonday(timestamp)"
  order_by     = "(team_id, toDate(timestamp), product, document_type, rendering, cityHash64(document_id))"
  ttl          = var.ttl ? "timestamp + toIntervalMonth(3)" : null
  settings     = "index_granularity = 512, ttl_only_drop_parts = 1"
  columns      = local.sharded_posthog_document_embeddings_text_embedding_3_large_3072_columns
  indexes = [
    { name = "kafka_timestamp_minmax_sharded_posthog_document_embeddings_text_embedding_3_small_1536", expression = "_timestamp", type = "minmax", granularity = 3 },
    { name = "embedding_idx_l2", expression = "embedding", type = "vector_similarity('hnsw', 'L2Distance', 1536)", granularity = 100000000 },
    { name = "embedding_idx_cosine", expression = "embedding", type = "vector_similarity('hnsw', 'cosineDistance', 1536)", granularity = 100000000 },
  ]
  constraints = [
    { name = "embedding_dimension_check", check = "length(embedding) = 1536" },
  ]
  override = try(var.overrides["sharded_posthog_document_embeddings_text_embedding_3_small_1536"], {})
}
