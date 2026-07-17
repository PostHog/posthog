# Generic LLM workflow step

An `llm` workflow action that sends a prompt to an LLM and stores the response in a workflow
variable. Built on park-and-wake-by-id so a long-running model call never holds a workflow worker:
the step dispatches a request to a dedicated fleet, parks the Cyclotron job, and is woken by id when
the completion lands (or a timeout backstop fires).

## Components

| File | Role |
| --- | --- |
| `../hogflows/actions/llm.ts` | The step handler: render prompt → dispatch → park → resume (result / error branch / timeout). |
| `llm-request-producer.ts` | Produces the dispatch to the `cdp_llm_requests` Kafka topic (keyed by team). |
| `../../consumers/cdp-llm-executor.consumer.ts` | The executor fleet: consume → call gateway → spill → wake. |
| `llm-executor-core.ts` | Gateway call + bounded retry + wake, factored out of the consumer for testing. |
| `llm-gateway.client.ts` | Talks to the PostHog LLM gateway (`POST /v1/chat/completions`). |
| `llm-wake.ts` | The guarded wake: `UPDATE cyclotron_jobs SET scheduled = NOW() … WHERE status = 'available'`. |
| `llm-blob-store.ts` / `llm-spill.ts` | Spill oversized completions to object storage; keep only a ref in state. |

## Configuration

The dispatch topic (`cdp_llm_requests`) is auto-created by the consumer (`CONSUMER_AUTO_CREATE_TOPICS`
defaults to true). Run the executor by enabling the `cdp-llm-executor` capability (on by default in
dev). Env knobs:

| Env var | Default | Purpose |
| --- | --- | --- |
| `CDP_LLM_GATEWAY_URL` | _(unset)_ | Base URL of the LLM gateway. Unset → every call fails to the timeout branch. |
| `CDP_LLM_GATEWAY_TOKEN` | _(empty)_ | Bearer token (a personal API key the gateway accepts). Per-team credential resolution is a follow-up. |
| `CDP_LLM_GATEWAY_REQUEST_TIMEOUT_MS` | `300000` | Per-call HTTP timeout. Reasoning models need this raised; the step's `max_wait_duration` is the outer backstop. |
| `CDP_LLM_S3_ENDPOINT` | `http://localhost:8333` (SeaweedFS) | Object storage for spilled completions. |
| `CDP_LLM_S3_BUCKET` / `_REGION` / `_ACCESS_KEY_ID` / `_SECRET_ACCESS_KEY` | `posthog` / `us-east-1` / `any` / `any` | S3 connection for the spill store. |

## Validating the RFC

The RFC is a scalability design; validation runs bottom-up from cheap unit tests to a real-stack
scale check. Each RFC claim below maps to the concrete thing that proves it.

### 1. Unit (no infra) — the state machine and race guards

```bash
hogli test nodejs/src/cdp/services/llm/
hogli test nodejs/src/cdp/services/hogflows/actions/llm.test.ts
```

- **Park-and-wake state machine** → `actions/llm.test.ts`: entry dispatches + parks; a written
  completion advances; an error/timeout with a wired branch routes to it, without one throws to
  `on_error`.
- **Wake is race-safe** → `llm-wake.test.ts`: `woken` only when `status='available'` and the step +
  nonce match; `missed` when the timeout already flipped the row; `stale` when the step advanced.
- **Response-by-reference** → `llm-spill.test.ts`: an oversized completion is spilled and only a
  compact ref (< 5KB) is kept for state.
- **Retry / idempotency** → `llm-executor-core.test.ts`: the `(jobId, actionId, nonce)` idempotency
  key, retriable-vs-terminal handling, and error-wake on give-up.

### 2. Integration (real Cyclotron Postgres) — the wake against a live table

`llm-wake.integration.test.ts` parks a real `cyclotron_jobs` row and proves `wakeParkedLlmJob` pulls
it forward with the completion, and that the `missed` (timeout won) and `stale` (advanced) races
behave. It runs in the main test group (which has `test_cyclotron_node`) and skips loudly if that DB
is absent. To run it locally:

```bash
pnpm --filter=@posthog/nodejs setup:test        # brings up + migrates test_cyclotron_node
hogli test nodejs/src/cdp/services/llm/llm-wake.integration.test.ts
```

### 3. End-to-end (local stack) — a workflow actually calls an LLM and continues

1. Start the stack (`hogli start`) and the LLM gateway (`services/llm-gateway`); set
   `CDP_LLM_GATEWAY_URL` + `CDP_LLM_GATEWAY_TOKEN`.
2. Build a workflow with an **AI → LLM prompt** step (prompt referencing `{{ event.properties.x }}`),
   then a step that reads `{{ variables.llm_response }}`.
3. Fire the trigger event. Watch the run: it should park, then advance once the completion lands.

Observe the park → wake transition directly (Cyclotron DB):

```sql
-- while parked: scheduled is in the future, status available, action_id = the llm step
SELECT id, status, scheduled, action_id FROM cyclotron_jobs WHERE action_id = '<llm-action-id>';
-- after the executor wakes it: scheduled jumps to ~now; the next dequeue advances the run
```

### 4. Scale — the RFC's core claims

Fan out a broadcast (or a high-frequency trigger) hitting the LLM step across many executions, and
measure:

| RFC claim | How to observe it |
| --- | --- |
| Parking frees workers (throughput invariant to LLM latency) | Workflow-worker dequeue rate / lag stays flat as LLM latency rises. The workflow worker touches the step for ms; the executor fleet holds the minutes. |
| Executor fleet sized by concurrency (`rate × duration`) | `cdp_llm_executor_requests_received` rate × mean call duration ≈ in-flight count; CPU stays near-idle; scale by replicas. |
| `cyclotron_jobs` stays small | Spilled completions leave only a ref in `state`: `SELECT max(length(state)) FROM cyclotron_jobs WHERE action_id = '<llm-action-id>'` stays small even for large outputs; object-storage object count rises instead. |
| Wake is O(1) and cheap | `cdp_llm_executor_wake_outcome{outcome="woken"}` vs `"missed"` (timeout-won races); wake is a single primary-key UPDATE. |
| Graceful degradation under provider/gateway outage | Kill the gateway: `cdp_llm_requests` lag grows, jobs sit cheaply parked, and past `max_wait_duration` they take the error/timeout branch. No worker exhaustion. |

## Known limitations (deferred)

- Prompt templating is liquid-only (hog-bytecode templating is a follow-up).
- Per-team gateway credential resolution is stubbed to a single token.
- Per-workflow / per-team LLM rate + budget caps (RFC §4) are not yet implemented; spend control
  currently relies on the gateway's admission control.
- Human-in-the-loop steps share this primitive but are a separate iteration.
