# Alerts noop workers

The Alerts product registers three queues through `products/alerts/backend/facade/temporal.py` and the shared `start_temporal_worker` command:

| Setting in `posthog/settings/temporal.py`        | Queue                                            | Workflow                     |
| ------------------------------------------------ | ------------------------------------------------ | ---------------------------- |
| `ALERTS_PRODUCT_SHARED_ORCHESTRATION_TASK_QUEUE` | `alerts-product-shared-orchestration-task-queue` | `alerts-product-orchestrate` |
| `ALERTS_PRODUCT_EVALUATION_TASK_QUEUE`           | `alerts-product-evaluation-task-queue`           | `alerts-product-evaluate`    |
| `ALERTS_PRODUCT_DELIVERY_TASK_QUEUE`             | `alerts-product-delivery-task-queue`             | `alerts-product-deliver`     |

These queue names are hardcoded and stay separate even with `DEBUG=True`.
Shared orchestration registers the orchestration workflow, the source dispatcher and a synthetic demand-discovery activity.
The evaluation queue registers the evaluation workflow (`alerts-product-evaluate`), each bound source evaluation, and the probe activity.
Each schedule tick starts orchestration, which discovers demand once and then pages source dispatchers until the demand is exhausted or its dispatch budget is spent.
Each dispatcher starts one evaluation child for its source. Evaluation runs the probe and starts its independent delivery child on the delivery queue.
Start one worker for each queue:

```bash
python manage.py start_temporal_worker --task-queue alerts-product-shared-orchestration-task-queue --metrics-port 8104
python manage.py start_temporal_worker --task-queue alerts-product-evaluation-task-queue --metrics-port 8102
python manage.py start_temporal_worker --task-queue alerts-product-delivery-task-queue --metrics-port 8103
```

Give every worker its own `--metrics-port`.
The option defaults to 8001, which the shared development worker already binds, so a worker that keeps the default stops with `Address already in use`.
The shared development worker does not poll these queues.
See [Temporal development guidance](../../posthog/temporal/README.md) for worker setup.

## Dev schedule

`python manage.py schedule_temporal_workflows` creates or updates `alerts-product-check-due-schedule`
only when `CLOUD_DEPLOYMENT=DEV`. The normal deployment migration step runs this command.
Registration does nothing in production, local development, or other environments, even with `DEBUG=True`.
It does not delete schedules created manually in those environments.

The schedule starts `alerts-product-orchestrate` with `{}` on the orchestration queue every minute (UTC).
There is no routing flag: the flow is tick → orchestration → evaluation → delivery.
It uses SKIP overlap, a one-minute catchup window, a 50-second workflow execution timeout,
and one workflow attempt. Creation does not trigger an immediate run; the next minute starts it.
Delivery has no schedule: evaluation starts its delivery child.
New schedules start unpaused. Registration updates existing schedules to this policy while retaining their state from Temporal, including manual pauses.
To stop future smoke-test ticks, pause the schedule in Temporal; resume it there when ready. Pausing does not stop workflows already running.
Disabling registration alone does not remove an existing Temporal schedule.

Verify the Postgres activity result and the delivery child's completion separately.
Parent completion does not prove either succeeded. Schedule creation also does not prove worker availability.
Enable production only in a separate rollout after dev verification.

### Shared orchestration rollout and rollback

The deployment identity is `temporal-worker-alerts-product-shared-orchestration`.
It uses the shared `posthog-cloud` image built by `container-images-cd.yml`, not a separate image build or repository.
Worker deployment configuration lives outside this repository. Deploying this code must be coordinated with starting the orchestration worker.
Schedule reconciliation now routes directly to orchestration; merging the code alone does not start a worker process.
If the dev schedule does not exist yet, start all three workers before the first reconciliation: new schedules start unpaused.

1. Pause the existing dev schedule before deployment so migration-time reconciliation cannot send ticks to a worker that is not ready.
2. Deploy the code and start the orchestration worker with the command above.
   Verify it polls `alerts-product-shared-orchestration-task-queue`, and that evaluation and delivery workers remain available.
3. Run `python manage.py schedule_temporal_workflows` and verify the action starts `alerts-product-orchestrate` on the orchestration queue.
   Existing pause state is preserved. Resume only after all three workers are ready, then verify the complete workflow chain.

To stop future starts, pause the schedule. Keep all three workers running until orchestration, evaluation, and delivery work drains.
For rollback, restore the previous schedule action (the evaluation workflow started directly on the evaluation queue, named `alerts-product-check-due` before the rename below) after draining, then roll back the code.
Do not reconcile with the new code after restoring the old action: reconciliation would route back to orchestration.
Pausing or changing the schedule does not move or stop queued or running workflows.

### Manual local runs

For local development, start an orchestration run by hand.
The `execute_temporal_workflow` and `start_temporal_workflow` commands do not know these workflows and reject the name, so use the Temporal CLI in the dev stack:

```bash
docker exec posthog-temporal-admin-tools-1 \
    temporal workflow start --address temporal:7233 --namespace default \
    --task-queue alerts-product-shared-orchestration-task-queue \
    --type alerts-product-orchestrate \
    --workflow-id "alerts-product-orchestrate-manual-$(date +%Y%m%d%H%M%S)" \
    --execution-timeout 50s \
    --input '{}'
```

The empty `--input '{}'` becomes an `OrchestrateInputs` with every field defaulted.
Watch orchestration, its source dispatcher children, their evaluation children, and the delivery great-grandchildren in the Temporal UI at <http://localhost:8081>.

Evaluation and delivery accept an empty `AlertsProductInputs` dataclass; orchestration accepts `OrchestrateInputs` with all fields defaulted.
Orchestration pages source dispatchers, which start evaluation children with a 75-second execution timeout and one workflow attempt.
Evaluation child IDs carry the tick ID, source and page, so each tick starts distinct evaluations.
Evaluation runs a Postgres connectivity probe; delivery runs an empty activity with no I/O.
Evaluation and delivery activities each have a 10-second start-to-close timeout and a 30-second schedule-to-close timeout.
Evaluation has one attempt; delivery retains at most three attempts.
Evaluation starts one delivery child on the delivery queue and waits for confirmation that it started, without waiting for completion.
The child ID includes the evaluation run ID, so repeated runs of the same evaluation workflow ID start different children.
`ParentClosePolicy.ABANDON` lets delivery continue after evaluation closes.
Delivery has a one-minute execution timeout for the noop.
Real notification delivery guarantees remain undecided.

## Names

The evaluation workflow is `alerts-product-evaluate` (class `AlertsProductEvaluateWorkflow`), the probe activity is `alerts_product_probe_postgres_activity`, and the schedule is registered by `create_alerts_product_tick_schedule`.
These replace `alerts-product-check-due`, `alerts_product_check_due_activity` and `create_alerts_product_check_due_schedule`: discovery finds what is due and dispatchers hand it out, so this workflow only evaluates.
A workflow type rename breaks runs of the old type that are in flight at deploy time: no worker knows the old name, so they fail. Dev evaluations live under their execution timeout, and production is off.
The schedule ID stays `alerts-product-check-due-schedule`. Registration does not delete schedules, so a new ID would leave two schedules until someone deleted the old one by hand.

## Tick loop and source dispatchers

One tick is one `alerts-product-orchestrate` execution. It takes an `OrchestrateInputs`; the schedule passes `{}` and every field defaults.
The first run records the tick cutoff (the scheduled start time, or the workflow start time for manual runs) and a deadline 45 seconds after the run started.
Discovery runs once per tick. The loop then starts one `alerts-product-source-dispatch` child per source with demand, ID `{tick_id}-{source}-p{page}`, on the orchestration queue.
Dispatchers are part of the tick: the orchestrator awaits each dispatcher's report and keeps the default `TERMINATE` close policy on that edge.
They run on the tick's own fleet because the tick awaits them. On the evaluation queue, an evaluation fleet with no free slots
leaves the dispatcher unpicked, and the tick waits on a report that cannot arrive. A dispatcher starts no activities,
so it costs the orchestration fleet a workflow task per source per page and nothing else.
The evaluations it starts still name the evaluation queue, so moving the dispatcher does not move them.
Each dispatcher has one attempt and an execution timeout of 30 seconds, or the time left before the tick's hard stop minus one second, whichever is shorter.
The hard stop is the run's own execution timeout when it has one, and the budget plus five seconds otherwise. Both deadlines travel in the input across continued runs.

The orchestrator passes a dispatcher every remaining ID for its source. The dispatcher decides how much to take and returns the rest.
Today it takes everything: no adapter has said yet how many alerts one evaluation can hold, so nothing remains and a tick is one page.
The limit that will matter is the evaluation workflow's own history, which depends on the adapter's query shape; it arrives with the first real adapter.
It starts one `alerts-product-evaluate` child, ID `{dispatcher_id}-eval`, with `ParentClosePolicy.ABANDON`, a 75-second execution timeout (`SOURCE_EVALUATION_TIMEOUT`) and one attempt.
The timeout has to hold every attempt a source's activities allow, because an attempt cut off here is a batch that decided something and recorded nothing.
Evaluations are abandoned rather than awaited, so it does not have to fit inside the tick.
It waits for the child to start, never for it to finish, then returns the dispatched count and the remaining IDs.
Members are not passed to evaluation yet: evaluation keeps the probe path until claims exist.

After every page the orchestrator records a `TickPage` (page, run ID, dispatched, remaining, failed sources, undispatched).
When nothing remains it returns `OrchestrateResult(remaining=0, deadline_reached=False)`.
Before each page after the first, it checks the deadline. When work remains and the deadline has passed, or fewer than two seconds remain before the hard stop, it returns cleanly with the remaining count and `deadline_reached=True`; the next minute's tick discovers that work again.
A tick always runs its first page: the deadline is a stop rule, not an admission rule.
A tick that exits with remaining work is a load signal. A tick that hits the schedule's 50-second execution timeout is a breakage signal: a clean exit never times out.
The orchestrator calls `continue_as_new` only when Temporal reports `is_continue_as_new_suggested()`. The continued run receives the cutoff, deadline, demand and pages in its input and does not rerun discovery.
The schedule's execution timeout spans continued runs, so a rollover cannot extend the tick.

A dispatcher that overruns times out before the tick's hard stop rather than the tick being terminated mid-page. Evaluations already started by earlier dispatchers, and their delivery children, are abandoned and complete on their own.
The orchestrator settles its pages rather than failing on the first error, so one source's dispatcher failing or timing out does not stop the sources dispatching alongside it in the same minute.
A failed source is counted in the page's `failed_sources`, its keys in `undispatched`, and it is logged with its error.
Only a `ChildWorkflowError` counts as a source failure. Anything else, a cancellation or a bug in the orchestrator included, still fails the tick rather than being absorbed on every tick behind a report that says it completed. Nothing advanced its keys' due time, and discovery orders by that time,
so those keys are rediscovered and win a later tick; the tick reports them in `remaining` rather than re-paging them.
If the tick is terminated or times out anyway, Temporal terminates its in-flight dispatchers after the tick closes.
The previous `workflow.patched` gate around discovery is gone: the loop cannot run without discovery, and dev histories live under a minute.

## Synthetic demand discovery

The first orchestration activity, `alerts_product_discover_demand_activity`, accepts a timezone-aware ISO-8601 cutoff.
Scheduled runs use `TemporalScheduledStartTime`; manual runs use the workflow start time.
Activity retries retain the same cutoff rather than reading the activity's clock.
The activity returns an `AlertDemand` containing configuration IDs grouped by the shared `SourceKind` enum (`logs` and `insight`).
Only nonempty groups are returned. Discovery does not reserve or claim IDs.
Each source is bounded to `DISCOVERY_LIMIT_PER_SOURCE` IDs (1,000) so the manifest stays near 40 KB per source, under the repository's 256 KB rule for Temporal payload fields.
`omitted_by_source` counts the due IDs left out. The tick adds that count to its `remaining` result, and the next tick discovers that work again.

For now, `logic/demand.py` supplies deterministic synthetic configurations relative to that cutoff:
two eligible logs configurations and one eligible insight configuration, plus future and disabled configurations that are excluded.
There are no configuration-table reads, new database entities, or real evaluations of these IDs.
The result feeds the tick loop above. Evaluation still runs the probe/delivery smoke path without receiving synthetic IDs.
TTL claims are not implemented here.
Discovery has a five-second start-to-close timeout, a ten-second schedule-to-close timeout, and at most three attempts.

## Batch keys

Discovery returns batch keys, not configuration ids. A key is `(source, team_id, slot)`, where `slot` is
`next_check_at` floored to the minute. A key costs a fixed amount and does not grow with a team's alert
count, so the manifest bound is about how many chunks a tick starts rather than how many alerts it found.

The key names the chunk by what it holds, so the evaluation workflow id is
`alerts-eval-{source}-{team_id}-{slot}` and stays the same when a later tick rediscovers the same work.
A slow evaluation therefore blocks its own re-dispatch without a claim on the configuration rows.

Discovery orders by `next_check_at` ascending. A key the manifest bound leaves out grows more overdue
and wins a later tick; any stable ordering that is not by due time starves the same keys every tick.

Each dispatcher takes up to `MAX_EVALUATIONS_PER_DISPATCH` keys and hands the rest back as a later page.
The evaluation re-reads its own configurations from the key, which it has to do anyway to get thresholds
and filters, so it sees a fresher set than discovery did.

Flooring to the minute loses nothing that load spreading provides: `compute_shard_offset_seconds` returns
whole multiples of the 60-second schedule interval, so spreading moves an alert between minutes rather
than within one.

## Source evaluation bindings

`products/alerts/backend/temporal/sources.py` maps a `SourceKind` to the workflow name that evaluates it.
A source in that map gets its own workflow started by name, carrying one batch key and the tick cutoff.
A source absent from it keeps the noop `alerts-product-evaluate` path, which receives no key.
The alerts product imports nothing from a source: the binding holds a name, and `test_every_source_evaluation_binding_names_a_registered_workflow` fails if that name is not registered on the evaluation queue.

`logs` is bound to `logs-alert-evaluate`, which is the first real source evaluation.

## Logs source evaluation

`logs-alert-evaluate` evaluates one batch key, a team's alerts due in one minute, and previews one delivery per notification.
The evaluation is a plain function in `products/logs/backend/alert_source_cycle.py`, so a test calls it without Temporal.

It writes its own state and never the logs product's rows.
The production `logs-alerting-task-queue` fleet evaluates these same alerts every minute against `LogsAlertConfiguration`,
so a write to those rows, a `LogsAlertEvent` row or a Kafka message here would transition an alert twice and notify a person twice for one breach.
State transitions land on `PlatformAlert` and schedule advancement on `PlatformAlertConfiguration`, which the logs fleet never reads.
Delivery stops at `alerts-product-deliver-preview`, which records what would have been sent and contacts no destination.

The lifecycle decision comes from `products/alerts/backend/facade/lifecycle.py` configured with `LOGS_ALERT_POLICY`,
which is the shared machine the logs product's own state machine is a thin adapter over.
Going to the shared machine directly keeps the platform's lifecycle out of a source product's import path.

It evaluates against the tick cutoff rather than the clock, so a retried attempt selects the same alerts,
resolves the same windows and derives the same evaluation keys as the attempt it replaced.
The due predicate is applied a second time here, because discovery ran earlier in the tick and a configuration
can have been disabled, snoozed or broken since.

### Evaluating and writing are separate activities

`evaluate_logs_alerts_activity` reads and decides; it writes nothing.
It is a sync `def`, so Temporal runs it on the worker's own activity executor and the thread it blocks is a slot Temporal is accounting for.
An async activity handing the work to its own thread pool releases its slot the moment the activity times out, while the thread stays on a query Temporal can no longer see.
Being sync also means Django's connection recycling is the activity's own job, which `@close_db_connections` does for it.
The workflow then calls `alerts_product_record_outcomes`, the platform's own activity, which persists the batch.
Order matters more than the split does: Temporal holds the deliveries the batch decided on before any write
can advance a schedule past them, so an attempt lost between the two costs its queries and nothing else.
A source starts the write by name rather than importing it, so the products stay apart.

The write is safe to run twice. An attempt that commits leaves every configuration due after the cutoff,
and a replay skips those rows rather than advancing them again and skipping a cycle.
It runs in one transaction, so no alert is marked as notified while its schedule still says the check is due.

`MAX_PREVIEWS_PER_CYCLE` bounds an outcome together with the delivery it belongs to.
Recording an outcome whose preview the batch cannot carry would leave an alert firing with nothing announcing it,
and a firing alert does not fire again. Dropping the pair leaves it due, the way a truncated cohort already behaves.
`alerts_platform_deliveries_deferred_total` counts them.

Cohorting, the batched ClickHouse query, projection routing, the byte ceiling and ingestion-freshness gating
all come from the existing logs code, so a preview says what production would have sent.

### The query budget sits under the activity timeout

Four bounds, largest first: `SOURCE_EVALUATION_TIMEOUT` (75s) over the source's `EVALUATION_BUDGET` (62s) over `EVALUATE_START_TO_CLOSE` (30s) over `BATCH_QUERY_BUDGET_SECONDS` (25s) over `MAX_QUERY_SECONDS` (20s).
Temporal bounds an attempt by whichever of start-to-close and schedule-to-close expires first, so schedule-to-close is derived as start-to-close plus a queue tolerance rather than written as a literal.
A literal close to start-to-close lets queue time shorten the run below the query budget, which is the same inversion arriving by another route, on exactly the load that causes queueing.
`test_the_evaluation_timeout_ladder_holds` asserts the whole ladder in one place.
The order is the point. ClickHouse has to be what ends an overrunning query: with the activity timeout below the query's own limit,
the activity times out while the cluster is still running the query, the attempt's thread stays on it, and the retry starts an identical query alongside the first.
Above it, a slow query arrives as one failed cohort the batch reports and the rest of the batch continues.

A batch can run several cohort queries one after another, so a single per-query limit does not bound the batch.
Each query is given the time left before the batch deadline, capped at `MAX_QUERY_SECONDS`; below `MIN_QUERY_SECONDS` no further query starts
and the cohort keeps its due time, counted in an `unqueried` log line.
The budget covers the cohort queries only. The per-alert destination lookup is outside it, so a wide fan-out can still spend the activity's own timeout.
The cap reaches ClickHouse as `max_execution_time` on `BatchedAlertCheckQuery`, with `timeout_overflow_mode` set to throw,
because a partial count could resolve an alert that is actually breaching.

Delivery previews carry a list of group transitions with one entry and an empty grouping key.
Logs does not group yet; the list is the shape that lets fan-out change the evaluation and nothing downstream.

### Metrics

The path emits through Temporal's own meter, so every series carries the worker, queue and activity attributes
the runtime attaches. `products/alerts/backend/temporal/metrics.py` holds them and a source reaches them through
`facade/platform_metrics.py`.

| Metric                                                    | What it answers                                             |
| --------------------------------------------------------- | ----------------------------------------------------------- |
| `alerts_platform_checks_total{source,outcome}`            | How many checks the platform decided, and what they decided |
| `alerts_platform_state_transitions_total{source,from,to}` | Which transitions it reached                                |
| `alerts_platform_deliveries_previewed_total{source}`      | How many deliveries it recorded instead of sending          |
| `alerts_platform_deliveries_deferred_total{source}`       | How many the payload bound left for a later tick            |
| `alerts_platform_outcomes_recorded_total`                 | How many decisions reached the tables                       |
| `alerts_platform_batch_duration_ms{source}`               | What one batch key costs                                    |
| `alerts_platform_scheduler_lag_ms{source}`                | How far past its due time a check was evaluated             |

Histogram buckets are registered in `posthog/temporal/common/worker.py`; a histogram missing from
`ALERTS_PLATFORM_LATENCY_HISTOGRAM_METRICS` gets Prometheus defaults instead.
Every call site goes through `safe_record`, so a metric failure cannot fail a check.

### Seeding the shared tables

`PlatformAlertConfiguration` starts empty, so discovery finds nothing and no evaluation runs until configurations are copied in.
Run the copy once per environment from any pod that carries the application image and a database connection:

```bash
python manage.py backfill_platform_alert_configurations
```

Pass `--team-id` to copy one team's configurations only.
It is a seed, not a sync: the logs product keeps the control plane, and a later change to a logs alert reaches these tables only on the next run.
A second run updates rather than duplicates, because `legacy_configuration_id` carries the row each copy came from.

## Postgres connectivity probe

Each evaluation activity issues one explicit `SELECT 1` and checks for `(1,)` through Django's `default` main writer connection.
It inherits runtime credentials and connection/pooler settings without overrides, new aliases, or a separate pool.
It does not use replicas, persons services, or application tables.
One probe per tick means one intended activity attempt, not exactly-once SQL execution.
Connection setup and transaction control can issue additional statements.

The probe uses `execute_with_timeout(1000, database="default")` for a one-second transaction-local statement timeout.
The transaction commits on success and rolls back on failure, so the timeout does not persist on pooled connections.
Connection acquisition, SQL, and force-close cleanup run in the same executor thread, outside the default thread-sensitive executor.
`close_db_connections` closes initialized connections without a cleanup health-check query after failure.

Django `OperationalError` and `InterfaceError` become a sanitized `AlertsProductPostgresProbeFailure` activity failure.
Evaluation starts delivery after that failure or an activity start-to-close/schedule-to-close timeout.
Cancellation and unrelated errors propagate without starting delivery.
This handoff requires the parent and its worker to remain available; termination before child startup is not covered.

A successful evaluation workflow does not prove that the database probe succeeded.
Activity success/failure logs and attempt duration remain separate from delivery outcomes; #97445 owns lifecycle telemetry.
Activity duration includes executor wait, connection setup, transaction work, and cleanup, not just SQL execution.
On activity timeout, the replay-safe workflow log records an unknown database outcome and continuation to delivery, without a completed query duration.
A late activity completion does not replace that timeout observation.

The SQL timeout does not cover connection acquisition or pooler waiting.
Temporal's activity bounds limit the workflow's wait, but timeout or cancellation cannot kill a running database thread or guarantee SQL has stopped.
Cleanup runs when that thread finishes; this probe does not change connection defaults or add a watchdog.

Before production rollout, deployment owners must verify the runtime database identity and main writer route in dev using the deployment's credentials.
Verify a successful probe, statement timeout and transaction reset through the configured pooler, and delivery continuation after failure or timeout.
`SELECT 1` alone does not verify the intended database identity, application grants, schema, or write readiness.
These tests do not replace deployment verification.

Worker registration does not deploy workers. The dev schedule sets the orchestration workflow's
50-second execution timeout; manually started workflows must set their own timeout.

## Activity logs

The evaluation and delivery queues use an activity-only interceptor that emits `alerts_product_activity_started` and `alerts_product_activity_finished` through the shared write-only logger.
Discovery has SDK metrics and traces but does not use this logging interceptor.
The shared logger's async methods keep log processing and writes off the activity event loop.
Each retry emits its own start and finish events.
The shared logger supplies `activity_id`, `activity_type`, `attempt`, `task_queue`, `workflow_id`, `workflow_namespace`, `workflow_run_id`, and `workflow_type`.
Finish events add a monotonic `duration_ms` and an `outcome` of `success`, `failure`, or `cancellation`.
Start, success, and cancellation events use INFO; a failed attempt uses WARNING and includes only the exception class in `exception_type`.
A failed attempt does not mean the workflow has exhausted its retries.

When a valid OpenTelemetry span is active, both events include hexadecimal `trace_id` and `span_id` fields.
The interceptor does not log inputs, headers, exception messages, or locals, and does not capture exceptions separately.
Telemetry errors cannot replace an activity's result, exception, or cancellation.
Cancellation before the activity starts still propagates; cancellation while writing its finish log cannot replace the completed activity's outcome.
Evaluation and delivery workflow logging are unchanged.

## Metrics

The shared worker exposes these SDK histograms with `task_queue` labels:

- `temporal_activity_schedule_to_start_latency`: time from the current attempt's scheduling to its start. Earlier attempts and retry backoff are excluded.
- `temporal_activity_execution_latency`: worker-side execution time for an attempt, including interceptor overhead. This is not an end-to-end evaluation or delivery duration.

Both histograms use milliseconds and the SDK's default buckets.
Prometheus exposes their `_bucket`, `_sum`, and `_count` series.
Native metrics retain the `temporal_` prefix. The `alerts_product_` convention applies only to custom metrics if those are added later.
Do not add workflow or run IDs as metric labels.

A worker killed before completion cannot emit a finish log or execution sample.
Activities that never start produce no worker-side timing sample.
Missing finish events are not evidence of success.

## Tracing and deployment verification

All three deployments must set `TEMPORAL_OTEL_PLUGIN_ENABLED=true`, a nonempty `OTEL_SERVICE_NAME`, and the appropriate OTLP gRPC exporter configuration.
For example, configure `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` for the collector and any required credentials or TLS settings.
The shared startup command initializes Temporal's replay-safe provider, and the client registers `OpenTelemetryPlugin(add_temporal_spans=True)`.
Do not add the legacy tracing interceptor or another provider.

The activity logs use the plugin's active attempt span.
Orchestration, evaluation, child delivery, and their activity spans retain their trace relationships even when delivery runs after evaluation finishes.
Retries have separate activity attempt spans.

Tests verify local logging, queue-labelled SDK metrics, and trace relationships without an application database or an external collector.
Charts rollout must separately configure all three deployments and verify Prometheus scraping and delivery to the tracing collector.
This change does not configure deployments, dashboards, alert rules, or SLO emission.
The `alerts-product` SLO area remains reserved without changes to shared SLO handling or workflow inputs.
