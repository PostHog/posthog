moved {
  from = module.partitioned_sharded_posthog_document_embeddings
  to   = module.partitioned_sharded_posthog_document_embeddings_family.module.storage
}

moved {
  from = module.distributed_posthog_document_embeddings
  to   = module.partitioned_sharded_posthog_document_embeddings_family.module.read
}

moved {
  from = module.writable_posthog_document_embeddings
  to   = module.partitioned_sharded_posthog_document_embeddings_family.module.write
}

moved {
  from = module.sharded_posthog_document_embeddings_buffer
  to   = module.sharded_posthog_document_embeddings_buffer_family.module.storage
}

moved {
  from = module.writable_posthog_document_embeddings_buffer
  to   = module.sharded_posthog_document_embeddings_buffer_family.module.write
}

moved {
  from = module.posthog_document_embeddings_kafka_to_buffer_mv
  to   = module.sharded_posthog_document_embeddings_buffer_family.module.mv
}

moved {
  from = module.kafka_posthog_document_embeddings
  to   = module.sharded_posthog_document_embeddings_buffer_family.module.kafka
}

moved {
  from = module.sharded_posthog_document_embeddings_text_embedding_3_large_3072
  to   = module.sharded_posthog_document_embeddings_text_embedding_3_large_3072_family.module.storage
}

moved {
  from = module.distributed_posthog_document_embeddings_text_embedding_3_large_3072
  to   = module.sharded_posthog_document_embeddings_text_embedding_3_large_3072_family.module.read
}

moved {
  from = module.writable_posthog_document_embeddings_text_embedding_3_large_3072
  to   = module.sharded_posthog_document_embeddings_text_embedding_3_large_3072_family.module.write
}

moved {
  from = module.sharded_posthog_document_embeddings_text_embedding_3_small_1536
  to   = module.sharded_posthog_document_embeddings_text_embedding_3_small_1536_family.module.storage
}

moved {
  from = module.distributed_posthog_document_embeddings_text_embedding_3_small_1536
  to   = module.sharded_posthog_document_embeddings_text_embedding_3_small_1536_family.module.read
}

moved {
  from = module.writable_posthog_document_embeddings_text_embedding_3_small_1536
  to   = module.sharded_posthog_document_embeddings_text_embedding_3_small_1536_family.module.write
}
