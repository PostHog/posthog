# Task-run spend

## Stored state

The spend feature adds three fields to `TaskRun.state`:

```json
{
  "unprocessed_request_ids": ["req-b"],
  "token_spend": {
    "model-a": {
      "provider-a": {
        "spend_microusd": 15200,
        "request_ids": ["req-a"]
      }
    }
  },
  "compute_spend": 2
}
```

`unprocessed_request_ids` is the queue of reported IDs awaiting gateway pricing.
Successful processing removes an ID from this queue.
Missing or failed responses leave the ID queued for a later pass.
An empty queue means no reported IDs are awaiting processing; it does not prove that a run has ended or that every request was reported.

`token_spend` groups recorded gateway spend by model, then provider.
Each bucket stores an integer micro-USD sum and its processed request IDs.
The IDs prevent a retried agent report or overlapping worker pass from adding spend twice.
There is no copied token-count or settlement metadata.
One cent is 10,000 micro-USD.

`compute_spend` is an integer-cent amount derived from the existing sandbox ledger and rates.
It is `null` when the run has no applicable ledger data.
There is no additional accounting wrapper, completion flag, per-session spend snapshot, or finality field.
Existing run metadata and adapter token-count telemetry remain separate.

## Data flow

1. A small agent-server HTTP observer captures `X-Request-ID` from each Go gateway response.
2. The agent appends it through the existing task-run PATCH API with `state_append.unprocessed_request_ids`.
3. Django validates the ID and appends it under the run lock, unless it is already pending or processed.
4. The existing Temporal relay activity reads a bounded batch on its 30-second heartbeat.
5. The worker queries `GET /v1/usage/{request_id}` through the unchanged gateway API.
6. Under one run lock, it increments the model/provider bucket, records the processed ID, and removes the pending ID.

Gateway calls happen outside database locks and outside the event stream handler.
Unavailable responses rotate to the end of the queue so they cannot block later IDs.
The existing cleanup activity flushes the agent's reports, processes pending IDs, closes the sandbox ledger, and refreshes compute spend.
There is no new endpoint, database model, migration, workflow signal, or workflow timer.

The observer covers Claude and Codex SDK subprocesses and subagent requests.
It forwards streamed bytes unchanged and retries only request-ID delivery.
It does not query usage or calculate money.
Model-list and token-count helper calls do not enter the spend queue.

## Consumer interface

State contains the token breakdown. The Tasks facade returns totals in integer cents:

```python
from products.tasks.backend.facade.billing import (
    TaskRunSpend,
    get_task_run_spend,
    get_task_spend,
)

run_spend = get_task_run_spend(team_id=team_id, run_id=run_id)
task_spend = get_task_spend(team_id=team_id, task_id=task_id)

# Both values are integer cents, or None when the source is unavailable.
run_spend.token_spend
run_spend.compute_spend
```

Within Tasks, `TaskRun.get_current_spend()` returns the same two-field contract.
It reads recorded token spend and the existing sandbox ledger; it never queries the gateway or analytics events.
It refreshes the persisted `compute_spend` value.

The token total includes only requests already processed.
Pending IDs can therefore mean that more spend remains to be recorded.
An initialized run with no processed spend returns zero; an untracked or local run returns `None` for token spend.
Consumers can inspect the pending queue, but the contract makes no completeness or finality claim.

Task-level aggregation includes all runs, including failed and cancelled attempts.
It sums exact source amounts across model/provider buckets and runs before half-even rounding to cents.
These figures describe recorded spend, not customer charges.
Signals consumers must retain their own charging policy rather than charge every internal attempt.

## Pricing and trust

The gateway's existing wire field is named `cost_usd`.
Tasks interprets it as spend, parses its decimal string exactly, and retains micro-USD precision until totals are rounded.
The model and provider keys come from that response.
Tasks does not derive spend from SDK token counts or duplicate gateway prices.

Compute uses `SandboxSession`, attribution timestamps, resource shape, burstable resource floors, and versioned rate cards.
Unclaimed prewarm time contributes zero attributed compute.
There is no separate stored snapshot of each sandbox session's spend.
The existing calculator's Hogland TTL behavior remains unchanged, including its difference from raw usage aggregation.

Only the server initializes the pending queue and token-spend map for a tracked run.
Only its task-bound agent can append IDs to the initialized queue.
Ordinary clients cannot change the queue; neither ordinary clients nor the agent can forge token or compute spend.
Request-to-run attribution trusts the task-bound agent, because the unchanged gateway API checks the funding team rather than an exact task run.
Gateway usage reads use the worker-held standard credential; sandbox permissions do not expand.

## Rollout and limits

`TASKS_GATEWAY_ACCOUNTING_ENABLED` defaults to false.
The worker injects `TASK_RUN_GATEWAY_ACCOUNTING=1` only for already Go-routed cloud runs after initializing their state.
Deploy the backend and compatible agent image before enabling it for a small population.
Python-routed runs, Pi's existing Python route, local runs, and historical token usage do not participate.

The existing gateway may return no usage row for genuine zero spend.
Such IDs remain queued rather than being assumed free.
A crash before an ID reaches Django or an outage beyond the last cleanup attempt can also leave spend unrecorded.
There is no separate reconciliation service or historical backfill.

Before wider rollout, compare model/provider buckets with gateway usage responses and check pending queues and `task_gateway_usage.*` logs.
Local tests cover reporting, processing, rounding, duplicate handling, resume, and compute attribution.
A live provider-to-sandbox test remains required.
