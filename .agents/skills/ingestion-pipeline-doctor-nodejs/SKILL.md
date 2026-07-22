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
      → concurrentlyPerGroup(token:distinctId) for per-entity processing
      → gather()
      → pipeChunk() for chunk operations
      → handleIngestionWarnings()
    → handleResults()
  → handleSideEffects()
  → build()
```

See `nodejs/src/ingestion/pipelines/analytics/joined-ingestion-pipeline.ts` for the real implementation.

## Key file locations

| What              | Where                                                                   |
| ----------------- | ----------------------------------------------------------------------- |
| Step type         | `nodejs/src/ingestion/framework/steps.ts`                               |
| Result types      | `nodejs/src/ingestion/framework/results.ts`                             |
| Doc-test chapters | `nodejs/src/ingestion/framework/docs/*.test.ts`                         |
| Joined pipeline   | `nodejs/src/ingestion/pipelines/analytics/joined-ingestion-pipeline.ts` |
| Doctor agents     | `.claude/agents/ingestion/`                                             |
| Test helpers      | `nodejs/src/ingestion/framework/docs/helpers.ts`                        |

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

**Composition**: `messageAware` wraps the pipeline. `handleResults` inside `messageAware`. `handleSideEffects` after. `concurrentlyPerGroup` for per-entity work. `gather` before chunk steps.

**Batching lifecycle hooks** (`BatchingPipeline` beforeBatch/afterBatch): enrich-only. Hooks may enrich elements and batch context but must return exactly the elements they received — a count change is a broken invariant and `feed()` throws. Filtering belongs in sub-pipeline steps that return `drop()`. An empty `feed()` is a no-op (no hooks, no capacity). Details: `nodejs/src/ingestion/framework/docs/14-batching.test.ts`.

**Testing**: Step tests call factory directly. Use `consumeAll()`/`collectChunks()` helpers. Fake timers for async. Type guards for result assertions. No `any`.

## Running all doctors

Ask Claude to "run all pipeline doctors on my recent changes" to get a comprehensive review across all 4 concern areas.
