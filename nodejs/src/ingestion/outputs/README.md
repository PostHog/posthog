# Ingestion Outputs

Ingestion pipelines need to produce messages to Kafka — events, heatmaps, ingestion warnings, etc. Each of these destinations is an **output**. An output has a topic and a producer, both configurable at deploy time without code changes.

## Why

Previously, pipelines received raw `KafkaProducerWrapper` instances and hardcoded topic names. This made it impossible to route outputs to different Kafka clusters (e.g. events to MSK, heatmaps to WarpStream) without code changes. It also meant the producer was accessible everywhere, with no control over what gets produced where.

## What this module provides

**A named output abstraction.** Pipeline steps produce messages to an output by name (e.g. `'events'`). The output resolves to a topic and producer at startup. Steps never see the producer directly.

**Configurable producer routing.** Each output has a default producer, overridable via env var. Producers are defined with their own env var → rdkafka config mapping, validated with zod at startup.

**Configurable topics.** Each output has a default topic, also overridable via env var.

**Health checks.** `IngestionOutputs` can verify broker connectivity and topic existence at startup, and provide ongoing health status for Kubernetes readiness probes.

## Concepts

A **producer** is a Kafka connection configured via env vars. Each producer has a name (e.g. `'DEFAULT'`) and a mapping from env var names to rdkafka config keys. The `KafkaProducerRegistry` creates and caches producers by name — you define the producers and their env var mappings, the registry handles creation and lifecycle.

An **output** is a named destination (e.g. `'events'`, `'heatmaps'`). Each output points to a producer and a topic. Both are configurable via env vars so you can re-route outputs between clusters or topics at deploy time without touching code.

`IngestionOutputs` is the interface pipeline steps use to produce messages. It maps each output name to its resolved producer and topic, exposing `produce()` and `queueMessages()` methods that route messages to the right Kafka cluster and topic without the caller needing to know the details.

The **resolver** (`resolveIngestionOutputs`) is the glue. It takes a registry and a set of output definitions, looks up env var overrides, creates the producers through the registry, and returns an `IngestionOutputs`. This happens once at startup.

## Conventions

Pipeline steps receive `IngestionOutputs<O>` as a dependency and produce messages through it using `outputs.produce(output, message)` or `outputs.queueMessages(output, messages)`. Steps should never access Kafka producers directly.

Each pipeline defines its output and producer config in its own directory (e.g. `analytics/config/`). Shared output constants that appear in multiple pipelines go in `common/outputs.ts`. The server resolves the definitions into an `IngestionOutputs` at startup and passes it down.

## How to extend

To add a new output, add the output constant to the appropriate `outputs.ts` file (`common/` if shared, or the pipeline's own) and add an entry to the pipeline's output definitions.

To add a new producer, add it to the pipeline's `producers.ts` with its env var mapping. The registry creates it on first use.

## File layout

```text
ingestion/outputs/              — generic infrastructure (pipeline-agnostic)
ingestion/common/outputs.ts     — shared output constants (e.g. EVENTS_OUTPUT)
ingestion/analytics/outputs.ts  — analytics-specific output constants
ingestion/analytics/config/     — analytics pipeline definitions (outputs + producers)
```
