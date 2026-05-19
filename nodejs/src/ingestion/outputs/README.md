# Ingestion Outputs

Ingestion pipelines need to produce messages to Kafka — events, heatmaps, ingestion warnings, etc. Each of these destinations is an **output**. An output has one or more targets (each a topic + producer pair), all configurable at deploy time without code changes.

## Why

Previously, pipelines received raw `KafkaProducerWrapper` instances and hardcoded topic names. This made it impossible to route outputs to different Kafka clusters (e.g. events to MSK, heatmaps to WarpStream) without code changes. It also meant the producer was accessible everywhere, with no control over what gets produced where.

## What this module provides

**A named output abstraction.** Pipeline steps produce messages to an output by name (e.g. `'events'`). The output resolves to one or more targets at startup. Steps never see the producer directly.

**Configurable producer routing.** Each output has a default producer, overridable via the config object (backed by env vars). Producers are defined with their own config key → rdkafka config mapping, validated with zod at startup.

**Configurable topics.** Each output has a default topic, also overridable via the config object.

**Compile-time config validation.** Both the producer registry builder and the outputs builder enforce at compile time that the server config contains all required keys. Missing keys are caught by the type checker, not at runtime.

**Dual writes.** Each output can optionally have a secondary target (topic + producer on a different broker). When secondary env vars are set, every `produce()` and `queueMessages()` call fans out to both targets in parallel. This enables writing to two Kafka clusters simultaneously without any pipeline step changes.

**Per-target metrics.** All produce metrics (`ingestion_outputs_latency_seconds`, `ingestion_outputs_errors_total`, `ingestion_outputs_message_value_bytes`, `ingestion_outputs_batch_size`) include `producer_name` and `topic` labels, so primary and secondary writes are independently observable in Grafana.

**Health checks.** `IngestionOutputs` can verify broker connectivity and topic existence at startup, and provide ongoing health status for Kubernetes readiness probes. Health checks cover all targets, including secondary ones.

## Concepts

A **producer** is a Kafka connection configured via the server config object. Each producer has a name (e.g. `'DEFAULT'`) and a mapping from config key names to rdkafka config keys. `KafkaProducerRegistryBuilder` creates all producers at startup, returning a typed `KafkaProducerRegistry<P>` where `P` is the union of registered producer names. The producer name is set on the `KafkaProducerWrapper` instance and used in metrics labels.

A **target** is a single Kafka destination: a topic, a producer, and the producer's name. An output contains one or more targets.

An **output** is a named destination (e.g. `'events'`, `'heatmaps'`). Each output has a primary target and optionally a secondary target for dual writes. Both are configurable via env vars so you can re-route outputs between clusters or topics at deploy time without touching code.

`IngestionOutputs` is the interface pipeline steps use to produce messages. It maps each output name to its resolved targets, exposing `produce()` and `queueMessages()` methods that route messages to the right Kafka cluster(s) and topic(s) without the caller needing to know the details.

`IngestionOutputsBuilder` registers outputs with their config key pairs, then `build(registry, config)` resolves them — verifying at compile time that all config keys exist and producer values match the registry's type.

## Dual writes

Each output can have a secondary target with configurable routing via mode and percentage.

### Configuration

Set the secondary target, mode, and percentage for an output:

```bash
INGESTION_OUTPUT_EVENTS_SECONDARY_TOPIC=events_json_v2
INGESTION_OUTPUT_EVENTS_SECONDARY_PRODUCER=WARPSTREAM
INGESTION_OUTPUT_EVENTS_SECONDARY_MODE=copy
INGESTION_OUTPUT_EVENTS_SECONDARY_PERCENTAGE=100
```

The secondary producer must be defined in the pipeline's `producers.ts` with its own env var config mapping.

### Modes

- **`off`** (default) — secondary is ignored.
  All messages go to primary only, regardless of other secondary settings.
- **`copy`** — primary always receives all messages.
  A percentage of messages (by key hash) is also copied to secondary.
  Useful for validating a new cluster while keeping the original fully fed.
- **`move`** — messages are routed to exactly one target.
  A percentage of messages (by key hash) goes to secondary; the rest go to primary.
  Useful for gradually migrating traffic from one cluster to another.

### Percentage and key hashing

The `percentage` (0–100) controls what fraction of messages are routed to secondary.
Routing is deterministic per message key using FNV-1a 32-bit — the same key always routes the same way,
so related messages (e.g. same `distinct_id`) stay together on the same target.

Messages without a key are routed randomly based on the percentage,
since the absence of a key means ordering doesn't matter for those messages.

### Failure semantics

If either target fails, the entire produce call fails.
Other outputs are unaffected — dual writes are per-output.

## Conventions

Pipeline steps receive `IngestionOutputs<O>` as a dependency and produce messages through it using `outputs.produce(output, message)` or `outputs.queueMessages(output, messages)`. Steps should never access Kafka producers directly.

Each pipeline defines its output and producer config in its own directory (e.g. `analytics/config/`). Shared output constants that appear in multiple pipelines go in `common/outputs.ts`. The server builds the outputs at startup and passes them down.

## How to extend

To add a new output:

1. Add the output name constant to the appropriate `outputs.ts` file (`common/` if shared, or the pipeline's own)
2. Add topic and producer config keys to the pipeline's config type (e.g. `IngestionOutputsConfig`)
3. Add defaults in the `getDefault*Config()` function
4. Add a `.register()` call in the pipeline's `register*Outputs()` function

To add a new producer:

1. Add the name constant and config map to the pipeline's `producers.ts`
2. Add the config keys to `KafkaProducerEnvConfig` with defaults
3. Add a `.register()` call on the `KafkaProducerRegistryBuilder` in the server

To enable dual writes for an existing output, set the `secondaryTopicEnvVar` and `secondaryProducerEnvVar` fields on the output definition, then configure the env vars at deploy time.

## File layout

```text
ingestion/outputs/              — generic infrastructure (pipeline-agnostic)
ingestion/common/outputs.ts     — shared output constants (e.g. EVENTS_OUTPUT)
ingestion/common/producers.ts   — shared producer constants and config maps
ingestion/analytics/outputs.ts  — analytics-specific output constants
ingestion/analytics/config/     — analytics pipeline config (output types, defaults, registration)
```
