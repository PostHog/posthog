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

## Telemetry

Both queues report through `products/alerts/backend/temporal/metrics.py`:

| Signal          | Where to read it                                                                          |
| --------------- | ----------------------------------------------------------------------------------------- |
| Metrics         | The worker's `--metrics-port`, under the `alerts_product_activity_` prefix                |
| Structured logs | One record for each activity, with `task_queue`, `activity_type`, and `workflow_id`       |
| Traces          | OTel spans, force-enabled for both queues, so a tick and its delivery child are one trace |

`alerts_product_activity_execution_latency` carries `task_queue`, `activity_type`, and `status`, so one query separates the two fleets:

```promql
rate(alerts_product_activity_execution_latency_count{status="FAILED"}[5m])
```

Queue wait is Temporal's own `temporal_activity_schedule_to_start_latency`.
It rises when the fleet cannot keep up with the queue, and the activity duration does not show that.
Both queues widen its buckets to 30 minutes, because the default boundaries stop at 10 seconds.

Traces need `OTEL_SERVICE_NAME`.
Without it the worker starts, but it sends no spans.

This registration does not create schedules or deploy workers.
Schedule registration will set the evaluation workflow's 50-second execution timeout separately.
