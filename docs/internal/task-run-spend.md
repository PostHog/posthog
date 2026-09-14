# Task-run spend

## Request flow

The agent server reports gateway request IDs through the existing task-run PATCH API.
It uses `state_append: {"gateway_request_ids": "<request-id>"}`, alongside the existing token-usage reporting mechanism.
The backend validates and deduplicates IDs under the run's row lock.
This request performs no gateway lookup and accepts no monetary amount.

The task workflow's existing event-relay activity processes pending IDs on its 30-second heartbeat.
The lookup runs in a worker thread, outside the stream handler and outside database transactions.
It calls the unchanged Go gateway endpoint `GET /v1/usage/{request_id}` with `SANDBOX_AI_GATEWAY_MINT_KEY`.
The worker reads the existing decimal `cost_usd` response and stores the canonical result in protected run state.

The existing cleanup activity stops the agent, processes its final reported IDs, closes the sandbox ledger, and persists the spend projection.
There is no new reporting endpoint, database table, migration, workflow signal, or workflow timer.
No gateway change or additional sandbox permission is required.

## Scope and rollout

`TASKS_GATEWAY_ACCOUNTING_ENABLED` defaults to false.
The worker enables accounting only for an already Go-routed cloud run and injects `TASK_RUN_GATEWAY_ACCOUNTING=1` into its agent environment.
The existing Go-product routing settings still select the population.
Deploy the backend and compatible agent image before enabling the setting.

Python-routed runs, Pi's existing Python route, local runs, and historical token usage remain unavailable.
This change does not migrate callers or alter customer charges, quotas, or Signals behavior.
The existing adapter token-count telemetry stays separate from authoritative money.

The loopback HTTP observer exists because SDK subprocesses do not expose every response header to the agent server.
It routes Claude and Codex requests, including their subprocess and subagent calls, to a fixed gateway target.
It preserves streamed bytes and reports `X-Request-ID` as soon as headers arrive.
Model-list and token-count helper calls do not create spend entries.
The observer never queries usage or calculates prices.

## Consumer interface

Cross-product consumers use the Tasks facade:

```python
from products.tasks.backend.facade.billing import (
    TaskRunSpend,
    get_task_run_spend,
    get_task_spend,
)

run_spend = get_task_run_spend(team_id=team_id, run_id=run_id)
task_spend = get_task_spend(team_id=team_id, task_id=task_id)
```

Within Tasks, `TaskRun.get_current_spend()` returns the same contract.
The getter reads persisted receipts and sandbox records, then refreshes `TaskRun.state["spend"]`.
It never queries the gateway or retrospective analytics events.

| Field            | Meaning                                         |
| ---------------- | ----------------------------------------------- |
| `token_cost`     | Integer USD cents, or `None` when unavailable   |
| `compute_cost`   | Integer USD cents, or `None` when unavailable   |
| `token_status`   | `unavailable`, `partial`, `current`, or `final` |
| `compute_status` | `unavailable`, `current`, or `final`            |
| `is_final`       | Both components are final                       |

A partial token cost is a known lower bound.
If no requested receipt is available, its cost is `None`, not zero.
Consumers must check the status as well as the amount.

The task total includes all runs, including failed and cancelled attempts.
It sums exact source amounts before rounding, not rounded run cents.
Unknown and partial states propagate to the task total.
These amounts describe factual spend, not customer charges.
Signals consumers must retain their existing charging policy rather than charge every internal attempt.

## Precision and compute

Tasks parses the gateway's decimal USD string without floating-point arithmetic.
It stores the six-decimal source amount as integer micro-USD and sums each unique request ID once.
It converts the total to cents with `ROUND_HALF_EVEN`.
The gateway amount includes its own model, cache, routing, and fee pricing; Tasks does not reconstruct those prices from token counts.

Compute uses `SandboxSession` and the existing versioned rate calculator.
It uses attribution time, resource shape, burstable resource floors, recorded end time, and existing TTL rules.
Unclaimed prewarm time contributes zero attributed compute.
Missing sandbox records produce unavailable compute.
Open sessions keep compute current.
Closed-session snapshots retain decimal source precision, so a later rate change does not reprice completed sessions.

The existing calculator clamps Hogland sessions to `ttl_expires_at`, although Hogland treats this as an idle timeout.
Raw usage aggregation handles that distinction differently.
This slice preserves the calculator and customer billing policy.

## Trust and completion

Only the task-bound agent may append request IDs or set the reporting-complete marker.
Ordinary clients cannot modify these fields, `spend`, or `_spend_accounting` through merge, append, or removal.
Only worker code writes priced receipts and enables accounting.

Request-to-run attribution trusts the task-bound agent.
The existing gateway API checks the funding team but does not prove that a request belongs to one particular run.
No new credential-identity contract is assumed.
The server-held standard credential performs usage reads; the sandbox's scoped token does not need that permission.

The agent sets `gateway_usage_complete` to false at startup.
It sets the marker to true only after streams stop and all captured IDs reach the backend.
Any new ID resets the marker to false.
A missing request ID or failed report prevents complete accounting.
Token spend becomes final only when the run is terminal, reporting is complete, and all reported IDs have priced responses.

The worker retries missing or failed lookups on later heartbeats and during cleanup.
Each pass has a bounded batch and time budget.
Pending reads rotate so a missing receipt cannot block later IDs.
A missing response never means zero: the current gateway does not retain a debit for genuine zero cost, so such requests can remain incomplete.
A crash before an ID reaches Django, or an outage beyond final cleanup, can also leave incomplete spend.
There is no separate reconciliation service or historical backfill.

## Verification before wider rollout

Start with a small existing Go-routed population.
Compare the protected receipt map with the gateway's usage responses and confirm that duplicate reports do not add cost.
Check that live runs update during execution and clean runs become final after cleanup.
Inspect `task_gateway_usage.*` and relay accounting logs for pending lookups and processing failures.
Confirm that unavailable receipts and interrupted reporters remain partial.

Local tests cover the HTTP observer, existing PATCH API, worker processing, precision, and compute attribution.
A live provider-to-sandbox test and production rollout checks remain required before broader enablement.
