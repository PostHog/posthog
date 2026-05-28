# Design — platform LLM analytics emission

**Status:** v0 (runner captures via standard PostHog ingestion) ✅ shipped; v1 (signed origin marker for billing exclusion) not yet built. **Owner:** ben.

This is `self-healing-agents.md` §3.1 broken out into its own plan
because the emitter is shipping ahead of the rest of self-healing —
the moment agents start invoking models in production we want every
turn captured in LLM Analytics.

We emit directly from the runner rather than rely on PostHog's
llm-gateway. The gateway already emits `$ai_generation` events (see
[`services/llm-gateway/src/llm_gateway/callbacks/posthog.py`](../../../services/llm-gateway/src/llm_gateway/callbacks/posthog.py))
but it covers only the gateway code path — agents going direct to
Anthropic / OpenAI get nothing, and it never sees tool calls. Owning
emission in the runner means uniform coverage regardless of provider
plus `$ai_span` for tools.

## 1. Problem

`agent_session.conversation` JSONB already records every model call
the runner makes. That's enough for one-session debug — useless for
fleet-level questions:

1. **What's my failure rate per agent? Per tool?** Aggregation needs
   `ai_events` rows in ClickHouse keyed on `$agent_application_id` +
   `$agent_revision_id`. Today we have nothing in that shape.
2. **Where's my latency budget going?** P95 model latency vs tool
   latency requires `$ai_generation` + `$ai_span` events with the
   shared `$ai_trace_id` linkage.
3. **What did this turn cost?** Cost lives on `agent_session.usage_total`
   (per-turn-cost-capture.md) but only at the session granularity. Per-
   call rollup needs per-event cost on `ai_events`.
4. **PostHog's existing LLM Analytics product is dark for agents.**
   `posthog/products/llm_analytics/` is wired against `ai_events`. With
   the runner not emitting, our own product doesn't surface our own
   agent traffic.

## 2. Why standard /capture, not a dedicated topic

The first iteration of this plan wrote to a dedicated Kafka topic
(`agent_ai_events`) with a future consumer that would forward into
the canonical pipeline with a "free" billing flag attached. That was
over-engineering: the dedicated topic adds infrastructure (a new
consumer to build + run) for a benefit that's achievable as a
property marker at billing time.

The shipped design uses **standard PostHog ingestion**:

```text
runner ──posthog-node──▶ /capture ──ingestion──▶ clickhouse_ai_events_json ──▶ ai_events (CH)
```

Same path the llm-gateway uses (`posthoganalytics.capture()` →
`/capture`). Events show up in LLM Analytics with zero new infra.

The trade-off: emission becomes one network call per turn instead of
one Kafka produce. `posthog-node` batches by default (`flushAt: 20`,
`flushInterval: 10s`), so the actual HTTP traffic is far lower than
event count. We wire `client.shutdown()` into the runner's clean exit
so the final batch drains before pods recycle.

## 3. Event shape

Two event kinds, names match PostHog's existing `ai_events` table
schema ([`posthog/models/ai_events/sql.py`](../../../posthog/models/ai_events/sql.py)).

### 3.1 `$ai_generation` — one per pi-ai call

Emitted in [`run-turn.ts`](../../../services/agent-runner/src/loop/run-turn.ts)
right after `pi.invoke()` returns (or throws). Properties:

| Property                                                                             | Source                                                                                                          |
| ------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------- |
| `$ai_trace_id`                                                                       | `session.id` (all turns of one session share a trace)                                                           |
| `$ai_span_id`                                                                        | `<session>:gen:<turn>` (via `generationSpanId`)                                                                 |
| `$ai_model`                                                                          | `result.model`                                                                                                  |
| `$ai_provider`                                                                       | `result.provider`                                                                                               |
| `$ai_input`                                                                          | `context.messages` (heavy column)                                                                               |
| `$ai_output_choices`                                                                 | `result.content` (heavy column)                                                                                 |
| `$ai_input_tokens` / `$ai_output_tokens`                                             | `result.usage.input` / `result.usage.output`                                                                    |
| `$ai_cache_read_input_tokens` / `$ai_cache_creation_input_tokens`                    | Anthropic prompt-cache splits                                                                                   |
| `$ai_latency`                                                                        | Wall-clock seconds for the pi-ai call                                                                           |
| `$ai_total_cost_usd`                                                                 | `result.usage.cost.total`, **suppressed on the gateway path** because pi-ai's numbers are client-side estimates |
| `$ai_stop_reason`                                                                    | `result.stopReason`                                                                                             |
| `$ai_is_error` / `$ai_error`                                                         | Set on the throw branch                                                                                         |
| `$agent_application_id` / `$agent_revision_id` / `$agent_session_id` / `$agent_turn` | Constant per-session / per-turn                                                                                 |
| `team_id`                                                                            | `session.team_id` — stamped explicitly for cheap per-team rollups                                               |
| `$ai_origin: 'agent_platform_runner'`                                                | The future signed-origin marker — see §5                                                                        |

### 3.2 `$ai_span` — one per tool dispatch

Emitted in [`dispatch-one.ts`](../../../services/agent-runner/src/loop/dispatch-one.ts).
Chains to the generation that emitted the toolCall via `$ai_parent_id`.

| Property                              | Source                                                                |
| ------------------------------------- | --------------------------------------------------------------------- |
| `$ai_trace_id`                        | `session.id`                                                          |
| `$ai_span_id`                         | `<session>:tool:<turn>:<tool_call_id>`                                |
| `$ai_parent_id`                       | Generation's `span_id`                                                |
| `$ai_span_name`                       | Tool id (internal — not the provider-safe form)                       |
| `$ai_tool_call_id`                    | pi-ai's `ToolCall.id`                                                 |
| `$ai_input_state`                     | `call.arguments` (after nonce substitution — never plaintext secrets) |
| `$ai_output_state`                    | Tool result, truncated upstream by dispatcher                         |
| `$ai_latency`                         | Tool execution wall-clock, seconds                                    |
| `$ai_is_error` / `$ai_error`          | From `dispatchTool` outcome                                           |
| `$agent_*` / `team_id` / `$ai_origin` | Same as `$ai_generation`                                              |

## 4. distinct_id strategy

Composite, with fallback:

- `<principal.kind>:<principal.id>` when the session has a known
  principal (`pat:user-7`, `slack:T01:U01`, `internal:...`).
- `agent:<application_id>` for anonymous public-agent sessions.

This matches `llm-gateway`'s `resolve_distinct_id(auth_user, end_user_id)`
contract and lets the LLM Analytics surface slice both per-user and
per-agent without joining session metadata.

## 5. Future signed origin marker

Today every event carries `$ai_origin: 'agent_platform_runner'`. The
billing intent is "platform-internal LLM use shouldn't bill customers
for PostHog's own runs" — events with that marker should be excluded
from billable usage at meter time.

**The current unsigned marker is forgeable.** Anyone with the
destination project's PostHog API key can capture
`{event: '$ai_generation', properties: {$ai_origin:
'agent_platform_runner', $ai_total_cost_usd: -10000}}` and shift their
billing. That's fine while we don't actually use the marker for billing
decisions; it stops being fine the moment we do.

**The intended evolution** is a **signed origin marker**:

1. The runner holds a platform-internal HMAC secret (deploy via the
   same channel as `AGENT_PREVIEW_SECRET`).
2. On each emission, compute
   `$ai_origin_signature = HMAC_SHA256(secret, canonical_form(event))`
   where `canonical_form` covers the billing-relevant fields
   (`team_id`, `$ai_total_cost_usd`, `$ai_total_tokens`, `$ai_trace_id`,
   `timestamp`).
3. The billing meter verifies `$ai_origin === PLATFORM_ORIGIN && signature
matches` before excluding the event. Forgeries fail signature
   verification and are billed normally.
4. Rotation is handled the same way as `AGENT_PREVIEW_SECRET`: the
   verifier accepts a small set of recent secrets during overlap, the
   emitter signs with the current one.

**Why not implement it now:** the billing meter that would honour
the signature doesn't exist yet, and the canonical-form spec needs to
stay in lockstep with whatever the verifier reads from ClickHouse. We
ship the unsigned marker as the placeholder so the property is
present from day one; the signing extension is purely additive
(`$ai_origin_signature` slot is reserved).

## 6. Rollout

**v0 — runner captures via standard ingestion.** ✅ shipped.

- `AnalyticsSink` interface + `InMemory` / `Noop` / `Capture` impls in
  agent-shared, mirroring `LogSink`.
- `$ai_generation` emission in `run-turn.ts` (success + throw paths).
- `$ai_span` emission in `dispatch-one.ts`.
- `CaptureAnalyticsSink` wraps `posthog-node`, lazy-imports on first
  `connect()`, drains on `shutdown()`.
- Config knobs: `POSTHOG_ANALYTICS_API_KEY` + `POSTHOG_ANALYTICS_HOST`.
  Unset → `NoopAnalyticsSink` (harness / CI). Local `hogli` dev sets
  them on the agent-runner mprocs entry pointing at the same target
  the llm-gateway uses (`phc_localposthogprojecttoken` /
  `http://localhost:8010`), so a fresh `hogli` start has agent traffic
  showing up in the local PostHog project's LLM Analytics view.
- `$ai_origin: 'agent_platform_runner'` stamped on every event as the
  placeholder for the future signed-origin work.

**v1 — signed origin marker + billing-side verifier.** Not yet built.

- See §5. Owner / timeline TBD. Depends on the billing meter knowing
  to look for `$ai_origin_signature`.

**v2 — backfill from `agent_session.conversation`.** Optional.

- Sessions that ran in v0 (or in environments without an API key)
  have all the information needed to reconstruct events from
  `conversation` + `usage_total`. A one-shot janitor endpoint could
  capture historical events.

## 7. Dependencies + what this enables

**Hard depends on:** nothing. Pure additive change.

**Composes with:**

- [`per-turn-cost-capture.md`](per-turn-cost-capture.md) — token /
  cost numbers attached to each generation come from the same
  `result.usage` block the per-turn accumulator reads.
- [`streaming-and-reasoning.md`](streaming-and-reasoning.md) — when
  the runner switches to `pi.stream()`, `$ai_generation` emits at the
  stream's terminal `end` event; deltas don't produce extra events.

**What this unblocks:**

- LLM Analytics surface lighting up for agent traffic.
- `self-healing-agents.md` §3 — the introspection loop reads
  `ai_events`, which now contains real rows from agent sessions.
- Per-agent / per-tool latency + cost rollups in dashboards
  (`agent_session_daily_summary` views in self-healing §3.2).
