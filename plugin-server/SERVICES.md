# Plugin Server Services

This document classifies the plugin server modes/services by their primary function.

> **Last updated:** 2025-12-22

## Ingestion Services

| Mode                                    | Capability                                | Consumer Class               | Hub Type                      |
| --------------------------------------- | ----------------------------------------- | ---------------------------- | ----------------------------- |
| `ingestion-v2`                          | `ingestionV2`                             | `IngestionConsumer`          | `IngestionConsumerHub`        |
| `recordings-blob-ingestion-v2`          | `sessionRecordingBlobIngestionV2`         | `SessionRecordingIngesterV2` | `SessionRecordingIngesterHub` |
| `recordings-blob-ingestion-v2-overflow` | `sessionRecordingBlobIngestionV2Overflow` | `SessionRecordingIngesterV2` | `SessionRecordingIngesterHub` |

## CDP Services

| Mode                           | Capability                     | Consumer Class                      | Hub Type                             |
| ------------------------------ | ------------------------------ | ----------------------------------- | ------------------------------------ |
| `cdp-processed-events`         | `cdpProcessedEvents`           | `CdpEventsConsumer`                 | `CdpEventsConsumerHub`               |
| `cdp-person-updates`           | `cdpPersonUpdates`             | `CdpPersonUpdatesConsumer`          | `CdpConsumerBaseHub`                 |
| `cdp-data-warehouse-events`    | `cdpDataWarehouseEvents`       | `CdpDatawarehouseEventsConsumer`    | `CdpDatawarehouseEventsConsumerHub`  |
| `cdp-internal-events`          | `cdpInternalEvents`            | `CdpInternalEventsConsumer`         | `CdpConsumerBaseHub`                 |
| `cdp-legacy-on-event`          | `cdpLegacyOnEvent`             | `CdpLegacyEventsConsumer`           | `CdpLegacyEventsConsumerHub`         |
| `cdp-cyclotron-worker`         | `cdpCyclotronWorker`           | `CdpCyclotronWorker`                | `CdpCyclotronWorkerHub`              |
| `cdp-cyclotron-worker-hogflow` | `cdpCyclotronWorkerHogFlow`    | `CdpCyclotronWorkerHogFlow`         | `CdpCyclotronWorkerHogFlowHub`       |
| `cdp-cyclotron-worker-delay`   | `cdpCyclotronWorkerDelay`      | `CdpCyclotronDelayConsumer`         | `CdpCyclotronDelayConsumerHub`       |
| `cdp-precalculated-filters`    | `cdpPrecalculatedFilters`      | `CdpPrecalculatedFiltersConsumer`   | `CdpPrecalculatedFiltersConsumerHub` |
| `cdp-cohort-membership`        | `cdpCohortMembership`          | `CdpCohortMembershipConsumer`       | `CdpCohortMembershipConsumerHub`     |
| `cdp-api`                      | `cdpApi`                       | `CdpApi`                            | `CdpApiHub`                          |
| `async-webhooks`               | `processAsyncWebhooksHandlers` | `startAsyncWebhooksHandlerConsumer` | `AsyncWebhooksHandlerHub`            |
| `evaluation-scheduler`         | `evaluationScheduler`          | `startEvaluationScheduler`          | `EvaluationSchedulerHub`             |

## Logs Services

| Mode             | Capability      | Consumer Class          | Hub Type                   |
| ---------------- | --------------- | ----------------------- | -------------------------- |
| `ingestion-logs` | `logsIngestion` | `LogsIngestionConsumer` | `LogsIngestionConsumerHub` |

## Combined Modes (Local Development)

| Mode             | Capabilities    | Description                                                      |
| ---------------- | --------------- | ---------------------------------------------------------------- |
| `local-cdp`      | Ingestion + CDP | Runs `ingestionV2` plus all CDP services                         |
| `null` (default) | All             | Runs all services including ingestion, CDP, recordings, and logs |

When `PLUGIN_SERVER_MODE` is not set (null), the server runs in combined mode with all capabilities enabled for local development.

## Summary

| Category  | Count | Services                                                              |
| --------- | ----- | --------------------------------------------------------------------- |
| Ingestion | 3     | Event ingestion, session recordings (main + overflow)                 |
| CDP       | 13    | Event triggers, cyclotron workers, cohorts, API, webhooks, evaluation |
| Logs      | 1     | Logs ingestion                                                        |

## Hub Type Hierarchy

Each service declares exactly what configuration it needs via a narrowed Hub type. This makes dependencies explicit and allows for better testing and configuration management.

### Generic Base Classes

Base consumer classes use TypeScript generics to allow child classes to extend the hub type without needing `declare` overrides:

```typescript
// Base class is generic over its hub type
export abstract class CdpConsumerBase<THub extends CdpConsumerBaseHub = CdpConsumerBaseHub> {
    constructor(protected hub: THub) { ... }
}

// Child class extends with a more specific hub type
export type CdpEventsConsumerHub = CdpConsumerBaseHub & Pick<Hub, 'teamManager' | 'SITE_URL'>

export class CdpEventsConsumer<THub extends CdpEventsConsumerHub = CdpEventsConsumerHub>
    extends CdpConsumerBase<THub> {
    // hub is automatically typed as THub
}

// Grandchild class can further extend
export type CdpLegacyEventsConsumerHub = CdpEventsConsumerHub & Pick<Hub, 'CDP_LEGACY_EVENT_*'>

export class CdpLegacyEventsConsumer extends CdpEventsConsumer<CdpLegacyEventsConsumerHub> {
    // hub is typed as CdpLegacyEventsConsumerHub
}
```

### Shared Configuration Types

Common configuration subsets are defined as reusable types:

```typescript
// Shared fetch configuration used by multiple executors
export type CdpFetchConfig = Pick<Hub, 'CDP_FETCH_RETRIES' | 'CDP_FETCH_BACKOFF_BASE_MS' | 'CDP_FETCH_BACKOFF_MAX_MS'>

// Composed hub types use intersection
export type HogExecutorServiceHub = CdpFetchConfig &
  HogInputsServiceHub &
  EmailServiceHub &
  Pick<Hub, 'CDP_WATCHER_HOG_COST_TIMING_UPPER_MS' | 'CDP_GOOGLE_ADWORDS_DEVELOPER_TOKEN'>
```

See [CONFIG.md](./CONFIG.md) for detailed configuration requirements per service.
