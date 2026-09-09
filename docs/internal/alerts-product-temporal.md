# Alerts noop workers

The Alerts product registers two queues through `products/alerts/backend/facade/temporal.py` and the shared `start_temporal_worker` command:

| Setting in `posthog/settings/temporal.py` | Queue                                  | Workflow                   |
| ----------------------------------------- | -------------------------------------- | -------------------------- |
| `ALERTS_PRODUCT_EVALUATION_TASK_QUEUE`    | `alerts-product-evaluation-task-queue` | `alerts-product-check-due` |
| `ALERTS_PRODUCT_DELIVERY_TASK_QUEUE`      | `alerts-product-delivery-task-queue`   | `alerts-product-deliver`   |

These queue names are hardcoded and stay separate even with `DEBUG=True`.
Start a worker for each queue with the command's `--task-queue` option.
The shared development worker does not poll these queues.
See [Temporal development guidance](../../posthog/temporal/README.md) for worker setup.

Both workflows accept an empty `AlertsProductInputs` dataclass and run an empty activity with no I/O.
Each activity has a 10-second start-to-close timeout, a 30-second schedule-to-close timeout, and at most three attempts.
Evaluation starts one delivery child on the delivery queue and waits for confirmation that it started, without waiting for completion.
The child ID includes the evaluation run ID, so repeated runs of the same evaluation workflow ID start different children.
`ParentClosePolicy.ABANDON` lets delivery continue after evaluation closes.
Delivery has a one-minute execution timeout for the noop.
Real notification delivery guarantees remain undecided.

This registration does not create schedules or deploy workers.
Schedule registration will set the evaluation workflow's 50-second execution timeout separately.
