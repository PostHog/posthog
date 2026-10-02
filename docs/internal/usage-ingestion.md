# Usage ingestion

The Rust usage-ingestion service accepts billing records over gRPC, Kafka, or
both transports. Its [service README](../../rust/usage-ingestion/README.md)
documents local setup and every environment variable.

Production Kafka mode requires the `usage_ingestion` and `usage_ingestion_dlq`
topics on the ingestion cluster. Deployment overrides belong in PostHog's
deployment charts; secret connection values belong in the secrets repository.
