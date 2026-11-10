# @posthog/ingestion-common

Ingestion's contract with the other Node services, cut at what they import: the pipeline framework (with ingestion's metrics and warnings), the personhog client and its generated stubs, and the person and group repositories. CDP depends on the repositories, logs on the framework; `@posthog/ingestion` depends on all of it. It depends on `@posthog/node-common` and on nothing else in the repository.

The ingestion warning registry (`src/ingestion-warning-types.ts`) is the source of truth for the Rust `WarningType` enum: `pnpm gen:ingestion-warning-types` writes `ingestion/rust/ingestion_warnings/warning_types.generated.json`, and a test fails when the two drift.
