# Task-run spend

## Scope

Go-gateway cloud runs can record current and final spend without querying analytics events.
The agent server records request intent before dispatch, records the gateway request ID at response headers, and requests settlement after the stream ends.
The Tasks backend retrieves the receipt with its server-held gateway credential.
It verifies the receipt against a scoped credential minted for that exact run.

The Python gateway, Pi's existing Python route, local runs, and historical runs do not participate in token accounting.
Their token cost is unavailable, not zero.
The existing token-count telemetry remains separate.

## Consumer interface

Import the contract through the Tasks facade:

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
The getter reads durable request and sandbox records, then updates the protected `TaskRun.state["spend"]` projection.
It makes no gateway or analytics request.
Receipt retrieval occurs during execution and cleanup.

`TaskRunSpend` contains:

| Field            | Meaning                                                                   |
| ---------------- | ------------------------------------------------------------------------- |
| `token_cost`     | Gateway cost in integer USD cents, or `None` when unavailable             |
| `compute_cost`   | Attributed resource cost in integer USD cents, or `None` when unavailable |
| `token_status`   | `unavailable`, `partial`, `current`, or `final`                           |
| `compute_status` | `unavailable`, `current`, or `final`                                      |
| `is_final`       | Both components are final                                                 |

A partial token cost is a lower bound when some receipts are known.
If no receipt is known and one is pending, the cost is `None`.
A covered epoch with no requests has a known zero cost.
Consumers must check the status, not only the amount.
A terminal task status does not imply final accounting.

`get_task_spend` includes every run under the task, including failed and cancelled attempts.
It sums source precision across runs before rounding, rather than summing rounded run cents.
An unavailable component propagates to the corresponding task component.
A partial token status also propagates.

These are factual costs, not customer charges.
The gateway cost includes any fees that the gateway includes in its settled amount.
The contract does not decide which attempts a customer pays for.
Signals consumers must apply their existing charging policy separately.
No invoice, quota, credit, Signals grouping, or handoff code uses this new contract in this change.

## Precision and duplicate reports

Gateway receipts store integer micro-USD, using the gateway's existing settlement rounding.
One cent is 10,000 micro-USD.
Tasks sums receipts by gateway request ID, then rounds the total to cents with `ROUND_HALF_EVEN`.
Two different requests with equal prices both count.
Two attempts that replay the same gateway request count once.

Credentials, process epochs, and request intents have durable records.
A resumed run can use a new scoped credential without losing receipts from an earlier credential.
All mutations lock the run before they read or update its projection.
A gateway lookup never holds that lock.
Repeated and out-of-order reports cannot replace a request's immutable binding or add its cost twice.

## Compute

Compute uses `SandboxSession` and the existing versioned `calculate_sandbox_compute_cost` rates.
It uses the attribution start, resource shape, burstable resource floors, session end, and existing TTL rules.
It does not use the task's elapsed wall time as the resource ledger.
Unclaimed prewarm time contributes zero attributed compute.
Internal origins are not excluded from factual cost.
Existing customer billing filters remain unchanged.

A missing sandbox ledger produces unavailable compute.
An open ledger keeps compute current.
Closed session costs retain exact decimal source snapshots in backend-private state, so later rate changes cannot reprice those sessions.
Public monetary totals remain integer cents.
A resumed epoch reopens finality, while old session snapshots and token receipts remain available.

The existing rate calculator clamps Hogland sessions to `ttl_expires_at`, although Hogland uses an idle timeout.
Raw sandbox usage handles that distinction differently.
This slice retains the rate calculator's behavior and does not change compute charging policy.

## API and trust

The agent calls `POST /api/projects/{team}/tasks/{task}/runs/{run}/gateway_usage/`.
The operations are `start`, `request`, `settle`, and `finish`.
The endpoint requires the existing task-bound sandbox OAuth identity.
It checks the URL task, run, and team together.
Ordinary users cannot submit authoritative spend.
Normal run-state PATCH, append, and remove operations cannot alter `spend` or `_spend_accounting`.

The sandbox submits identifiers, never prices.
The backend calls the existing Go endpoint `GET /v1/usage/{request_id}` with `SANDBOX_AI_GATEWAY_MINT_KEY`.
The receipt must contain a matching `request_id`, trusted `credential_id`, integer `cost_microusd`, and settlement timestamp.
Scoped gateway tokens remain unable to read usage.
No broad gateway credential enters the sandbox.

The loopback proxy gives Claude and Codex child processes a local credential.
It retains the real scoped bearer in agent-server memory and forwards only to the configured gateway.
Helper model-list and token-count calls do not create spend intents.

## Completion and recovery

The proxy stops new requests, aborts active streams, and drains its reports before sealing the epoch.
Cleanup stops the agent and retries a bounded set of known pending request IDs.
It closes the sandbox ledger and persists spend before stream completion.
A failed provider teardown cannot produce final compute for an accounting-enabled run.
Terminal status updates also refresh the projection.

A missing receipt, failed lookup, missing request ID, or interrupted epoch never becomes a final zero.
Gateway settlement recovery can produce a delayed receipt.
Known pending request IDs remain durable for another cleanup retry.
A process lost before its request ID was persisted remains incomplete.
There is no automatic reconciliation sweep in this slice.
A long gateway outage after the final cleanup can therefore require another reconciliation attempt.

## Rollout

1. Deploy the [gateway receipt changes](https://github.com/PostHog/ai-gateway/pull/481) and migration first.
2. Verify that a standard credential can retrieve a scoped request's credential identity and exact cost.
3. Deploy the Tasks migration, backend, and compatible agent image.
4. Enable `TASKS_GATEWAY_ACCOUNTING_ENABLED` for a small existing Go-routed population.
5. Inspect `state.spend`, pending request records, and the `task_gateway_usage.*` logs.
6. Confirm that clean terminal runs become final and unknown receipts remain partial.
7. Confirm that aggregate costs equal unique gateway receipts plus the attributed sandbox rate calculation.

The setting defaults to false.
The worker injects `TASK_RUN_GATEWAY_ACCOUNTING=1` only after credential registration.
The existing Go-product routing settings still select the population.
Do not enable the marker on an old agent image that does not observe requests.
Disable the setting to stop enrolling new runs; let already-enrolled runs finish with their existing marker.

The local tests use mock model streams and receipt responses, plus real database tests for the gateway ledger.
A live provider-to-sandbox test and production rollout verification remain required before enabling this outside a test population.
