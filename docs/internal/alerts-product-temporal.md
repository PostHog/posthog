# Alerts noop workers

The Alerts product registers two queues through `products/alerts/backend/facade/temporal.py` and the shared `start_temporal_worker` command:

| Setting in `posthog/settings/temporal.py` | Queue                                  | Workflow                   |
| ----------------------------------------- | -------------------------------------- | -------------------------- |
| `ALERTS_PRODUCT_EVALUATION_TASK_QUEUE`    | `alerts-product-evaluation-task-queue` | `alerts-product-check-due` |
| `ALERTS_PRODUCT_DELIVERY_TASK_QUEUE`      | `alerts-product-delivery-task-queue`   | `alerts-product-deliver`   |

These queue names are hardcoded and stay separate even with `DEBUG=True`.
Start one worker for each queue:

```bash
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

The schedule starts `alerts-product-check-due` with `{}` on the evaluation queue every minute (UTC).
It uses SKIP overlap, a one-minute catchup window, a 50-second workflow execution timeout,
and one workflow attempt. Creation does not trigger an immediate run; the next minute starts it.
Delivery has no schedule: evaluation starts its delivery child.
New schedules start unpaused. Registration updates existing schedules to this policy while retaining their state from Temporal, including manual pauses.
To stop future smoke-test ticks, pause the schedule in Temporal; resume it there when ready. Pausing does not stop workflows already running.
Disabling registration alone does not remove an existing Temporal schedule.

Verify the Postgres activity result and the delivery child's completion separately.
Parent completion does not prove either succeeded. Schedule creation also does not prove worker availability.
Enable production only in a separate rollout after dev verification.

For local development, start an evaluation run by hand.
The `execute_temporal_workflow` and `start_temporal_workflow` commands do not know these workflows and reject the name, so use the Temporal CLI in the dev stack:

```bash
docker exec posthog-temporal-admin-tools-1 \
    temporal workflow start --address temporal:7233 --namespace default \
    --task-queue alerts-product-evaluation-task-queue \
    --type alerts-product-check-due \
    --workflow-id "alerts-product-check-due-manual-$(date +%Y%m%d%H%M%S)" \
    --input '{}'
```

The empty `--input '{}'` becomes the empty `AlertsProductInputs`.
Watch the evaluation run and its delivery child in the Temporal UI at <http://localhost:8081>.

Both workflows accept an empty `AlertsProductInputs` dataclass.
Evaluation runs a Postgres connectivity probe; delivery runs an empty activity with no I/O.
Each activity has a 10-second start-to-close timeout and a 30-second schedule-to-close timeout.
Evaluation has one attempt; delivery retains at most three attempts.
Evaluation starts one delivery child on the delivery queue and waits for confirmation that it started, without waiting for completion.
The child ID includes the evaluation run ID, so repeated runs of the same evaluation workflow ID start different children.
`ParentClosePolicy.ABANDON` lets delivery continue after evaluation closes.
Delivery has a one-minute execution timeout for the noop.
Real notification delivery guarantees remain undecided.

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

Worker registration does not deploy workers. The dev schedule sets the evaluation workflow's
50-second execution timeout; manually started workflows must set their own timeout.

## Activity logs

Both Alerts queues use an activity-only interceptor that emits `alerts_product_activity_started` and `alerts_product_activity_finished` through the shared write-only logger.
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
Workflow logging and workflow bodies are unchanged.

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

Both deployments must set `TEMPORAL_OTEL_PLUGIN_ENABLED=true`, a nonempty `OTEL_SERVICE_NAME`, and the appropriate OTLP gRPC exporter configuration.
For example, configure `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` for the collector and any required credentials or TLS settings.
The shared startup command initializes Temporal's replay-safe provider, and the client registers `OpenTelemetryPlugin(add_temporal_spans=True)`.
Do not add the legacy tracing interceptor or another provider.

The activity logs use the plugin's active attempt span.
Evaluation, child delivery, and their activity spans retain their trace relationships even when delivery runs after evaluation finishes.
Retries have separate activity attempt spans.

Tests verify local logging, queue-labelled SDK metrics, and trace relationships without an application database or an external collector.
Charts rollout must separately configure both deployments and verify Prometheus scraping and delivery to the tracing collector.
This change does not configure deployments, dashboards, alert rules, or SLO emission.
The `alerts-product` SLO area remains reserved without changes to shared SLO handling or workflow inputs.
