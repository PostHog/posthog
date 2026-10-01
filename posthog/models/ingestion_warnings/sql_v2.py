# Ingestion warnings v2: additive, structured warnings table living on the aux cluster
# (single shard, replicated). It reads the same `clickhouse_ingestion_warnings` Kafka topic
# as v1 through a dedicated consumer group, so it receives the full stream independently
# without touching the legacy path.
#
# Structured dimensions (category, severity, pipeline_step) and entity ids are DEFAULT
# expressions parsing the `details` JSON, so agents/MCP can filter without re-parsing JSON
# at query time. DEFAULT rather than MATERIALIZED: the MV (or producers) can later set the
# columns explicitly without a schema change, which MATERIALIZED would forbid.

TABLE_NAME = "ingestion_warnings_v2"
DISTRIBUTED_TABLE_NAME = f"{TABLE_NAME}_distributed"
