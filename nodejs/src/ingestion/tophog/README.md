# TopHog

TopHog is an in-process metric aggregation system that tracks the top contributors for named metrics across pipeline steps. It accumulates counts and timings keyed by arbitrary dimensions (e.g. `team_id`), keeps only the top N entries per metric, and periodically flushes results to Kafka.

This is not a tool for analyzing customer behavior. It is designed for realtime troubleshooting of multi-tenant systems to quickly identify whether a small subset of tenants is overloading the system — e.g. "which teams are producing the most events right now?" or "which teams are causing the slowest processing times?"

## Metric types

Each metric type has three variants:

- **Input** (`count`, `sum`, `max`, `average`) — records before the step runs. Key/value derived from the step input.
- **Result** (`countResult`, `sumResult`, `maxResult`, `averageResult`) — records after the step completes, regardless of result type (ok, drop, dlq, redirect). Key/value receive `(result, input)` where `result` is the full `PipelineResult<TOutput>`. Use when you need to count all invocations including drops/dlqs.
- **Ok** (`countOk`, `sumOk`, `maxOk`, `averageOk`) — records after the step completes, only on OK results. Key/value receive `(output, input)` where `output` is the unwrapped OK value. Use when you need the output value.

- **`count(name, keyFn, opts?)`** / **`countResult(name, keyFn, opts?)`** / **`countOk(name, keyFn, opts?)`** — increments by 1 per invocation. Use for tracking volume (e.g. messages received, events produced).
- **`sum(name, keyFn, valueFn, opts?)`** / **`sumResult(name, keyFn, valueFn, opts?)`** / **`sumOk(name, keyFn, valueFn, opts?)`** — accumulates a custom value per invocation. Use for tracking totals where each invocation contributes a variable amount (e.g. bytes ingested, payload sizes).
- **`max(name, keyFn, valueFn, opts?)`** / **`maxResult(name, keyFn, valueFn, opts?)`** / **`maxOk(name, keyFn, valueFn, opts?)`** — tracks the maximum observed value per key. Use for finding peak values (e.g. largest payload size, slowest individual request).
- **`average(name, keyFn, valueFn, opts?)`** / **`averageResult(name, keyFn, valueFn, opts?)`** / **`averageOk(name, keyFn, valueFn, opts?)`** — tracks the average value per key. Ranks and evicts by average, not sum. Use for finding keys with consistently high values rather than high volume (e.g. average payload size per team).
- **`timer(name, keyFn, opts?)`** — records elapsed wall-clock time in milliseconds. The key is derived from the step input at start time. Records regardless of whether the step succeeds or fails.

## Designing metrics

### Keys

Metric keys are plain objects (`Record<string, string>`). Keys with the same properties and values are aggregated together, so property ordering must be deterministic. Always construct key objects with properties in a consistent order.

Use properties that align with dimensions used elsewhere in the system, particularly event ingestion restrictions. The recommended properties are:

- `team_id` — team identifier
- `distinct_id` — user identifier
- `event` — event name
- `session_id` — session identifier
- `uuid` — event UUID

You don't need to use all of them. Pick the dimensions that make sense for what you're troubleshooting — typically `team_id` is enough to find noisy tenants.

### Example

A pipeline that parses messages and processes persons, with TopHog metrics tracking message counts, payload size, and person processing time:

```typescript
interface RawInput {
    message: Message
    team_id: number
    distinct_id: string
}

interface ParsedEvent {
    team_id: number
    distinct_id: string
}

function parseMessage(input: RawInput): Promise<PipelineResult<ParsedEvent>> {
    // ... parsing logic
}

function processPerson(input: ParsedEvent): Promise<PipelineResult<void>> {
    // ... person processing logic
}

return builder
    .pipe(
        topHog(parseMessage, [
            // Count messages per team
            count('parsed_messages', (input) => ({
                team_id: String(input.team_id),
            })),
            // Count messages per team + distinct_id
            count('parsed_messages_by_distinct_id', (input) => ({
                team_id: String(input.team_id),
                distinct_id: input.distinct_id,
            })),
            // Track total payload size per team
            sum('parsed_message_bytes', (input) => ({
                team_id: String(input.team_id),
            }), (input) => input.message.value?.length ?? 0),
            // Track total payload size per team + distinct_id
            sum('parsed_message_bytes_by_distinct_id', (input) => ({
                team_id: String(input.team_id),
                distinct_id: input.distinct_id,
            }), (input) => input.message.value?.length ?? 0),
            // Track largest single message per team
            max('max_message_bytes', (input) => ({
                team_id: String(input.team_id),
            }), (input) => input.message.value?.length ?? 0),
            // Track average message size per team
            average('avg_message_bytes', (input) => ({
                team_id: String(input.team_id),
            }), (input) => input.message.value?.length ?? 0),
        ])
    )
    .pipe(
        topHog(processPerson, [
            // Time person processing per team + distinct_id
            timer('process_person_time', (input) => ({
                team_id: String(input.team_id),
                distinct_id: input.distinct_id,
            })),
            // Count person processing completions per team (all results)
            countResult('persons_processed', (_result, input) => ({
                team_id: String(input.team_id),
            })),
        ])
    )
```

## Configuration

### TopHog (instance-level)

| Option            | Type                     | Default  | Description                                             |
| ----------------- | ------------------------ | -------- | ------------------------------------------------------- |
| `kafkaProducer`   | `KafkaProducerWrapper`   | required | Kafka producer for flushing                             |
| `topic`           | `string`                 | required | Kafka topic for metric messages                         |
| `pipeline`        | `string`                 | required | Pipeline name included in each message                  |
| `lane`            | `string`                 | required | Lane name included in each message                      |
| `flushIntervalMs` | `number`                 | `60000`  | How often to flush to Kafka                             |
| `defaultTopN`     | `number`                 | `10`     | Default number of top entries to report per metric      |
| `maxKeys`         | `number`                 | `1000`   | Default max distinct keys per metric tracker            |
| `labels`          | `Record<string, string>` | `{}`     | Static labels included in every message (e.g. hostname) |

### MetricConfig (per-metric overrides)

Passed to any metric factory to override instance-level defaults for a specific metric.

| Option    | Type     | Description                       |
| --------- | -------- | --------------------------------- |
| `topN`    | `number` | Override top-N for this metric    |
| `maxKeys` | `number` | Override max keys for this metric |

## Tuning

**`maxKeys`** controls the memory/accuracy tradeoff. Higher values track more distinct keys accurately but use more memory and make eviction passes slower. Lower values use less memory but may drop keys that would have been in the top N. The default of 1000 works well when `topN` is 10 because there's two orders of magnitude of headroom before eviction could affect the top entries.

**`topN`** controls how many entries are reported per flush. Set this to however many top contributors you want visibility into. Keep it well below `maxKeys` so that eviction doesn't affect reported results.

**`flushIntervalMs`** controls reporting frequency. Shorter intervals give more granular time series but produce more Kafka messages. Longer intervals aggregate more data per message but increase latency to visibility.

## Architecture

```text
TopHog (registry + Kafka reporter)
├── summingTrackers
│   └── SummingMetricTracker "emitted_events"
├── maxTrackers
│   └── MaxMetricTracker "max_payload"
├── averageTrackers
│   └── AverageMetricTracker "avg_size"
└── allTrackers() → iterates all three maps for flush

Pipeline extension (pipelines/extensions/tophog.ts)
├── count("emitted_events", keyFn)           → increments by 1 before step runs
├── countResult("output_count", keyFn)       → increments by 1 after step, on all results
├── countOk("ok_count", keyFn)              → increments by 1 after step, on OK results only
├── sum("total_bytes", keyFn, valueFn)       → accumulates value before step runs
├── sumResult("output_bytes", keyFn, valueFn)→ accumulates value after step, on all results
├── sumOk("ok_bytes", keyFn, valueFn)       → accumulates value after step, on OK results only
├── max("max_payload", keyFn, valueFn)       → tracks max value before step runs
├── maxResult("max_output", keyFn, valueFn)  → tracks max value after step, on all results
├── maxOk("max_ok_output", keyFn, valueFn)  → tracks max value after step, on OK results only
├── average("avg_size", keyFn, valueFn)     → tracks average before step runs
├── averageResult("avg_out", keyFn, valueFn)→ tracks average after step, on all results
├── averageOk("avg_ok_out", keyFn, valueFn)→ tracks average after step, on OK results only
├── timer("processing_time", keyFn)         → records elapsed ms per step
└── createTopHogWrapper(registry)            → wraps pipeline steps with metrics
```

`TopHog` owns the flush interval and Kafka reporting. Trackers are stored in separate maps by type (`summingTrackers`, `maxTrackers`, `averageTrackers`), so the same metric name can exist across different types without collision. `MetricTracker` handles per-metric accumulation, eviction, and top-N selection. The pipeline extension provides factory functions that wire metrics into pipeline steps.

## Performance

### MetricTracker.record()

Each call to `record()` is technically O(log K) due to the Map operations where K = `maxKeys`, but since K is a fixed constant this is effectively O(1). When the number of distinct keys exceeds `maxKeys`, an eviction pass sorts all entries and drops the bottom half by value.

For N total records and K = `maxKeys`:

- **Eviction cost**: O(K log K) per eviction, triggered every ~K/2 new unique keys
- **Total cost of N insertions**: O(N log K)
- **Amortized cost per record**: O(log K)

In practice, most records update existing keys (pure O(1)) so evictions are infrequent.

### MetricTracker.flush()

Each flush sorts entries (O(K log K)) and takes the top N. This runs once per flush interval (default: 60s), not per event.

### Memory

Each metric tracker holds at most `maxKeys` entries in memory. After eviction, it holds at most `maxKeys / 2`. Total memory per TopHog instance is bounded by `numMetrics * maxKeys * avgKeySize`.
