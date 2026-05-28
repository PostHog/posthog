# Design — platform LLM analytics emission

**Status:** v0 (runner emits to dedicated Kafka topic) ✅ shipped; v1 (consumer + free-flag billing logic) not yet built. **Owner:** ben.

This is `self-healing-agents.md` §3.1 broken out into its own plan
because the emitter is shipping ahead of the rest of self-healing —
the moment agents start invoking models in production we want every
turn captured in LLM Analytics.

We chose to emit directly from the runner rather than rely on PostHog's
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

## 2. Why a dedicated Kafka topic

Two options for landing events:

- **(A) Write straight into `clickhouse_ai_events_json`.** Existing
  topic, fed by PostHog's standard ingestion pipeline. Zero new infra.
- **(B) Write into a dedicated `agent_ai_events` topic with a future
  consumer that forwards into `clickhouse_ai_events_json`.** Lets us
  add custom logic between emit and forward without coupling to
  ingestion semantics.

We chose **B**. The reason is the **future free-flag work** (§5):
events the platform generates internally must not bill customers for
PostHog's own LLM use. The cleanest place to mark "this run was
platform-internal, don't count it for billing" is the forwarder
consumer — it can tag, drop, or rewrite as the billing model
evolves without touching the runner or the canonical topic.

This mirrors the `log_entries` pattern
([`log-sink.ts`](../../../services/agent-shared/src/runtime/log-sink.ts)):
runner owns its dedicated producer, downstream owns the forward path,
no shared topic with the rest of PostHog ingestion.

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
| `$ai_origin: 'agent_platform_runner'`                                                | The free-flag marker — see §5                                                                                   |

### 3.2 `$ai_span` — one per tool dispatch

Emitted in [`dispatch-one.ts`](../../../services/agent-runner/src/loop/dispatch-one.ts).
Chains to the generation that emitted the toolCall via `$ai_parent_id`.

| Property                     | Source                                                                |
| ---------------------------- | --------------------------------------------------------------------- |
| `$ai_trace_id`               | `session.id`                                                          |
| `$ai_span_id`                | `<session>:tool:<turn>:<tool_call_id>`                                |
| `$ai_parent_id`              | Generation's `span_id`                                                |
| `$ai_span_name`              | Tool id (internal — not the provider-safe form)                       |
| `$ai_tool_call_id`           | pi-ai's `ToolCall.id`                                                 |
| `$ai_input_state`            | `call.arguments` (after nonce substitution — never plaintext secrets) |
| `$ai_output_state`           | Tool result, truncated upstream by dispatcher                         |
| `$ai_latency`                | Tool execution wall-clock, seconds                                    |
| `$ai_is_error` / `$ai_error` | From `dispatchTool` outcome                                           |
| `$agent_*` / `$ai_origin`    | Same as `$ai_generation`                                              |

## 4. distinct_id strategy

Composite, with fallback:

- `<principal.kind>:<principal.id>` when the session has a known
  principal (`pat:user-7`, `slack:T01:U01`, `internal:...`).
- `agent:<application_id>` for anonymous public-agent sessions.

This matches `llm-gateway`'s `resolve_distinct_id(auth_user, end_user_id)`
contract and lets the LLM Analytics surface slice both per-user and
per-agent without joining session metadata.

## 5. Future free flag — `$ai_origin: 'agent_platform_runner'`

Every emitted event carries `$ai_origin: 'agent_platform_runner'`. The
property name is intentionally generic so the future consumer can use
it as a routing key: "events with this origin came from the platform
runner itself, decide billable vs not based on agent ownership / who
triggered the session."

**Why this is not yet implemented:**

- The billing model for platform-internal LLM use isn't decided.
- The forwarder consumer that would honour the flag doesn't exist yet
  — events sit in `agent_ai_events` and aren't forwarded into
  `clickhouse_ai_events_json` until v1.
- We need a few weeks of real traffic in the dedicated topic to know
  what shape the rewrite needs (drop entirely vs rewrite team_id vs
  add a `$ai_free` boolean property the ingestion pipeline respects).

**What the future work has to do:**

1. Build a consumer that reads `agent_ai_events` and:
   - Forwards rows where `$ai_origin === 'agent_platform_runner'` AND
     the originating session belongs to a customer's own agent into
     `clickhouse_ai_events_json`.
   - For platform-originated events tied to PostHog's _internal_
     agents (e.g. the self-healing pass, the concierge, future
     authoring agents): either drop, rewrite the team_id to PostHog's
     own, or attach a `$ai_free: true` property the billing meters
     respect.
2. The decision tree above belongs in the consumer, not the emitter —
   the runner shouldn't know whether a session is "free" or "billable".
   Source-of-truth lives at billing time.
3. Removing or renaming `$ai_origin` requires coordinating with that
   consumer; flagged inline in
   [`analytics-sink.ts`](../../../services/agent-shared/src/runtime/analytics-sink.ts)
   via the `PLATFORM_ORIGIN` constant.

## 6. Rollout

**v0 — runner emits to dedicated topic.** ✅ shipped.

- `AnalyticsSink` interface + `InMemory` / `Noop` / `Kafka` impls in
  agent-shared, mirroring `LogSink`.
- `$ai_generation` emission in `run-turn.ts` (success + throw paths).
- `$ai_span` emission in `dispatch-one.ts`.
- `KafkaAnalyticsSink` produces wire-shaped rows
  (`uuid / event / properties / timestamp / team_id / distinct_id / …`)
  matching the ClickHouse `ai_events` Kafka engine schema, ready for
  the future consumer to forward.
- Config knobs: `KAFKA_HOSTS` + `AGENT_ANALYTICS_TOPIC`. Unset →
  `NoopAnalyticsSink` (dev / harness).

**v1 — forwarder consumer + free-flag billing logic.** Not yet built.

- See §5. Owner / timeline TBD.
- Until then events accumulate in `agent_ai_events` but don't reach
  `clickhouse_ai_events_json` — the LLM Analytics surface stays dark
  for agent traffic.

**v2 — backfill from `agent_session.conversation`.** Optional.

- Sessions that ran in v0 (before the forwarder existed) have all the
  information needed to reconstruct events from `conversation` +
  `usage_total`. A one-shot janitor endpoint could emit historical
  events into the topic once the consumer is alive.

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
  `ai_events`, which only exists once the forwarder lands.
- Per-agent / per-tool latency + cost rollups in dashboards
  (`agent_session_daily_summary` views in self-healing §3.2).
