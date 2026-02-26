# Error Tracking Ingestion Pipeline

## Overview

This proposal outlines the migration of the standard error tracking event processing from Cymbal's Kafka consumer to a Node.js ingestion pipeline. The goal is to leverage shared ingestion infrastructure (most of what we need already exists) while keeping the error-tracking-specific logic (stack trace resolution, fingerprinting, issue linking) contained to Cymbal's HTTP API.

## Current Architecture

Currently, Cymbal consumes directly from kafka, parsing, filtering, enriching, and processing events before dispatching to clickhouse via kafka.

```text
Capture API
    │
    ▼
Capture Service (Rust)
    │
    ├──► exceptions_ingestion ──────────────────► Cymbal Kafka Consumer (Rust)
    │    (DataType::ExceptionMain)                ├── Billing limits
    │                                             ├── Team resolution
    │                                             ├── Person properties
    │                                             ├── GeoIP enrichment
    │                                             ├── Group type mapping
    │                                             ├── Exception processing
    │                                             └── Emit to clickhouse_events_json
    │
    └──► events_plugin_ingestion ──► Analytics Pipeline (Node.js)
         (all other events)
```

**Problems:**

- Cymbal duplicates a lot generic ingestion logic (team resolution, person properties, etc.) that we've already standardized in other ingestion pipelines.
- No shared infrastructure between analytics and error tracking pipelines, duplicating operational burden.
- Changes to ingestion logic requires updates in two places (Node.js and Rust)

## Proposed Architecture

We instead propose lifting the non-exception related event processing into a node pipline, calling out to Cymbal for the team specific processing. Fortunately, most of this logic already exists and is used across our other ingestion pipelines.

```text
Capture API
    │
    ▼
Capture Service (Rust)
    │
    ├──► exceptions_ingestion ──► Error Tracking Pipeline (Node.js) ◄── NEW
    │                             ├── Parse headers & message         [reuse]
    │                             ├── Apply event restrictions        [reuse]
    │                             ├── Resolve team                    [reuse]
    │                             ├── Person properties (read-only)   [in progress]
    │                             ├── GeoIP enrichment                [new - wrap existing]
    │                             ├── Group type mapping              [new - wrap existing]
    │                             ├── Call Cymbal HTTP API            [new]
    │                             └── Emit to clickhouse_events_json  [reuse]
    │                                          │
    │                                          ▼
    │                             Cymbal HTTP API `/process` (Rust)
    │                             └── Exception processing only
    │                                 ├── Stack trace resolution
    │                                 ├── Fingerprinting
    │                                 ├── Issue linking
    │                                 └── Alerting
    │
    └──► events_plugin_ingestion ──► Analytics Pipeline (Node.js)
         (unchanged)
```

**Benefits:**

- Shared ingestion infrastructure, logic, and monitoring (team resolution, person properties, etc.)
- Single source of truth for generic ingestion logic
- Cymbal focuses on error-tracking-specific processing, providing a clean line of separation
- Consistent patterns across analytics, session replay, and error tracking pipelines

## Component Assessment

From my attempt to understand everything that Cymbal currently does (with much help from Claude), I wanted to break down what all already exists, what exists but will need to be adapted, and what will have to be net new to make this migration happen.

### Reuse As-Is

| Component | Location | Notes |
|-----------|----------|-------|
| Pipeline Framework | `src/ingestion/pipelines/` | Builders, batch handling, result types |
| Parse Headers | `src/ingestion/event-preprocessing/parse-headers.ts` | Extract token, timestamps |
| Apply Event Restrictions | `src/ingestion/event-preprocessing/apply-event-restrictions.ts` | Billing limits, drop/overflow |
| Parse Kafka Message | `src/ingestion/event-preprocessing/parse-kafka-message.ts` | Raw capture format parsing |
| Resolve Team | `src/ingestion/event-preprocessing/resolve-team.ts` | Team lookup with caching |
| TeamService | `src/session-replay/shared/teams/team-service.ts` | Team lookup service |
| Ingestion Warnings | `handleIngestionWarnings()` | Emit warnings to Kafka |
| Result Handling | `handleResults()` | DLQ routing |
| GeoIP Service | `src/cdp/services/geoip-service.ts` | MaxMind lookup |
| GroupTypeManager | `src/worker/ingestion/group-type-manager.ts` | Group type resolution |

### New Steps (Wrap Existing Services)

| Component | Description | Effort |
|-----------|-------------|--------|
| `createPersonPropertiesReadOnlyStep()` | Fetch person by distinct_id, attach to event. No updates/merges. | Small |
| `createGeoIPEnrichmentStep()` | Wrap `GeoIPService` as pipeline step | Small |
| `createGroupTypeMappingStep()` | Wrap `GroupTypeManager` as pipeline step | Small |

Note: No filtering step needed - the `exceptions_ingestion` topic only contains `$exception` events (routed by capture service).

### New Components

| Component | Description | Effort |
|-----------|-------------|--------|
| `ErrorTrackingIngestionConsumer` | Kafka consumer (based on `IngestionConsumer` pattern) | Medium |
| `createErrorTrackingPipeline()` | Wire up all steps using pipeline builders | Small |
| `createCymbalProcessingStep()` | HTTP client calling Cymbal `/process` endpoint | Medium |
| `CymbalClient` | HTTP client wrapper with retry/timeout handling | Small |

## Pipeline Structure

This is what the pipeline will look like at a high level - it won't be exactly this, we'll wrap some steps in TopHog, flesh out our overflow and DLQ behavior, etc. But the gist is -

```typescript
// Consumer reads from "exceptions_ingestion" topic (only contains $exception events)
const pipeline = newBatchPipelineBuilder<ErrorTrackingPipelineInput, ErrorTrackingPipelineContext>()
    .messageAware((b) => b
        .sequentially((b) => b
            // Parse and validate
            .pipe(createParseHeadersStep())
            .pipe(createApplyEventRestrictionsStep(eventIngestionRestrictionManager, {
                overflowEnabled,
                overflowTopic,
            }))
            .pipe(createParseKafkaMessageStep())
            .pipe(createResolveTeamStep(teamService))
        )
        .teamAware((b) => b
            .sequentially((b) => b
                // Enrich
                .pipe(createPersonPropertiesReadOnlyStep(personService))
                .pipe(createGeoIPEnrichmentStep(geoipService))
                .pipe(createGroupTypeMappingStep(groupTypeManager))
            )
            .gather()
            // Call Cymbal for error-specific processing
            .pipeBatch(createCymbalProcessingStep(cymbalClient))
        )
        .handleIngestionWarnings(ingestionWarningProducer)
    )
    .handleResults(pipelineConfig)
    .build()
```

## Cymbal HTTP API Contract

### Request

```text
POST /process
Content-Type: application/json

[
  {
    "uuid": "...",
    "event": "$exception",
    "team_id": 123,
    "timestamp": "2024-01-01T00:00:00Z",
    "properties": {
      "$exception_list": [...],
      // Person properties (pre-enriched)
      "$person_id": "...",
      "$person_properties": {...},
      // GeoIP properties (pre-enriched)
      "$geoip_city_name": "...",
      // Group properties (pre-enriched)
      "$group_0": "...",
      ...
    }
  }
]
```

### Response

The response array maintains 1:1 position correspondence with the request array. Each position contains either an enriched event or `null` for suppressed events:

```json
[
  {
    "uuid": "...",
    "event": "$exception",
    "team_id": 123,
    "timestamp": "2024-01-01T00:00:00Z",
    "properties": {
      // Original properties plus:
      "$exception_list": [...],           // Resolved stack traces
      "$exception_fingerprint": "...",
      "$exception_issue_id": "...",
      "$exception_types": [...],
      "$exception_messages": [...],
      ...
    }
  }
]
```

## File Structure

```text
src/ingestion/
├── error-tracking-consumer.ts            # Error tracking consumer (NEW)
└── error-tracking/
    ├── PROPOSAL.md                       # This document
    ├── index.ts                          # Public exports
    ├── error-tracking-pipeline.ts        # Pipeline composition
    ├── error-tracking-pipeline.test.ts
    ├── geoip-enrichment-step.ts
    ├── geoip-enrichment-step.test.ts
    ├── group-type-mapping-step.ts
    ├── group-type-mapping-step.test.ts
    ├── cymbal-processing-step.ts         # Pipeline step calling Cymbal API
    ├── cymbal-processing-step.test.ts
    └── cymbal/
        ├── client.ts                     # HTTP client
        ├── client.test.ts
        └── types.ts                      # Request/response types
```

## Rollout Plan

### Phase 1: Build & Test

The focus here is to quickly and iteratively build out a PoC. I don't think there's a good way to incrementally roll out changes to production, so I'll instead incrementally add steps / features, validate behavior in dev, and move on to the next.

- Scaffold consumer and pipeline
- Implement new steps
- Unit and integration tests
- Verify in local dev environment

### Phase 2: Shadow Mode

Once the PoC has been built, we should then roll it out in production so we can validate output compared to Cymbal, tune metrics / alerts, and observe behavior (especially around the HTTP interactions).

- Deploy to production reading same topic (`exceptions_ingestion`) as Cymbal
- Both consumers process events (different consumer groups)
- Log and compare outputs (don't emit to ClickHouse from Node.js)
- Fix any discrepancies

### Phase 3: Team-Based Rollout

We'll want to slowly phase traffic from Cymbal consumer to the new ingestion pipeline.

- Split traffic via feature flag
- Both read from `exceptions_ingestion`, each processes their assigned teams
- Gradually expand: 10% → 50% → 100% of teams
- Monitor latency, error rates, output correctness

### Phase 4: Deprecate Cymbal Consumer

And lastly, clean up the old code.

- Remove Cymbal's Kafka consumer code
- Cymbal becomes HTTP API only
- Clean up unused Cymbal pipeline steps (team resolution, person, geoip, etc.)

## Infrastructure changes / requirements

- New DLQ + overflow topics

## Metrics & Observability

- Standard event count, processing / step latency, and kafak latency metrics for ingestion pipelines.
- Cymbal call latency for separating out team concerns.
- TopHog metrics for detailed breakdowns

## Open Questions

1. **Cymbal API batching** - What's the optimal batch size for the HTTP call? Need to balance latency vs throughput.

2. **Overflow handling** - Should error tracking events participate in the same overflow mechanism as analytics?

3. **Ingestion warnings** - Do we want the new ingestion pipeline to handle them, and if so can Cymbal return what we need for them?

## References

- [Session Replay Pipeline](../session_replay/) - Similar pattern for session recording events
- [Analytics Pipeline](../analytics/) - Main event ingestion pipeline
- [Cymbal HTTP API](../../../../rust/cymbal/src/router/event.rs) - Existing HTTP endpoint
