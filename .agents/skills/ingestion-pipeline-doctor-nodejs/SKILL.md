---
name: ingestion-pipeline-doctor-nodejs
description: >
  Ingestion pipeline architecture overview and convention reference.
  Use when you need a quick orientation to the pipeline framework
  or want to know which doctor agent to use for a specific concern.
---

# Pipeline Doctor

Quick reference for PostHog's ingestion pipeline framework and its convention-checking agents.

## Architecture overview

The ingestion pipeline processes events through a typed, composable step chain:

```text
Kafka message
  → messageAware()
    → parse headers/body
    → sequentially() for preprocessing
    → filterMap() to enrich context (e.g., team lookup)
    → teamAware()
      → groupBy(token:distinctId)
        → concurrently() for per-entity processing
      → gather()
      → pipeBatch() for batch operations
      → handleIngestionWarnings()
    → handleResults()
  → handleSideEffects()
  → build()
```

See `nodejs/src/ingestion/analytics/joined-ingestion-pipeline.ts` for the real implementation.

## Key file locations

| What              | Where                                                         |
| ----------------- | ------------------------------------------------------------- |
| Step type         | `nodejs/src/ingestion/pipelines/steps.ts`                     |
| Result types      | `nodejs/src/ingestion/pipelines/results.ts`                   |
| Doc-test chapters | `nodejs/src/ingestion/pipelines/docs/*.test.ts`               |
| Joined pipeline   | `nodejs/src/ingestion/analytics/joined-ingestion-pipeline.ts` |
| Doctor agents     | `nodejs/src/ingestion/doctor/agents/`                         |
| Test helpers      | `nodejs/src/ingestion/pipelines/docs/helpers.ts`              |

## Which agent to use

| Concern         | Agent                         | When to use                                               |
| --------------- | ----------------------------- | --------------------------------------------------------- |
| Step structure  | `pipeline-step-doctor`        | Factory pattern, type extension, config injection, naming |
| Result handling | `pipeline-result-doctor`      | ok/dlq/drop/redirect, side effects, ingestion warnings    |
| Composition     | `pipeline-composition-doctor` | Builder chain, concurrency, grouping, branching, retries  |
| Testing         | `pipeline-testing-doctor`     | Test helpers, assertions, fake timers, doc-test style     |

## Quick convention reference

**Steps**: Factory function returning a named inner function. Generic `<T extends Input>` for type extension. No `any`. Config via closure.

**Results**: Use `ok()`, `dlq()`, `drop()`, `redirect()` constructors. Side effects as promises in `ok(value, [effects])`. Warnings as third parameter.

**Composition**: `messageAware` wraps the pipeline. `handleResults` inside `messageAware`. `handleSideEffects` after. `groupBy` + `concurrently` for per-entity work. `gather` before batch steps.

**Testing**: Step tests call factory directly. Use `consumeAll()`/`collectBatches()` helpers. Fake timers for async. Type guards for result assertions. No `any`.

## Running all doctors

Ask Claude to "run all pipeline doctors on my recent changes" to get a comprehensive review across all 4 concern areas.
