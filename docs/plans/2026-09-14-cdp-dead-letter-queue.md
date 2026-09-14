# CDP dead-letter queue and replay

## Summary

Destinations and workflows can lose events when the CDP pipeline fails before an invocation exists.
This plan closes that gap and adds a Kafka dead-letter queue (DLQ) for the failures that no invocation can represent.

The plan has four parts:

1. Record every invocation-build failure as a durable `failed` row in `hog_invocation_results`, so the existing rerun tooling can replay it.
2. Add per-consumer DLQ topics on the `warpstream-cyclotron` cluster for raw messages that the consumers cannot process.
3. Replay from both stores: the rerun API and a fleet rerun command for rows, and a bounded replay worker for the DLQ topics.
4. Page on new build failures and on DLQ traffic, so the next platform bug is an alert and not a support ticket.

Part 1 is the incident fix and needs no new infrastructure.
Part 2 is the general safety net.

## Context

### The incident

A HogVM change ([PR #81140](https://github.com/PostHog/posthog/pull/81140)) made the argument-count check for some builtins narrower than HogQL.
Valid input templates such as `round(x, 2)` or `now(tz)` threw during input construction.
The pipeline recorded an `inputs_failed` app metric and a log line, and then dropped the event.
No invocation existed, so the rerun tooling had nothing to replay.
The forward fix ([PR #96261](https://github.com/PostHog/posthog/pull/96261)) restores the arities, but the deliveries lost in between are gone.
Users reported the problem. No alert fired.

### How an event becomes a delivery today

The destination path (`nodejs/src/cdp/consumers/cdp-events.consumer.ts`):

1. `_parseKafkaBatch` parses each `clickhouse_events_json` message, loads the team and its functions, and builds `HogFunctionInvocationGlobals`.
2. `HogFunctionInvocationPipeline.buildInvocations` runs the filter bytecode (`utils/hog-function-filtering.ts`), builds inputs (`services/hog-inputs.service.ts`), and applies quota, watcher state, and masking.
3. `queueInvocations` writes the invocations to the `cdp_cyclotron_hog` Kafka topic.
4. `CdpCyclotronWorker` executes them and records results.

The workflow path is the same shape.
`HogFlowExecutorService.buildHogFlowInvocations` runs the trigger filter and `createHogFlowInvocation`, then the invocation goes to the `hogflow` queue in cyclotron Postgres.

Every executed invocation writes lifecycle rows to `hog_invocation_results` through `HogInvocationResultsService` (`services/monitoring/hog-invocation-results.service.ts`).
The rows carry `invocation_globals` (gzip and base64, `inputs` stripped), `status`, `error_kind`, `error_message`, `event_uuid`, and `distinct_id`.
The topic `clickhouse_hog_invocation_results` lives on the `warpstream-cyclotron` cluster and ClickHouse keeps the rows for 30 days (`posthog/models/hog_invocation_results/sql.py`).

### What already exists for replay

The rerun system (`nodejs/src/cdp/rerun/`, `consumers/cdp-rerun-worker.consumer.ts`) is a replay worker over `hog_invocation_results`:

- `POST /api/projects/:team_id/{hog_functions|hog_flows}/:id/rerun` enqueues a wrapper job with a filter: `window_start`, `window_end`, `status`, `error_kind`, `error_message_contains`, `max_attempts`, `max_count`, `invocation_ids`.
- `RerunPaginatorService` pages through matching rows, skips invocations that later succeeded or still run, and rebuilds the invocation from the stored globals with the same `invocation_id`.
- The executor rebuilds `inputs` from the current function config when they are absent (`services/hog-executor.service.ts`, `buildInputsWithGlobals` branch).
  A rerun after a fix therefore runs the fixed code.
- The cyclotron janitor and the hog-function loader already use `recordTerminalFailureDurably` to write a `failed` row before they drop a job (`services/cyclotron-v2/janitor.ts`, `consumers/cdp-cyclotron-worker.consumer.ts`).

The cyclotron README ("No DLQ", `services/cyclotron-v2/README.md`) states the team's position: lost invocations converge on `hog_invocation_results` and the rerun tooling, not on a second recovery path.
This plan keeps that position.
The rows are the dead-letter store for invocations.
ClickHouse is the index.
Rerun is the replay worker.
The Kafka DLQ below only takes the messages that cannot become a row.

### Where events are lost today

| Stage                                                          | Code                                                      | Outcome today                                | Recorded                                 | Replayable                                                       |
| -------------------------------------------------------------- | --------------------------------------------------------- | -------------------------------------------- | ---------------------------------------- | ---------------------------------------------------------------- |
| Parse or team lookup fails                                     | `cdp-events.consumer.ts` `_parseKafkaBatch` catch         | Drop                                         | Pod log, `counterParseError`             | No                                                               |
| Filter bytecode throws                                         | `hog-function-filtering.ts` `filterFunctionInstrumented`  | No invocation                                | App metric `filtering_failed`, log entry | No                                                               |
| Input construction throws                                      | `invocation-utils.ts` `_buildInvocation` catch            | No invocation                                | App metric `inputs_failed`, log entry    | No                                                               |
| Workflow trigger filter throws                                 | `hogflow-executor.service.ts` `buildHogFlowInvocations`   | No invocation                                | App metric `filtering_failed`, log entry | No                                                               |
| Workflow or team not found at execution                        | `cdp-cyclotron-worker-hogflow.consumer.ts` `loadHogFlows` | `dequeueInvocations`                         | Pod log only                             | No                                                               |
| Unexpected exception outside the per-function try blocks       | `processBatch`                                            | Batch fails, offsets stay, consumer restarts | Pod log, error tracking                  | Yes, but a deterministic bug blocks the partition for every team |
| Quota, `disabled_permanently`, masked, workflow `rate_limited` | Pipeline services                                         | Intentional drop                             | App metric                               | Not needed                                                       |
| Execution fails after retries                                  | Executors                                                 | `failed` result                              | Lifecycle row, app metric                | Yes, through rerun                                               |
| Poison pill in cyclotron Postgres                              | Janitor                                                   | `failed` row, then delete                    | Lifecycle row                            | Yes, through rerun                                               |

The `_parseKafkaBatch` catch also swallows transient errors from `getTeam` and the function managers.
A short Postgres outage therefore drops events for the whole team instead of retrying the batch.

Transformations are out of scope for replay.
A failed transformation lets the event continue untransformed (`hog-transformations/hog-transformer.service.ts`).
The event is already in ClickHouse, and the rerun tooling excludes transformations by design (`RERUNNABLE_HOG_FUNCTION_TYPES`).
Part 4 still covers them for detection.

## Goals

- No event or invocation leaves the CDP pipeline without one of: an intentional drop with a metric, a durable failed invocation row, or a DLQ record.
- After a forward fix, an operator can replay the affected invocations for one function, one team, or the whole fleet, inside a time window.
- A new class of platform failure pages within minutes.
- Users see a failed invocation in the Invocations UI, with the reason, instead of a bare counter.
- No new database.
  Storage is Kafka on WarpStream plus the ClickHouse table that exists.

## Non-goals

- Replay of transformations.
- Exactly-once delivery.
  Destinations stay at-least-once, and a replay can duplicate a delivery that partially succeeded.
- A DLQ inside cyclotron Postgres.
  The cyclotron README explains why.

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
  filtering_failed: 'durable_failure',
  inputs_failed: 'durable_failure',
  failed: 'durable_failure',
  succeeded: 'success',
  // ...
} as const satisfies Record<MinimalAppMetric['metric_name'], OutcomePolicy>
```

A new metric name does not compile until it has a policy.
A `durable_failure` outcome must produce a `hog_invocation_results` row through the durable write path.
Raw messages that cannot reach any policy go to the DLQ.
A unit test asserts that each pipeline early-exit emits a metric whose policy matches what the code did.

Errors are classified the way `nodejs/src/ingestion/framework/retry.ts` does:

- `isRetriable === true` (Postgres, Redis, Kafka, timeouts): rethrow.
  The batch fails, offsets stay, and the consumer retries.
  Dependency outages do not make messages poisonous ([PR #95200](https://github.com/PostHog/posthog/pull/95200) set this rule for logs ingestion).
- `isRetriable === false`, or an unknown error: the message is poisonous for this code version.
  Record it (row or DLQ) and continue the batch.

### Part 1: record build failures as failed invocations

This part is the fix for the incident class.

**Destinations.**
In `_buildInvocation` (`utils/invocation-utils.ts`) and in the filter error branch of `filterFunctionInstrumented`, keep the app metric and the log entry, and also call a new `recordBuildFailure(hogFunction, globals, errorKind, error)`.
The helper:

1. Builds the invocation with `createInvocation(globals, hogFunction)` and no `inputs`.
   The executor rebuilds inputs at run time, which is the documented rerun contract.
2. Calls `invocationResultsRowsService.recordTerminalFailureDurably(invocation, { errorKind, error })`.
   `errorKind` is `inputs_failed` or `filtering_failed`, the same names as the app metrics.
3. Returns `false` when the durable write fails.
   The caller then throws a retriable error, so the batch fails and retries.
   The cyclotron queue topic is on the same cluster, so a queue write would fail too.

The helper applies to `destination` and `internal_destination` only.
Transformations keep their current behavior.

**Workflows.**
`buildHogFlowInvocations` gets the same treatment.
The filter error branch calls `createHogFlowInvocation` and then the durable write with `function_kind: 'hog_flow'` and `errorKind: 'filtering_failed'`.
`loadHogFlows` in `cdp-cyclotron-worker-hogflow.consumer.ts` gets the record-before-drop block that `loadHogFunctions` already has, with `errorKind` values `flow_not_found` and `team_not_found`.

**Rerun changes.**
`inputs_failed` rows need no rerun change.
`filtering_failed` rows did not pass a filter, so `rehydrateInvocation` must run the filter again before it enqueues:
`convertToHogFunctionFilterGlobal(globals)` then `filterFunctionInstrumented`.
A row that does not match is skipped and counted as `filtered_on_rerun`.
Workflows do the same with the trigger filter.

**Fleet rerun.**
The rerun API works per function.
An incident spans many functions and teams.
Add a management command `rerun_hog_invocations_fleet`:

```text
python manage.py rerun_hog_invocations_fleet \
  --error-kind inputs_failed --error-kind filtering_failed \
  --window-start <start> --window-end <end> \
  [--team-ids 1,2,3] [--function-ids ...] [--max-count 100000] [--dry-run]
```

The command queries `hog_invocation_results` for distinct `(team_id, function_kind, function_id)` in the window, and enqueues one rerun job per function through the existing Django to Node proxy (`rerun_hog_invocations` in `posthog/plugins/plugin_server_api.py`).
It prints the plan first and requires `--yes` to enqueue.
The rerun worker already tracks `attempts` and `rerunAttempts`, so a second fleet run does not loop.

**Volume.**
A build-failure row costs the same as a `failed` execution row today: one row per matching event.
No sampling.
Sampling would drop events, which is the failure this plan removes.
The watcher does not see build failures today.
Extending it so a function with persistent build failures becomes `degraded` bounds the row rate.
See open questions for the `disabled` step.

### Part 2: dead-letter topics for raw messages

Part 1 needs parsed globals and a loaded function.
Some failures happen before that, or outside the per-function try blocks.
Those messages go to a Kafka DLQ as raw bytes.

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
The topics live on `warpstream-cyclotron`, the cluster that already carries every CDP topic and the `WARPSTREAM_CYCLOTRON_PRODUCER` in `nodejs/src/cdp/outputs/producers.ts`.
Ingestion keeps its DLQ topics on MSK because those topics feed back into MSK consumers.
The CDP DLQ has only CDP consumers, so it stays with the CDP topics.
WarpStream stores on S3, so a 7 day retention is cheap and produce latency does not matter for a DLQ.
Retention is 7 days by default and 14 days at most.
Longer than that, the forward fix has not happened and the replay is no longer meaningful for a destination.

**Record format.**
Reuse the shape that `produceMessageToDLQ` in `nodejs/src/ingestion/framework/result-handling-helpers.ts` produces:

- Key: the original key.
- Value: the original message bytes, unchanged.
  Do not re-serialize.
- Headers: the original headers, plus `dlq_reason`, `dlq_step`, `dlq_timestamp`, `dlq_topic`, `dlq_partition`, `dlq_offset`, and three new ones: `dlq_consumer_group`, `dlq_replay_count` (starts at `0`), and `dlq_team_id` when the parse got that far.

The CDP DLQ output registers through `common/outputs` as a `DLQ_OUTPUT`, the same as every ingestion pipeline.
Startup fails when the topic does not exist (`checkTopics`).

**When a message goes to the DLQ.**

- `_parseKafkaBatch`: a JSON parse error or a schema error is non-retriable.
  DLQ the message.
  A `getTeam` or manager error is retriable.
  Rethrow it, so the batch fails.
  This also fixes the silent drop on Postgres blips.
- `processBatch`: wrap the per-event build in a try block.
  A non-retriable or unknown error dead-letters that one event and continues the batch.
- `CdpCyclotronWorker`: a job message that fails decompression or deserialization dead-letters to `cdp_cyclotron_jobs_dlq`.
- The DLQ produce is awaited to broker ack before the consumer stores offsets.
  A failed DLQ produce fails the batch.

**Batch circuit breaker.**
An unknown error in every message is a systemic bug, not poison.
When more than `CDP_DLQ_BATCH_FAIL_RATIO` (default `0.5`) of a batch would dead-letter, the consumer fails the batch instead.
Offsets stay, lag grows, and the existing lag alert pages.
Nothing is written to the DLQ in that case, so the operator does not have to replay the whole stream after the fix.

**Gate.**
`CDP_DLQ_ENABLED` (default `false` until phase 2 ships).
When off, the consumers behave as today.

### Part 3: replay

**Rows.**
The rerun API and the fleet command from part 1.
Replayed invocations write `hog_function_rerun` or `hog_flow_rerun` rows under the same `invocation_id`, so the Invocations UI shows the outcome next to the original failure.

**DLQ topics.**
A new server mode `PLUGIN_SERVER_MODE=cdp_events_dlq_replay` (and the internal-events variant).
It is the same `CdpProcessedEventsConsumer` class with two changes: the topic is the DLQ topic and the consumer group is `<group>-dlq-replay-<run id>`.
The messages therefore run through the current `processBatch`, with the fixed code, and with masking, quota, and watcher state applied.

The worker follows `IngestionSessionReplayMlImageScrubDlqReplayServer` (`nodejs/src/servers/`):

- It is bounded.
  It records the end offsets at start, reads to them, stops after two empty polls, and exits.
  An operator scales it to one replica for a replay and back to zero.
- The replay policy is config: `CDP_DLQ_REPLAY_RUN_ID`, `CDP_DLQ_REPLAY_FROM` and `CDP_DLQ_REPLAY_TO` (against `dlq_timestamp`, seeked with `offsetsForTimes`), `CDP_DLQ_REPLAY_TEAM_IDS`, `CDP_DLQ_REPLAY_SKIP_TEAM_IDS`, `CDP_DLQ_REPLAY_MAX_REPLAYS` (default `2`), `CDP_DLQ_REPLAY_MAX_MESSAGES_PER_SECOND`, `CDP_DLQ_REPLAY_DRY_RUN`.
- A message outside the policy is skipped, not re-produced.
  A fresh run id starts a new consumer group, so a later replay with a different policy can read the same records again.
- A message that fails again is re-produced to the DLQ with `dlq_replay_count + 1`.
  It lands after the recorded end offset, so one run cannot loop.
- A message at `MAX_REPLAYS` is skipped and counted as `exhausted`.
  It stays parked until retention removes it.

The worker never produces to `clickhouse_events_json`.
ClickHouse reads that topic, and a re-produce would duplicate events in the events table.
This is why the generic `replay_kafka_dlq` command and the Temporal `dlq-replay` workflow do not fit as-is; see alternatives.

**Ordering.**
A replayed event arrives days after its neighbors.
Destinations are already unordered at-least-once, so this is acceptable.
For workflows, the trigger filter runs again on replay, and `CDP_DLQ_REPLAY_MAX_AGE` (default 7 days) skips records older than that with a metric.
A workflow trigger that is a week late is usually wrong.

**Runbook.**
`docs/internal/cdp-dead-letter-replay.md` (written with phase 2) covers: confirm the forward fix is deployed, run the fleet rerun with `--dry-run`, run it, then run the DLQ replay worker with a run id and a window, then check the metrics below.

### Part 4: detection and alerting

The incident was found through user reports.
These signals turn the same class of failure into a page.

Prometheus counters, next to the app metrics:

- `cdp_invocation_build_failures_total{stage="filter"|"inputs", function_type}`
- `cdp_build_failure_rows_total{outcome="recorded"|"failed"}`
- `cdp_dead_letter_messages_total{topic, reason}`
- `cdp_dead_letter_produce_failures_total{topic}`
- `cdp_dead_letter_replay_messages_total{outcome="replayed"|"skipped"|"exhausted"|"failed"}`

Alerts:

- Page: `cdp_invocation_build_failures_total` rate rises above its 7 day baseline for 15 minutes, as a ratio to `triggered`.
  This is the exact signature of the incident: new `inputs_failed` outcomes after a deploy.
- Page: `cdp_dead_letter_messages_total` rate is above zero for 10 minutes.
  The steady state is zero.
- Page: `cdp_dead_letter_produce_failures_total` above zero.
- Page: `cdp_build_failure_rows_total{outcome="failed"}` above zero.
- Warn: DLQ topic high-water mark grows (KMinion, per cluster).
- Warn: build failures without rows.
  A ClickHouse check compares the hourly count of `inputs_failed` and `filtering_failed` app metrics to the count of `failed` rows with the same `error_kind`.
  The two must match.

Transformations get the first alert too, on `function_type="transformation"`, even though they have no replay.

User-facing:
the Invocations UI shows the failed row with the error message, for example `Could not build inputs: round requires 1 argument`.
The function's metrics and logs stay as they are.

### Data retention and privacy

- DLQ records carry full event payloads, the same content as `clickhouse_events_json`.
  Retention is 7 days, configurable to 14.
  The topics are TTL-reclaimed and get a line in `docs/internal/clickhouse-deletion-coverage.md`, next to the other DLQs.
- `hog_invocation_results` rows keep their 30 day TTL and `stripInputs` keeps secrets out of the stored globals.
- Only the replay worker and the topic browser in `rust/ingestion-control-plane` read the DLQ topics.

## Rollout

Phase 0, days:

- Add the Prometheus counters and the build-failure alert.
- Split the `_parseKafkaBatch` catch: rethrow retriable errors.

Phase 1, one to two weeks, gated by `CDP_RECORD_BUILD_FAILURES_ENABLED`:

- `recordBuildFailure` for destinations and workflows.
- Record-before-drop in `loadHogFlows`.
- `OUTCOME_POLICY` and its test.
- Rerun re-filters `filtering_failed` rows.
- `rerun_hog_invocations_fleet`.
- Enable on one region, watch `cdp_build_failure_rows_total` and ClickHouse row volume, then enable everywhere.

Phase 2, two to three weeks, gated by `CDP_DLQ_ENABLED`:

- DLQ topics, routing entries, outputs registration.
- Per-message isolation, classification, and the batch circuit breaker in both event consumers and the job-queue consumer.
- The replay server mode.
- Runbook and the deletion-coverage doc line.
- Game day: deploy a deliberate parse bug to a dev stack, confirm the alert fires and a replay recovers every message.

Phase 3, follow-ups:

- The janitor `cleanupTerminalJobs` deletes a failed cyclotron row about 10 seconds after `job.fail()`, with no check that a lifecycle row was written.
  Route the ordinary terminal failure path through the durable write as well.
- `HogMaskerService.release()` is not called when the event pipelines fail after the masking claim.
- The watcher counts build failures.

## Success criteria

- Build failures without a row: zero per hour, measured by the ClickHouse check.
- Time to detect a new build-failure class: under 15 minutes in the game day, from deploy to page.
- DLQ produce rate in steady state: zero.
- Replay success: the share of replayed records that end in `succeeded` or an intentional drop, reported per run.
- No increase in `clickhouse_events_json` consumer lag from the extra durable writes.

## Alternatives considered

**A Kafka DLQ for every build failure, instead of rows.**
Rejected as the primary store.
Selective replay per function needs a topic scan, the failures would not appear in the Invocations UI, and the replay worker would duplicate the rerun semantics (attempt tracking, skip of invocations that later succeeded, window filters).
It would also be the second recovery path the cyclotron README argues against.
Kept only for raw messages that cannot become a row.

**A DLQ table in cyclotron Postgres.**
Rejected for the reasons in `services/cyclotron-v2/README.md`: failed jobs multiply on retry and the table grows without bound.

**Reuse `posthog/kafka_client/dlq_replay.py`, `replay_kafka_dlq`, or the Temporal `dlq-replay` workflow.**
Both re-produce to a target topic.
The CDP source topic is shared with ClickHouse, so a re-produce duplicates events.
A dedicated `cdp_events_replay` topic consumed by a CDP consumer would work, at the cost of one more topic per consumer.
The in-process replay mode is simpler and reuses the exact `processBatch` path.
The `--max-replays`, `--skip-team-ids`, `--max-messages-per-second`, and `--dry-run` flags of `replay_kafka_dlq` are the model for the replay policy.

**Fail the batch on every unknown error.**
Preserves data, and it is what the consumer does today.
A deterministic bug in one message then blocks the partition for every team on it, and the fix needs a hotfix deploy before any event moves.
Kept for retriable and systemic failures through the circuit breaker.

## Open questions

1. Should persistent build failures move a function to `disabled_permanently`, as execution failures do?
   The incident was a platform bug, and a disabled function would have needed manual re-enable after the fix.
   Proposal: `degraded` only.
2. What is the row volume for a broken user filter on a high-volume team?
   Measure in phase 1 before the fleet-wide enable.
3. Who owns replay operations, and where does the runbook live for on-call?
4. Should the Invocations UI group build failures by `error_kind`, so a user can see "inputs failed" as one line with a count?
5. The `hog_invocation_results` normal write path is best-effort (`flush()` swallows produce errors).
   Should all terminal failures use the durable path, at the cost of one awaited produce per failure?

## Appendix: the standing DLQ design questions

`rust/ingestion-consumer/README.md` lists the open questions for a poison-message DLQ.
This plan answers them for the CDP:

- DLQ topic: one per consumer, on the consumer's cluster, raw bytes plus `dlq_*` headers.
- Retry budget: retriable errors never reach the DLQ; non-retriable messages get `CDP_DLQ_REPLAY_MAX_REPLAYS` (2) replays, then stay parked until retention.
- Per-key ordering: accepted for destinations (already unordered); for workflows the trigger filter runs again and a max age skips stale records.
- Replay ownership: the CDP team, through the rerun API and fleet command for rows and the bounded replay server mode for topics.
