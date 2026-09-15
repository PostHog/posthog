# CDP dead-letter queue and replay

## Summary

Destinations and workflows lose events when the CDP pipeline fails before an invocation exists.
Nothing stores the event, so nothing can replay it after a fix.

This plan adds a Kafka dead-letter queue (DLQ) on the `warpstream-cyclotron` cluster and a replay worker that feeds the records back through the same pipeline code.

- An event that fails filter or input construction for a function goes to a DLQ topic as the original message bytes.
  Headers name the functions that failed.
- A raw message that a consumer cannot parse or process goes to the same topic.
- A bounded replay worker reads the topic after a forward fix.
  It rebuilds invocations for the named functions only, and queues them.
- New DLQ traffic pages.

The DLQ holds no ClickHouse rows.
An incident can dead-letter millions of events, and Kafka on WarpStream is the store that absorbs that volume at low cost.
The existing rerun tooling stays the path for invocations that exist and failed in execution.

## Context

### The incident

A HogVM change ([PR #81140](https://github.com/PostHog/posthog/pull/81140)) made the argument-count check for some builtins narrower than HogQL.
Valid input templates such as `round(x, 2)` or `now(tz)` threw during input construction.
The pipeline recorded an `inputs_failed` app metric and a log line, and then dropped the event.
No invocation existed, so the rerun tooling had nothing to replay.
The forward fix ([PR #96261](https://github.com/PostHog/posthog/pull/96261)) restores the arities, but the deliveries lost in between are gone.
Users reported the problem. No alert fired.
The number of lost deliveries is unknown, because nothing counted them per function.

### How an event becomes a delivery today

The destination path (`nodejs/src/cdp/consumers/cdp-events.consumer.ts`):

1. `_parseKafkaBatch` parses each `clickhouse_events_json` message, loads the team and its functions, and builds `HogFunctionInvocationGlobals`.
2. `HogFunctionInvocationPipeline.buildInvocations` runs the filter bytecode (`utils/hog-function-filtering.ts`), builds inputs (`services/hog-inputs.service.ts`), and applies quota, watcher state, and masking.
3. `queueInvocations` writes the invocations to the `cdp_cyclotron_hog` Kafka topic.
4. `CdpCyclotronWorker` executes them and records results.

The workflow path has the same shape.
`HogFlowExecutorService.buildHogFlowInvocations` runs the trigger filter and `createHogFlowInvocation`, then the invocation goes to the `hogflow` queue in cyclotron Postgres.

From step 4 on, every invocation writes lifecycle rows to `hog_invocation_results` (`services/monitoring/hog-invocation-results.service.ts`).
The rerun tooling (`nodejs/src/cdp/rerun/`) replays `failed` rows, and the executor rebuilds inputs from the current config at run time.
The cyclotron README ("No DLQ", `services/cyclotron-v2/README.md`) explains why the job queue has no dead-letter table: failed jobs multiply on retry, and rerun already covers them.

Steps 1 and 2 have no store.
A failure there produces a metric and a log line, and the event is gone.
That is the gap this plan closes.
The job queue and rerun are out of scope, and the README position stands for them.

### Where events are lost today

| Stage                                                          | Code                                                     | Outcome today                                | Recorded                                 | Plan                             |
| -------------------------------------------------------------- | -------------------------------------------------------- | -------------------------------------------- | ---------------------------------------- | -------------------------------- |
| Parse or team lookup fails                                     | `cdp-events.consumer.ts` `_parseKafkaBatch` catch        | Drop                                         | Pod log, `counterParseError`             | DLQ (parse), fail batch (lookup) |
| Filter bytecode throws                                         | `hog-function-filtering.ts` `filterFunctionInstrumented` | No invocation                                | App metric `filtering_failed`, log entry | DLQ                              |
| Input construction throws                                      | `invocation-utils.ts` `_buildInvocation` catch           | No invocation                                | App metric `inputs_failed`, log entry    | DLQ                              |
| Workflow trigger filter throws                                 | `hogflow-executor.service.ts` `buildHogFlowInvocations`  | No invocation                                | App metric `filtering_failed`, log entry | DLQ                              |
| Unexpected exception outside the per-function try blocks       | `processBatch`                                           | Batch fails, offsets stay, consumer restarts | Pod log, error tracking                  | DLQ, with a circuit breaker      |
| Job message fails to parse                                     | `job-queue-kafka.ts` `consumeKafkaBatch`                 | Batch fails, consumer restarts               | Pod log                                  | DLQ                              |
| Quota, `disabled_permanently`, masked, workflow `rate_limited` | Pipeline services                                        | Intentional drop                             | App metric                               | No change                        |
| Execution fails after retries                                  | Executors                                                | `failed` result                              | Lifecycle row, app metric                | No change, rerun covers it       |
| Poison pill in cyclotron Postgres                              | Janitor                                                  | `failed` row, then delete                    | Lifecycle row                            | No change, rerun covers it       |

The `_parseKafkaBatch` catch also swallows transient errors from `getTeam` and the function managers.
A short Postgres outage therefore drops events for the whole team instead of retrying the batch.

Transformations are out of scope for replay.
A failed transformation lets the event continue untransformed (`hog-transformations/hog-transformer.service.ts`).
The event is already in ClickHouse, and a later replay cannot change it.
Detection still covers them.

## Goals

- No event leaves the CDP pipeline without one of: an intentional drop with a metric, a queued invocation, or a DLQ record.
- After a forward fix, an operator can count and replay the affected events for one function, one team, or the whole fleet, inside a time window.
- A replay creates invocations only for the functions that failed.
  Functions that delivered the first time do not deliver twice.
- A new class of platform failure pages within minutes.
- No new database and no new ClickHouse rows.
  Storage is Kafka on WarpStream.

## Non-goals

- Replay of transformations.
- Exactly-once delivery.
  Destinations stay at-least-once.
- A replacement for rerun.
  Invocations that exist stay on `hog_invocation_results`.
- A user-facing replay button.
  Replay is an operator action in this plan.

## Design

### Principle: no silent drop

Every non-success outcome in the pipeline gets an explicit policy.
The policy lives in one table in `nodejs/src/cdp/types.ts`, keyed by the `MinimalAppMetric['metric_name']` union:

```ts
export const OUTCOME_POLICY = {
  filtered: 'expected_drop',
  masked: 'expected_drop',
  quota_limited: 'expected_drop',
  disabled_permanently: 'expected_drop',
  rate_limited: 'expected_drop',
  filtering_failed: 'dead_letter',
  inputs_failed: 'dead_letter',
  failed: 'lifecycle_row',
  succeeded: 'success',
  // ...
} as const satisfies Record<MinimalAppMetric['metric_name'], OutcomePolicy>
```

A new metric name does not compile until it has a policy.
A `dead_letter` outcome must produce a DLQ record in the same batch.
A unit test asserts that each pipeline early-exit emits a metric whose policy matches what the code did.

Errors are classified the way `nodejs/src/ingestion/framework/retry.ts` does:

- `isRetriable === true` (Postgres, Redis, Kafka, timeouts): rethrow.
  The batch fails, offsets stay, and the consumer retries.
  Dependency outages do not make messages poisonous ([PR #95200](https://github.com/PostHog/posthog/pull/95200) set this rule for logs ingestion).
- `isRetriable === false`, or an unknown error: the message is poisonous for this code version.
  Dead-letter it and continue the batch.

### Part 1: DLQ topics

**Topics.**
One DLQ topic per consumer, named after the consumer and not after the shared source topic:

| Consumer               | Source topic                                     | DLQ topic                 | Env var                                  |
| ---------------------- | ------------------------------------------------ | ------------------------- | ---------------------------------------- |
| `cdp-processed-events` | `clickhouse_events_json`                         | `cdp_events_dlq`          | `CDP_EVENTS_CONSUMER_DLQ_TOPIC`          |
| `cdp-internal-events`  | `cdp_internal_events`                            | `cdp_internal_events_dlq` | `CDP_INTERNAL_EVENTS_CONSUMER_DLQ_TOPIC` |
| `cdp-cyclotron-worker` | `cdp_cyclotron_hog`, `cdp_cyclotron_hogoverflow` | `cdp_cyclotron_jobs_dlq`  | `CDP_CYCLOTRON_JOB_QUEUE_DLQ_TOPIC`      |

Constants go in `nodejs/src/common/config/kafka-topics.ts` and `posthog/kafka_client/topics.py` (the two files must stay in sync).
`posthog/kafka_client/routing.py` maps the new topics to `KafkaClusterProfile.CYCLOTRON`.

**Cluster.**
The topics live on `warpstream-cyclotron`, the cluster that carries every CDP topic and the `WARPSTREAM_CYCLOTRON_PRODUCER` in `nodejs/src/cdp/outputs/producers.ts`.
Ingestion keeps its DLQ topics on MSK because those topics feed back into MSK consumers.
The CDP DLQ has only CDP consumers, so it stays with the CDP topics.
WarpStream stores on S3.
Millions of records cost a few gigabytes, produce latency does not matter for a DLQ, and retention is a config value.

**Retention.**
30 days.
The incident ran for more than two weeks before the fix was ready.
A shorter retention loses the events before an operator can replay them.
30 days also matches the `hog_invocation_results` TTL, so both recovery paths reach back the same distance.

**Record format.**
Reuse the shape that `produceMessageToDLQ` in `nodejs/src/ingestion/framework/result-handling-helpers.ts` produces:

- Key: the original key.
- Value: the original message bytes, unchanged.
  Do not re-serialize.
  The raw event is smaller than the globals, it is the canonical input, and every other DLQ in the repo holds raw bytes.
- Headers: the original headers, plus the table below.

| Header                                     | Value                                                                                                 |
| ------------------------------------------ | ----------------------------------------------------------------------------------------------------- |
| `dlq_step`                                 | `parse`, `filter`, `inputs`, `process`, or `deserialize`                                              |
| `dlq_reason`                               | The first error message, cut to 1 KB                                                                  |
| `dlq_timestamp`                            | ISO 8601                                                                                              |
| `dlq_topic`, `dlq_partition`, `dlq_offset` | Source position, as in the ingestion DLQs                                                             |
| `dlq_consumer_group`                       | The producing consumer group                                                                          |
| `dlq_team_id`                              | When the parse got that far                                                                           |
| `dlq_event_uuid`                           | When the parse got that far                                                                           |
| `dlq_hog_function_ids`                     | Comma-separated ids of the functions that failed at this step. Empty means every function of the team |
| `dlq_hog_flow_ids`                         | Same, for workflows                                                                                   |
| `dlq_replay_count`                         | Starts at `0`                                                                                         |

One record per event and step.
An event whose inputs fail for three functions produces one record that names three ids.
The functions that succeeded for that event are queued as today and are not in the record.

**Producer.**
A `CdpDeadLetterService` in `nodejs/src/cdp/services/dead-letter/` collects failures during a batch and produces them at the end of the batch.
`buildInvocations` in both pipelines returns the build failures next to the invocations, as `{ messageRef, functionId, kind, step, error }`.
`_buildInvocation` and the filter error branch keep the app metric and the log entry, and add a build failure to that list.
The DLQ output registers through `common/outputs` as a `DLQ_OUTPUT`, the same as every ingestion pipeline.
Startup fails when the topic does not exist (`checkTopics`).
The service awaits broker acks before the batch completes, so a DLQ record exists before the consumer stores the offset.
A failed DLQ produce fails the batch.

**When a message goes to the DLQ.**

- `_parseKafkaBatch`: a JSON parse error or a schema error is non-retriable.
  Dead-letter the message with `dlq_step=parse`.
  A `getTeam` or manager error is retriable.
  Rethrow it, so the batch fails.
  This also fixes the silent drop on Postgres blips.
- `buildInvocations`: a filter or input error for one function adds that function to the event's record (`filter` or `inputs`).
- `processBatch`: wrap the per-event work in a try block.
  A non-retriable or unknown error dead-letters that one event with `dlq_step=process` and continues the batch.
- `consumeKafkaBatch` in `job-queue-kafka.ts`: a job message that fails decompression or JSON parsing dead-letters to `cdp_cyclotron_jobs_dlq` with `dlq_step=deserialize`.
  Today it throws and the consumer restarts on the same message.

**Batch circuit breaker.**
An unknown error in every message is a systemic bug, not poison.
When more than `CDP_DLQ_BATCH_FAIL_RATIO` (default `0.5`) of a batch would dead-letter with `dlq_step=process`, the consumer fails the batch instead.
Offsets stay, lag grows, and the existing lag alert pages.
The ratio does not apply to `filter` and `inputs` records.
A broken builtin can affect every function in a batch, and those records are exactly what the operator needs to replay.

**Gate.**
`CDP_DLQ_ENABLED` (default `false` until phase 1 ships).
When off, the consumers behave as today.

### Part 2: replay worker

A new server mode `PLUGIN_SERVER_MODE=cdp_dlq_replay`.
It registers like every other CDP mode: a `PluginServerMode` value, a capability, and a `registerService` block in `server.ts`.

The worker consumes a DLQ topic and runs the same code as the source consumer.
It uses the events consumer's `_parseKafkaBatch` and both `buildInvocations` pipelines, and it queues with the same `queueInvocations`.
A replayed event therefore runs the fixed code, and masking, quota, and watcher state apply to it.

**Function restriction.**
`BuildHogFunctionInvocationsOptions.invocationFilterFn` already restricts the functions a `buildInvocations` call considers.
The worker passes a filter that keeps only the ids in `dlq_hog_function_ids`, and the workflow pipeline gets the same option for `dlq_hog_flow_ids`.
An empty list (steps `parse` and `process`) replays every function of the team, because none of them ran.
A function that no longer exists or is disabled is skipped and counted.

**Run shape.**
The worker follows `IngestionSessionReplayMlImageScrubDlqReplayServer` (`nodejs/src/servers/`):

- It is bounded.
  It records the end offsets at start, reads to them, stops after two empty polls, and exits.
  An operator scales it to one replica for a replay and back to zero.
- Each run has a consumer group `<source group>-dlq-replay-<run id>`.
  A new run id starts from the window start, so a later replay with a different policy reads the same records again.
- A record outside the policy is skipped, not re-produced.
  The skip decision reads headers only, so a scan over millions of records does not parse them.
- A record that fails again goes back to the DLQ with `dlq_replay_count + 1`.
  It lands after the recorded end offset, so one run cannot loop.
- A record at `CDP_DLQ_REPLAY_MAX_REPLAYS` (default `2`) is skipped and counted as `exhausted`.
  It stays parked until retention removes it.

**Policy.**
All config, read once at start:

| Env var                                                   | Meaning                                                                             |
| --------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| `CDP_DLQ_REPLAY_TOPIC`                                    | Which DLQ topic to read                                                             |
| `CDP_DLQ_REPLAY_RUN_ID`                                   | Suffix of the consumer group                                                        |
| `CDP_DLQ_REPLAY_FROM`, `CDP_DLQ_REPLAY_TO`                | Window on `dlq_timestamp`, seeked with `offsetsForTimes`                            |
| `CDP_DLQ_REPLAY_STEPS`                                    | Subset of `dlq_step` values, default all                                            |
| `CDP_DLQ_REPLAY_TEAM_IDS`, `CDP_DLQ_REPLAY_SKIP_TEAM_IDS` | Allow and deny lists                                                                |
| `CDP_DLQ_REPLAY_HOG_FUNCTION_IDS`                         | Restrict to these functions                                                         |
| `CDP_DLQ_REPLAY_REASON_CONTAINS`                          | Substring match on `dlq_reason`, for one bug class                                  |
| `CDP_DLQ_REPLAY_MAX_REPLAYS`                              | Default `2`                                                                         |
| `CDP_DLQ_REPLAY_MAX_AGE`                                  | Skip records older than this. Default `30d` for destinations and `7d` for workflows |
| `CDP_DLQ_REPLAY_MAX_MESSAGES_PER_SECOND`                  | Throttle, so a replay does not flood the hog queue                                  |

**Sizing a replay.**
The worker has no count-only mode.
A count taken before the rebuild is not the number of deliveries, because the pipeline still rejects a function that was deleted or disabled, a team that is quota limited, and an event that is masked.
A count taken after the rebuild is exact but is no longer free: building invocations claims masks in Redis and reports billable invocations, so measuring would change what the next real run delivers.
The generic `replay_kafka_dlq` can count without producing, because it re-produces raw bytes with no pipeline in between, so its record count is its delivery count.
That does not carry over here.

To size a replay, read the `dlq_team_id`, `dlq_hog_function_ids`, `dlq_reason` and `dlq_step` headers on the topic and group them.
That answers "how many deliveries did we lose, and for whom" without running the worker at all.

**Refusing an unconfigured run.**
The worker will not start unless `CDP_DLQ_REPLAY_RUN_ID` names the run.
A replica scaled up before its policy is written therefore stops, rather than replaying everything the default open policy matches.

**Job DLQ.**
Records from `cdp_cyclotron_jobs_dlq` are re-produced to their source queue topic, unchanged, with the `dlq_*` headers removed.
That is safe because only CDP workers consume those topics.

**Never produce to `clickhouse_events_json`.**
ClickHouse reads that topic.
A re-produce would duplicate events in the events table.
This is why the generic `replay_kafka_dlq` command and the Temporal `dlq-replay` workflow do not fit as-is; see alternatives.

**Ordering.**
A replayed event arrives days after its neighbors.
Destinations are already unordered at-least-once, so this is acceptable.
For workflows, the trigger filter runs again on replay, and the shorter `CDP_DLQ_REPLAY_MAX_AGE` skips stale triggers with a metric.
A workflow trigger that is a week late is usually wrong.

**What a user sees.**
The function's metrics and logs keep the `inputs_failed` and `filtering_failed` entries from the first attempt.
A replayed invocation appears in the Invocations UI as a normal run, with `succeeded` or `failed`.
Replayed invocations carry `queueMetadata.replayed_from_dlq = true`, so a `replayed` app metric can be added later without a format change.

**Runbook.**
`docs/internal/cdp-dead-letter-replay.md` (written with phase 1) covers: confirm the forward fix is deployed, group the records by their `dlq_*` headers to size the replay, name the run, run the replay with a window, a reason filter and a throttle, then check the metrics below.

### Part 3: detection and alerting

The incident was found through user reports.
These signals turn the same class of failure into a page.

Prometheus counters, next to the app metrics:

- `cdp_invocation_build_failures_total{step="filter"|"inputs", function_type}`
- `cdp_dead_letter_messages_total{topic, step}`
- `cdp_dead_letter_produce_failures_total{topic}`
- `cdp_dead_letter_batch_failures_total{topic}` (the circuit breaker fired)
- `cdp_dlq_replay_messages_total{outcome="replayed"|"skipped"|"exhausted"|"failed"|"function_missing"}`

Alerts:

- Page: `cdp_dead_letter_messages_total` rate is above zero for 10 minutes.
  The steady state is zero.
  A broken builtin shows up here within one deploy.
- Page: `cdp_invocation_build_failures_total` rate rises above its 7 day baseline for 15 minutes, as a ratio to `triggered`.
  This catches the same bug when `CDP_DLQ_ENABLED` is off, and it covers transformations.
- Page: `cdp_dead_letter_produce_failures_total` or `cdp_dead_letter_batch_failures_total` above zero.
- Warn: DLQ topic high-water mark grows (KMinion, per cluster).

### Part 4: data retention and privacy

- DLQ records carry full event payloads, the same content as `clickhouse_events_json`.
  Retention is 30 days.
  The topics are TTL-reclaimed and get a line in `docs/internal/clickhouse-deletion-coverage.md`, next to the other DLQs.
- Only the replay worker and the topic browser in `rust/ingestion-control-plane` read the DLQ topics.
- Headers hold ids and error messages only.
  An error message from the Hog VM can quote a template value, so `dlq_reason` is cut to 1 KB and is not indexed anywhere.

## Rollout

Phase 0, days:

- Add `cdp_invocation_build_failures_total` and its alert.
- Split the `_parseKafkaBatch` catch: rethrow retriable errors.

Phase 1, two to three weeks, gated by `CDP_DLQ_ENABLED`:

- Topics, routing entries, outputs registration.
- `CdpDeadLetterService`, build failures returned from both pipelines, records for `filter` and `inputs`.
- `OUTCOME_POLICY` and its test.
- Enable on one region and watch `cdp_dead_letter_messages_total` and topic size.
  Producing records before the replay worker exists is safe, and it measures the real volume.
- Per-event isolation, `parse` and `process` records, and the circuit breaker.
- The replay worker mode.
- Runbook and the deletion-coverage doc line.
- Game day: deploy a deliberate builtin regression to a dev stack, confirm the alert fires, size the replay from the record headers, run it, and confirm every event delivers once.

Phase 2, follow-ups:

- `cdp_cyclotron_jobs_dlq` and its replay.
- The hog-flow loader drops a job without a lifecycle row when the flow or team is not found (`cdp-cyclotron-worker-hogflow.consumer.ts`).
  Add the record-before-drop block that `loadHogFunctions` has.
  This is a rerun-path fix, not a DLQ item.
- `HogMaskerService.release()` is not called when the event pipelines fail after the masking claim.
- The watcher counts build failures, so a function that fails to build for a long time becomes `degraded`.

## Success criteria

- Build failures without a DLQ record: zero, measured as `cdp_invocation_build_failures_total` minus `cdp_dead_letter_messages_total{step=~"filter|inputs"}` per hour, once `CDP_DLQ_ENABLED` is on.
- Time to detect a new build-failure class: under 15 minutes in the game day, from deploy to page.
- DLQ produce rate in steady state: zero.
- Replay precision: a replayed event creates invocations only for the functions in its record, checked in the game day.
- No increase in `clickhouse_events_json` consumer lag from the DLQ produce.

## Alternatives considered

**A `failed` row in `hog_invocation_results` for every build failure, replayed by rerun.**
Rejected for volume.
A build failure is one row per event and function.
An incident like this one writes millions of rows into a table that backs the Invocations UI, through the same Kafka topic and ClickHouse insert path that live invocations use.
Kafka holds the same events as raw bytes, smaller, with no query-time cost and no schema in ClickHouse.
Rerun also skips the filter stage, so `filtering_failed` rows would need a special case, and the DLQ replay runs the filter again as a matter of course.

**Serialized globals as the DLQ value.**
Rejected.
The globals are larger than the raw event, they carry a stale person and group snapshot, and a custom format needs its own schema and migration.
Raw bytes are canonical, and every other DLQ in the repo holds them.

**A DLQ table in cyclotron Postgres.**
Rejected for the reasons in `services/cyclotron-v2/README.md`.

**Reuse `posthog/kafka_client/dlq_replay.py`, `replay_kafka_dlq`, or the Temporal `dlq-replay` workflow.**
Both re-produce to a target topic and cannot restrict to functions.
The CDP source topic is shared with ClickHouse, so a re-produce duplicates events.
Their `--max-replays`, `--skip-team-ids` and `--max-messages-per-second` flags are the model for the replay policy above.
Their count-only flag is not, because it counts records it would re-produce verbatim, while this worker rebuilds each record through the pipeline and the pipeline can still reject it.

**Fail the batch on every unknown error.**
Preserves data, and it is what the consumer does today.
A deterministic bug in one message then blocks the partition for every team on it, and the fix needs a hotfix deploy before any event moves.
Kept for retriable and systemic failures through the circuit breaker.

## Open questions

1. Retention: 30 days is proposed.
   Is a shorter or longer window wanted for payload data?
2. Should persistent build failures degrade a function, as execution failures do?
   The incident was a platform bug, and a `disabled` function needs a manual re-enable after the fix.
   Proposal: `degraded` only.
3. Replay trigger: env config plus a scale-up for the first version.
   Is an API-triggered replay job wanted later, so on-call does not need a deploy?
4. Who owns replay operations, and where does the runbook live for on-call?
5. Should the function's metrics show a `replayed` count, so users see that a lost delivery was recovered?

## Appendix: the standing DLQ design questions

`rust/ingestion-consumer/README.md` lists the open questions for a poison-message DLQ.
This plan answers them for the CDP:

- DLQ topic: one per consumer, on the consumer's cluster, raw bytes plus `dlq_*` headers.
- Retry budget: retriable errors never reach the DLQ; dead-lettered records get `CDP_DLQ_REPLAY_MAX_REPLAYS` (2) replays, then stay parked until retention.
- Per-key ordering: accepted for destinations (already unordered); for workflows the trigger filter runs again and a max age skips stale records.
- Replay ownership: the CDP team, through the bounded replay worker, which refuses to start until the run is named.
