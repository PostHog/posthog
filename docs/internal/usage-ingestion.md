# Usage ingestion

The Rust usage-ingestion service accepts billing records over gRPC, Kafka, or
both transports. Its [service README](../../rust/usage-ingestion/README.md)
documents local setup and every environment variable.

Analytics event ingestion selects its transport with `USAGE_INGESTION_MODE`:
`grpc` calls the service directly and `kafka` writes protobuf requests through
the standard ingestion output registry. Other Node.js usage reporters continue
to use gRPC.

Production Kafka mode requires the `usage_ingestion` and `usage_ingestion_dlq`
topics on the ingestion cluster. Deployment overrides belong in PostHog's
deployment charts; secret connection values belong in the secrets repository.
