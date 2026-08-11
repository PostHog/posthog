# Cloud storage form of ai_events: the WarpStream envs store events in the
# table itself (the local/data stacks read through a Distributed shim onto
# sharded_ai_events).
database "posthog" {
  patch_table "ai_events" {
    order_by     = ["team_id", "trace_id", "timestamp"]
    partition_by = "toYYYYMM(drop_date)"
    ttl          = "drop_date"
    settings = {
      index_granularity   = "8192"
      ttl_only_drop_parts = "1"
    }
    index "idx_trace_id" {
      expr        = "trace_id"
      type        = "bloom_filter(0.001)"
      granularity = 1
    }
    index "idx_session_id" {
      expr        = "session_id"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_parent_id" {
      expr        = "parent_id"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_span_id" {
      expr        = "span_id"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_prompt_name" {
      expr        = "prompt_name"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_model" {
      expr        = "model"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_experiment_id" {
      expr        = "experiment_id"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_event" {
      expr        = "event"
      type        = "set(20)"
      granularity = 1
    }
    index "idx_is_error" {
      expr        = "is_error"
      type        = "set(2)"
      granularity = 1
    }
    index "idx_provider" {
      expr        = "provider"
      type        = "set(50)"
      granularity = 1
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/ai_events/tables/{shard}/posthog.ai_events"
      replica_name = "{replica}"
    }
  }
}
