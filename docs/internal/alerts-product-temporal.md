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

No schedule exists yet, so start an evaluation run by hand.
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

Both workflows accept an empty `AlertsProductInputs` dataclass and run an empty activity with no I/O.
Each activity has a 10-second start-to-close timeout, a 30-second schedule-to-close timeout, and at most three attempts.
Evaluation starts one delivery child on the delivery queue and waits for confirmation that it started, without waiting for completion.
The child ID includes the evaluation run ID, so repeated runs of the same evaluation workflow ID start different children.
`ParentClosePolicy.ABANDON` lets delivery continue after evaluation closes.
Delivery has a one-minute execution timeout for the noop.
Real notification delivery guarantees remain undecided.

This registration does not create schedules or deploy workers.
Schedule registration will set the evaluation workflow's 50-second execution timeout separately.

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
