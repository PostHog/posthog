# Where billing usage records come from

Every producer of `billing_usage_records` and the exact point in its flow where usage is counted.
The rule that shapes all of them: **count after the last step that can drop the thing being billed, and before the row is written.**

## Reading the tables

`ReplacingMergeTree(event_timestamp)` sorts by `(team_id, producer_id, record_id, version)`.
Two records with the same `(team_id, producer_id, record_id)` collapse to one — they do not add.
So a producer's `record_id` has to be a stable identity for the billed thing: the same work replayed must produce the same ID, and different work must never share one.
`usage_key` is not in the sort key, which is why every producer's `record_id` includes it whenever the producer emits more than one key.

| producer_id      | usage_key                  | unit        | record_id                                                                                       | env var                                   |
| ---------------- | -------------------------- | ----------- | ----------------------------------------------------------------------------------------------- | ----------------------------------------- |
| `ingestion`      | `events`, `ai_events`      | events      | `{topic}:{partition}:{minOffset}-{maxOffset}:{usage_key}`                                       | `USAGE_INGESTION_REPORT_EVENTS_TEAMS`     |
| `ai-ingestion`   | `ai_events`                | events      | same shape                                                                                      | `USAGE_INGESTION_REPORT_AI_EVENTS_TEAMS`  |
| `error-tracking` | `exceptions`               | events      | same shape                                                                                      | `USAGE_INGESTION_REPORT_EXCEPTIONS_TEAMS` |
| `cdp`            | `cdp_billable_invocations` | invocations | `event:{eventUuid}` / `flow:{invocationId}:{actionStepCount}:{kind}` / `webhook:{invocationId}` | `USAGE_INGESTION_REPORT_CDP_TEAMS`        |
| `feature-flags`  | `feature_flag_requests`    | requests    | fresh UUIDv7 per flush                                                                          | `FLAGS_USAGE_INGESTION_TEAMS`             |

Each env var is a team matcher, so a producer rolls out independently: `''` reports nothing, `*` every team, `1,2` those teams, `5%` a sampled share.
Empty is the default everywhere, so nothing reports until it is set.

## Analytics ingestion

```mermaid
flowchart TD
    K[events_plugin_ingestion] --> DENY[deny $exception, heatmap, client warning]
    DENY --> RESTRICT[token restrictions: drop / force overflow]
    RESTRICT --> RL[rate limit to overflow]
    RL --> PARSE[parse message]
    PARSE --> TEAM[resolve team]
    TEAM --> HIST[validate historical migration]
    HIST --> FILTERS[customer event filters]
    FILTERS --> COOKIELESS[cookieless processing]
    COOKIELESS --> DROPOLD[drop old events]
    DROPOLD --> TRANSFORM[hog transformations]
    TRANSFORM --> PERSONS[person processing]
    PERSONS --> PREPARE[prepare event]
    PREPARE --> GROUPS[process groups]
    GROUPS --> COUNT[**count usage**]
    COUNT --> CREATE[create event]
    CREATE --> EMIT[emit to clickhouse_events_json]

    DENY -.dropped.-> X[not counted]
    RESTRICT -.dropped.-> X
    RL -.redirected.-> OF[overflow topic, counted on the overflow lane]
    PARSE -.dlq.-> X
    TEAM -.dlq.-> X
    HIST -.dropped.-> X
    FILTERS -.dropped.-> X
    DROPOLD -.dropped.-> X
    TRANSFORM -.dropped.-> X
```

Counting sits between group processing and event creation, the last point where the event still carries its own team, name and Kafka message.
Everything that can drop an event runs upstream of it.

`resolveAnalyticsUsageKey` decides the key from the event name, so an event is billed under the product that owns it wherever it turns up.
A `$ai_*` event that reaches this lane is billed as `ai_events`, not as a standard event, and the non-billable names (`$feature_flag_called`, `$experiment_exposure`, survey events, `$exception`, conversations widget events) return no key at all.
That list mirrors `BILLABLE_EVENT_EXCLUDED_EVENTS` in `posthog/tasks/usage_report.py`; the two have to agree or the same team is billed differently by the two systems.

Overflow is not a drop. A redirected event is consumed again on the overflow lane, whose consumer reports under its own topic and partition, so it is counted exactly once.

### The one case that over-counts

Counting happens before the Kafka produce, and the produce is not awaited.
An event that fails to emit with `message_size_too_large` is counted but never lands in `clickhouse_events_json`.
Moving the count onto the produce acknowledgement was considered and rejected: the acknowledgement resolves after the batch's flush step, so the count would land in a cleared accumulator, and the record ID could no longer be the batch's offset range — which is what makes a rebalance replay deduplicate instead of double-billing.
Emission retries five times, so the residue is bounded by that one non-retried failure, which also raises an ingestion warning.

## AI ingestion

Same shape, on its own lane. The allow step DLQs anything that is not an AI event, so every event that reaches the counting step is billable and the resolver returns `ai_events` unconditionally.

AI events are double-written to `clickhouse_events_json` and `clickhouse_ai_events_json`. Counting runs before the split, so the double write bills once.

## Error tracking

```mermaid
flowchart TD
    K[exceptions_ingestion] --> RESTRICT[token restrictions]
    RESTRICT --> RL[rate limit to overflow]
    RL --> PARSE[parse message]
    PARSE --> TEAM[resolve team]
    TEAM --> COOKIELESS[cookieless processing]
    COOKIELESS --> CYMBAL[cymbal: symbolication, fingerprint, issue link]
    CYMBAL --> PERSON[fetch person]
    PERSON --> TRANSFORM[hog transformations]
    TRANSFORM --> PREPARE[prepare event]
    PREPARE --> GROUPS[process groups]
    GROUPS --> COUNT[**count usage**]
    COUNT --> CREATE[create event]
    CREATE --> EMIT[emit to clickhouse_events_json]

    CYMBAL -.suppressed.-> X[not counted]
    RESTRICT -.dropped.-> X
    PARSE -.dlq.-> X
```

Cymbal is the Rust symbolication service, and it suppresses exceptions — a suppressed exception is dropped from the pipeline.
Counting runs after it, so a suppressed exception is never billed.
Cymbal runs before enrichment for an unrelated reason (it only needs the raw exception, so suppressing early saves the enrichment work), which happens to put every one of its drops upstream of the counting step.

## CDP

CDP reports through `CdpUsageReporterService`, which owns its own batching and flush timer.
It is deliberately not derived from the `billable_invocation` app metric: the app metrics could be deleted without touching billing.
Three call sites report, each next to the app metric it is independent of:

| Site                                          | When                                                    | record_id                                      |
| --------------------------------------------- | ------------------------------------------------------- | ---------------------------------------------- |
| `hog-function-invocation-pipeline.service.ts` | an event triggers at least one destination              | `event:{eventUuid}`                            |
| `hogflows/actions/hog_function.ts`            | a workflow function action executed and was not skipped | `flow:{invocationId}:{actionStepCount}:{kind}` |
| `cdp-source-webhooks.consumer.ts`             | a webhook produced a workflow trigger                   | `webhook:{invocationId}`                       |

The event-triggered site bills once per triggering event, not per destination, matching the existing app metric.
The workflow site keys on `actionStepCount` so a cyclotron retry of the same step reuses the ID and deduplicates, while a loop that revisits the same action gets a new one and bills again.

The reporter flushes on a timer rather than at a consumer batch boundary, so an ungraceful exit can lose up to one interval of records per pod — the same exposure the feature-flags aggregator carries.

## Feature flags

The billing aggregator already counts requests in memory per `(team, request_type, library, bucket)` and flushes them to Redis on a tick.
Usage records are emitted from inside that flush, once a chunk has been credited to Redis, so a Redis retry cannot bill twice and the two stores can only disagree by a failed usage request.

`record_id` is a fresh UUIDv7 per emission rather than something derived from the aggregation key.
The key is not a stable identity for a delta: a Redis outage rebuckets and merges requeued entries, so the same key legitimately carries different quantities across flushes.
ID reuse is therefore scoped to the retry the gRPC client performs on one request.

## Trying it locally

The service's compose entry sits behind the `ingestion` profile and builds from source, so run it from cargo instead:

```sh
docker compose -f docker-compose.dev.yml up -d db redis7 kafka clickhouse objectstorage
DEBUG=1 python manage.py migrate_clickhouse
cd rust && USAGE_INGESTION_DATABASE_URL=postgres://posthog:posthog@localhost:5432/posthog \
  USAGE_INGESTION_TEAM_ORGANIZATION_REDIS_URL=redis://localhost:6379/2 \
  OBJECT_STORAGE_BUCKET=posthog OBJECT_STORAGE_ENDPOINT=http://localhost:19000 \
  cargo run -p usage-ingestion
```

Then point a producer at it and turn its team matcher on:

```sh
USAGE_INGESTION_ADDR=localhost:7143 USAGE_INGESTION_REPORT_EVENTS_TEAMS='*' ./bin/start
FLAGS_USAGE_INGESTION_URL=http://localhost:7143 FLAGS_USAGE_INGESTION_TEAMS=all cargo run -p feature-flags
```

Records land within one flush interval:

```sql
SELECT producer_id, usage_key, sum(quantity), count()
FROM billing_usage_records GROUP BY 1, 2 ORDER BY 1, 2
```

## What is not reported yet

Session replay, surveys, data warehouse rows synced, batch export rows, logs and APM all still reach billing only through the nightly usage report.
