# The Kafka named collections ClickHouse server config defines (posthog-cloud-infra
# ansible/roles/clickhouse/templates/config.d/named_collections.xml, mirrored for the
# local stack in docker/clickhouse/config.d/). Every kafka_* table names one as its
# engine's `collection`, and the resolver rejects a reference it cannot bind, so they
# are declared here once. `external` says the definition — brokers, credentials —
# lives in that server config and never in the schema.

named_collection "msk_cluster" {
  external = true
}

named_collection "warpstream_calculated_events" {
  external = true
}

named_collection "warpstream_cyclotron" {
  external = true
}

named_collection "warpstream_ingestion" {
  external = true
}

named_collection "warpstream_logs" {
  external = true
}

named_collection "warpstream_metrics" {
  external = true
}

named_collection "warpstream_replay" {
  external = true
}

named_collection "warpstream_shared" {
  external = true
}

named_collection "warpstream_traces" {
  external = true
}
