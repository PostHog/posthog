# Design — per-turn cost capture on the session row

**Status:** v0 + v1 shipped; v2 aggregates pending. **Owner:** ben.

We added `usage_total` to the sessions list/retrieve **derived from the
conversation**. That works for one session at a time. This plan
**persists** the same numbers onto the `agent_session` row so they can
be queried in bulk.

## 1. Problem

pi-ai populates `result.usage.cost.{input, output, cacheRead,
cacheWrite, total}` and `result.usage.{input, output, totalTokens}` on
every assistant turn. The runner sees them, the conversation stores
them, but **only inside the JSONB conversation blob**.

Three pain points this creates:

1. **Per-team / per-agent cost rollups** require a full table scan with
   `jsonb_array_elements(conversation)` and arithmetic across every
   assistant message. Fine for one team in a debug query, expensive
   for an org-wide rollup that powers a billing surface.
2. **The summary helper we just shipped recomputes on every read.**
   `lastAssistantTextPreview` + `totalConversationUsage` walk the
   conversation in node code for every list/retrieve call. For a
   long-running session with thousands of turns, that's wasted work
   per list response.
3. **Budget enforcement needs a cheap "current spend" lookup** so
   rate-limiting (`rate-limiting-sessions.md`) can refuse a turn that
   would put the agent over a per-team monthly cap. JSONB walks
   inside admission are out — we want a single indexed-column read.

## 2. Schema

New JSONB column on `agent_session`:

```sql
ALTER TABLE agent_session
    ADD COLUMN usage_total JSONB NOT NULL DEFAULT '{
        "tokens_in": 0,
        "tokens_out": 0,
        "cache_read": 0,
        "cache_write": 0,
        "cost_input": 0,
        "cost_output": 0,
        "cost_cache_read": 0,
        "cost_cache_write": 0,
        "cost_total": 0
    }'::jsonb;

-- Optional but cheap: GIN-style functional index for "all sessions
-- whose cost_total > X" queries. Skipping for v0; revisit if a budget
-- surface lands.
```

JSONB (not separate columns) for two reasons:

- Tokens vs cost have similar enough shape that one map is more
  ergonomic than ten columns.
- pi-ai may add usage fields (e.g. `cached_reasoning_tokens` for the
  o-series). JSONB tolerates that without a migration.

Cache read/write tokens broken out because Anthropic prompt-caching
prices them differently — billing needs the split.

The TS-side shape:

```typescript
export interface SessionUsageTotal {
  tokens_in: number
  tokens_out: number
  cache_read: number
  cache_write: number
  cost_input: number
  cost_output: number
  cost_cache_read: number
  cost_cache_write: number
  cost_total: number
}
```

Note: this **extends** the summary shape returned by
`totalConversationUsage()`. That helper currently returns 5 fields
(tokens_in, tokens_out, cost_input, cost_output, cost_total). v1 of
this plan widens it to 9. Existing callers either get more fields for
free or read just the subset they care about.

## 3. Update path on each turn

The runner already has `onTurnPersist(session)` after every assistant
message. We extend it:

```typescript
async function onTurnPersist(session: AgentSession, assistantMsg: AssistantMessageRecord): Promise<void> {
  const usage = assistantMsg.usage
  if (usage) {
    session.usage_total = {
      tokens_in: session.usage_total.tokens_in + (usage.input ?? 0),
      tokens_out: session.usage_total.tokens_out + (usage.output ?? 0),
      cache_read: session.usage_total.cache_read + (usage.cacheRead ?? 0),
      cache_write: session.usage_total.cache_write + (usage.cacheWrite ?? 0),
      cost_input: session.usage_total.cost_input + (usage.cost?.input ?? 0),
      cost_output: session.usage_total.cost_output + (usage.cost?.output ?? 0),
      cost_cache_read: session.usage_total.cost_cache_read + (usage.cost?.cacheRead ?? 0),
      cost_cache_write: session.usage_total.cost_cache_write + (usage.cost?.cacheWrite ?? 0),
      cost_total: session.usage_total.cost_total + (usage.cost?.total ?? 0),
    }
  }
  await queue.update(session.id, {
    conversation: session.conversation,
    usage_total: session.usage_total,
    updated_at: new Date().toISOString(),
  })
}
```

Accumulation happens in-process; the persist is a single UPDATE per
turn (same shape as today's conversation persist). No new round trip.

## 4. Backfill

Existing sessions have `usage_total = '{...}'::jsonb` defaults (all
zero). For the rollout:

- New sessions accumulate correctly from v0.
- Existing sessions (the JSONB still has their full conversation)
  get a one-shot backfill via a janitor endpoint:

```text
POST /sessions/backfill_usage
    { application_id?: UUID, dry_run: boolean }
```

The backfill walks `agent_session` rows where the JSONB default is
still in place (`usage_total = '{...}default'` matches by jsonb
equality), recomputes from `conversation` using
`totalConversationUsage()`, and UPDATEs. Bounded to one app at a
time so we can throttle.

Default `dry_run: true` returns a row count without writing — useful
to size the backfill before triggering it for real.

For the v1 cutover Django migration, we don't backfill in the
migration itself (locks the table). The migration adds the column
with a default; the backfill is async via the janitor endpoint.

## 5. Surfaces that benefit

- **`agent-applications-sessions-list`** — `usage_total` reads
  straight off the row, no `totalConversationUsage()` walk in node.
  Same response shape, faster.
- **Per-agent rollup tool** (new) —
  `agent-applications-usage-stats` that returns
  `{ sessions: N, tokens_in_total, ..., cost_total }` for a given app
  - date range. Single `SUM((usage_total->>'cost_total')::float)`
    query.
- **Rate-limiting admission** — when
  [`rate-limiting-sessions.md`](rate-limiting-sessions.md) gets a
  budget knob (`max_cost_usd_per_day`), the admission check is a
  per-team sum over `usage_total->>'cost_total'` over a date window.
  Cheap because it's an indexed-column scan, not a JSONB walk.
- **Activity log** —
  [`per-session-access-elevation.md`](per-session-access-elevation.md)
  §8 activity-log records can include the final `usage_total` when
  the session completes (so an audit shows "this elevation grant
  cost $0.12").

## 6. Schema-side rules

- `usage_total` is **append-only** in spirit — we only ever increment.
  No code path resets it except backfill.
- A session that retries (`retry_count > 0`) keeps its accumulated
  usage from prior attempts. That matches user intent: "what did this
  session cost me?" includes every retry.
- A session in state `failed` mid-turn doesn't have its in-flight
  partial turn counted. We only persist on successful pi-ai turn end.

## 7. Open questions

1. **Faux-provider sessions in tests.** `FauxPiClient` returns
   `usage: 0` everywhere; `usage_total` accumulates to zero. That's
   fine for shape tests, but harness assertions on "cost reporting
   worked" need a fixture path. Plan: add a `faux.text(...,
{usage:{input:50,output:10,cost:{...}}})` builder.
2. **OpenAI streaming responses.** pi-ai may not have final usage
   until the stream ends. The streaming plan
   ([`streaming-and-reasoning.md`](streaming-and-reasoning.md)) ends
   each stream with an `end` event carrying the materialized
   `AssistantMessage` including usage — so `onTurnPersist` still has
   the numbers. No change needed.
3. **LLM gateway cost — don't trust pi-ai's calc.** When
   `config.useLlmGateway === true`, the runner routes every call
   through `posthogAiGatewayModel()`. pi-ai's `usage.cost.*` numbers
   in that path are client-side estimates (often zero / based on
   pi's own pricing tables, which we don't own and can't keep in
   sync with our ai-gateway billing). We want **our own** cost
   calculation, not pi's:
   - **Token counts (`input`, `output`, `cacheRead`, `cacheWrite`)
     are fine** — those come from the provider response, not pi's
     pricing table. Keep accumulating them.
   - **Cost fields (`cost.input`, `cost.output`, `cost.cacheRead`,
     `cost.cacheWrite`, `cost.total`) come from PostHog's price
     table**, not pi's. Two implementation options:
     1. **Recompute at accumulate time** in `onTurnPersist`: feed
        the token counts + the model id into a `posthogCost()`
        helper that reads our internal price map and returns the
        dollar figures. Same place as the accumulator; one source
        of truth.
     2. **Pull from the gateway's tracking endpoint.** The
        ai-gateway already tracks per-request cost server-side; a
        future endpoint returns the materialized number. Cleaner
        long-term but adds a round trip per turn.
   - Lean **(1)** for v0 — no new round trips, gateway service can
     evolve independently. Revisit once the gateway has a
     query-cost endpoint and we want a single source on the gateway
     side. The price table lives somewhere central (likely
     `posthog/llm/pricing.py` shared between Django + the gateway);
     the node side either imports a JSON snapshot or hits a small
     `/v1/pricing` lookup at boot.
   - **Non-gateway path stays as-is** — pi-ai's pricing for direct
     Anthropic / OpenAI calls is the legacy behavior and continues
     to work. The gateway branch is the one where we override.
4. **Cost-attribution surface.** Hinted at across B.3, C.1, D.2. This
   plan is its foundation but doesn't build the surface itself.
   Future plan once we have a use case beyond billing.
5. **Cross-revision aggregation.** "How much did agent X cost across
   all revisions in May?" is one of:
   - join `agent_session` (queue DB) → `agent_revision` (Django DB)
     → `agent_application` (Django DB) at query time, OR
   - denormalize `application_id` onto `agent_session` (it already
     is, for slug routing) and just GROUP BY. We have the column;
     this is a one-line aggregate.

## 8. Rollout

**v0 — column + accumulator.** ✅ shipped.

- Migration adds `usage_total` column (JSONB default).
- `SessionQueue.update()` accepts the new field.
- Runner `onTurnPersist` accumulates and writes via the shared
  `accumulateUsage()` helper, honouring `useGatewayCost`.
- TS shape (`AgentSession.usage_total` + `SessionUsageTotal`) added.
- Tests: `run-turn.test.ts` asserts post-turn `session.usage_total`
  matches the assistant message's `usage`; gateway-cost branch zeroes
  cost while preserving token counts.

**v1 — surface it.** ✅ shipped.

- `summarize-conversation.ts` deprecated for live-row reads
  (still useful for backfill + ad-hoc tests). The summary helper
  in [services/agent-shared/src/spec/summarize-conversation.ts]
  stays as a derivation, but
  `agent-applications-sessions-list` returns the persisted column.
- Backfill endpoint shipped at `POST /sessions/backfill_usage` on
  the janitor; defaults to `dry_run: true`.

**v2 — aggregates.** Not yet built.

- `agent-applications-usage-stats` tool with date-range / state
  filters.
- Optional functional index if query latency becomes an issue.

## 9. Dependencies + what this enables

**Hard depends on:** nothing. Pure schema + runner change.

**Composes with:**

- [`streaming-and-reasoning.md`](streaming-and-reasoning.md) — the
  stream's `end` event still carries usage, so streaming doesn't break
  cost accumulation.
- [`per-session-access-elevation.md`](per-session-access-elevation.md)
  §8 — activity-log entries can carry `usage_total` snapshots.
- [`rate-limiting-sessions.md`](rate-limiting-sessions.md) — opens
  the door to cost-based admission caps.

**What this unblocks:**

- A team-level / org-level "agent spend this month" surface (future
  plan, hinted across B.3 / C.1 / D.2).
- Budget enforcement in admission control.
- Per-agent ROI reporting in the authoring UI.
