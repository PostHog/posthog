# Design — cron trigger scheduler

**Status:** draft. **Owner:** ben.

[`TriggerSchema`](../../../services/agent-shared/src/spec/spec.ts) already
carries a `cron` variant with `schedule` + `timezone`. Nothing wakes
those agents up, and the existing shape is too thin — it tells you
_when_ but not _what to do_. This plan fixes both.

## 1. The shift: each cron entry is a job, not a ping

The cron-shaped agents in [`_APP_IDEAS.md`](_APP_IDEAS.md) all share a
problem: a single agent has a lot of context (a digest agent knows how
to read the warehouse, format prose, post to Slack) and is triggered
in multiple shapes — chat ("redo last week's digest"), webhook
("Grafana fired, look at this"), and _cron_ ("it's Monday morning, do
the weekly digest"). The cron firing needs to communicate the **task**
to the agent, not just "tick happened."

So the unit of cron config isn't "a schedule" — it's a **job**:

| Field      | Purpose                                                                               |
| ---------- | ------------------------------------------------------------------------------------- |
| `name`     | Human + machine handle for the job. Required, unique within the agent's `triggers[]`. |
| `schedule` | Cron expression. Required.                                                            |
| `timezone` | IANA zone. Default `UTC`.                                                             |
| `prompt`   | **What the agent should do when this cron fires.** Required.                          |

An agent with three cron jobs is three trigger entries, each with its
own prompt. The agent's `agent.md` describes the agent's identity,
skills, and tone; each cron's `prompt` is a normal user-shaped request
that exercises that identity.

```yaml
triggers:
  - type: chat
    config: { require_auth: true }
  - type: cron
    config:
      name: weekly-digest
      schedule: '0 9 * * MON'
      timezone: US/Pacific
      prompt: |
        Produce the weekly product digest. Cover the last 7 days.
        Use `@posthog/query` for shipped-feature signals, and
        `@posthog/slack-read-channel` for #releases. Post the draft
        to #marketing and end-turn.
  - type: cron
    config:
      name: stale-pr-ping
      schedule: '0 9 * * 1-5'
      timezone: US/Pacific
      prompt: |
        Find PRs in posthog/posthog open >7 days with no review activity.
        Post a thread to #engineering listing them with author + age.
```

`agent.md` doesn't need to mention cron at all. Each firing arrives at
the runner as a user-role message whose content is the `prompt` — the
agent treats it as a normal request, picks the right skill, uses its
tools, finishes the turn.

## 2. What "fire" actually means

A firing is a single call into the same
[`enqueueOrResume()`](../../../services/agent-ingress/src/enqueue/enqueue.ts)
that chat, webhook, and Slack already use. It carries:

- The application + the live revision id (cron only fires through the
  live revision; agents without a live revision get skipped)
- An `idempotency_key` so two janitor replicas can't both create a
  session for the same firing (see §6)
- An optional `external_key` derived from the cron config (see §3)
- A user-role input message whose content is the job's `prompt` (see §4)
- Trigger metadata `{ kind: 'cron', cron_name, schedule, fired_at }`

The scheduler doesn't manage sessions, doesn't track resume state,
doesn't open or close anything. The path from firing to "the agent
runs" is the same path every trigger walks.

## 3. Fresh session per firing, or append to a long-running thread?

The author controls this via `external_key`, the same way they do for
Slack / chat / webhook today. The cron config has an optional
`external_key` field with placeholder expansion:

| Author intent                                            | What they set                             | Result                                                                                   |
| -------------------------------------------------------- | ----------------------------------------- | ---------------------------------------------------------------------------------------- |
| **Fresh session every firing.** Weekly digest, stale-PR. | Leave `external_key` unset (the default). | The scheduler doesn't supply one; `enqueueOrResume` creates a new session.               |
| **Append to one rolling session.** Self-healing thread.  | `external_key: 'self-healing'`            | `findByExternalKey` returns the existing session; new prompt goes into `pending_inputs`. |
| **One session per calendar day / week.**                 | `external_key: 'digest-{fired_at:week}'`  | Each week gets its own session; multiple firings the same week append.                   |

Placeholders: `fired_at:iso`, `fired_at:date`, `fired_at:week`,
`schedule`, `cron_name`. Expanded at firing time. **No new resume
concept is invented** — the underlying mechanism is the existing
`external_key` resume from [long-running-sessions.md](long-running-sessions.md) §4.

## 4. The firing message

The runner's loop expects a user turn to drive the assistant turn. The
scheduler supplies one whose **content is the job's `prompt`** and
whose metadata carries the cron context:

```jsonc
{
  "role": "user",
  "content": "Produce the weekly product digest. Cover the last 7 days. ...",
  "metadata": {
    "trigger_kind": "cron",
    "cron_name": "weekly-digest",
    "schedule": "0 9 * * MON",
    "fired_at": "2026-06-01T16:00:00Z",
  },
}
```

The agent treats this as a normal request. If it wants to know it was
cron-triggered (to skip some prelude, or pick a specific skill), it
reads `metadata.trigger_kind`. Most agents don't need to.

`prompt` supports the same placeholders as `external_key`. So:

```yaml
prompt: 'Produce the digest for the week ending {fired_at:date}.'
```

## 5. Where the scheduler runs

**Janitor.** It already runs `sweepOnce` every 30s
([`sweep.ts`](../../../services/agent-janitor/src/sweep.ts)), already
holds the `PgRevisionStore`, already opens the two PG pools. Adding a
`cronTick()` alongside the sweep is the smallest possible addition —
no new deploy unit, no new shape to operate.

(Alternative considered: a dedicated `agent-scheduler` service.
Rejected — small work, janitor's lifecycle fits. Splittable if cron
volume ever forces it.)

## 6. The cron tick — and the `idempotency_key` primitive

The dedupe problem ("two janitor replicas race, only one session
should be created") is the same problem webhook redelivery has when
Stripe / GitHub / Slack resend an event. Both want: "I supplied this
key once; if a session for it already exists, no-op." Rather than
build a cron-specific dedupe table, the platform grows a general
**`idempotency_key`** column on the session row, and cron uses it.

### The primitive

```sql
ALTER TABLE agent_session ADD COLUMN idempotency_key TEXT NULL;

CREATE UNIQUE INDEX agent_session_idempotency_key_unique
    ON agent_session (application_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
```

`enqueueOrResume()` grows an optional `idempotencyKey` argument. When
supplied:

1. The insert is `INSERT … ON CONFLICT (application_id, idempotency_key)
DO NOTHING RETURNING id`.
2. If a row comes back, the caller created the session. Continue as
   today.
3. If no row comes back, the duplicate is dropped. Look up the
   existing session by `(application_id, idempotency_key)` and return
   it (mirrors Stripe's behaviour: a duplicate request returns the
   original response).

Two important contrasts with `external_key`:

| Verb on collision | `external_key` (existing) | `idempotency_key` (new)              |
| ----------------- | ------------------------- | ------------------------------------ |
| Match found       | **Append** to session     | **No-op**, return original           |
| Author's intent   | "Same conversation"       | "Same request"                       |
| Typical lifetime  | Days / weeks              | Minutes / hours, swept after 30 days |

They're independent fields and can coexist on a session.

### How `cronTick()` uses it

`cronTick()` runs on the same 30s interval as the sweep. Each tick:

1. **List candidates.** Every application's `live_revision_id` whose
   `spec.triggers[]` includes at least one `cron` entry. Backed by a
   new `PgRevisionStore.listLiveCronRevisions(): Promise<AgentRevision[]>`;
   in-memory filter over `listLiveRevisions()` is fine until live-cron
   count grows past ~1000, then a JSONB GIN index on
   `spec->'triggers'` upgrades the query.
2. **Compute firings in the window.** For each `cron` trigger on each
   live revision, use `cron-parser` to list firings in
   `(lastTickAt, now]`. Multiple firings can fall in the window;
   apply catch-up (§7) to decide which actually fire.
3. **Enqueue with idempotency.** For each surviving firing, build the
   key:

   ```ts
   idempotencyKey = `cron:${revision.id}:${cron_name}:${fired_at_minute}`
   ```

   and call `enqueueOrResume({ ..., idempotencyKey })`. The unique
   index does the dedupe. If two janitors raced, one wins and starts
   the session; the other gets the same session id back and no-ops.

`lastTickAt` is per-janitor-process in memory. On restart it resets to
`now`; the catch-up policy is what handles missed firings, not a
persisted clock. **The unique index is the only source of truth for
"did we fire this minute,"** not any in-memory clock.

### Retention

A janitor sweep nulls out `idempotency_key` on sessions older than 30
days — at that point the dedupe is no longer load-bearing (any retry
would have happened long ago) and freeing the slot keeps the partial
index small. Same sweep can keep an `agent_session_trigger_audit`
roll-up if "when did this cron last fire?" queries need a longer
retention window than the live session row.

### Why this generalizes

Webhook triggers can accept an `Idempotency-Key` header (or read it
from `X-Hub-Signature-ID` / Stripe's `idempotency_key` body field
depending on provider) and pass it through to `enqueueOrResume()` —
the platform now de-dupes redeliveries from external systems too,
without any new code. That's a strict improvement on today, where a
double-delivery from Stripe creates two sessions.

## 7. Catch-up on downtime

If the janitor was down for 4 hours, a daily-2am cron that fired three
times in the gap would, by default, fire all three at once. Almost
never the right thing. Three modes:

```yaml
config:
  schedule: '0 2 * * *'
  catch_up: most_recent # 'all' | 'most_recent' (default) | 'skip'
  max_catch_up_age_seconds: 3600
```

- `most_recent` (default) — fire **once** for the most recent missed
  firing within `max_catch_up_age_seconds`. Anything older is dropped.
  Right for digests, reminders, periodic crawls.
- `all` — fire every missed firing within the bound. Right for
  "process every period" shapes paired with append-mode `external_key`
  (rare, opt-in).
- `skip` — drop every missed firing. Right for time-sensitive sends
  ("good morning" posts where firing late is worse than not firing).

`max_catch_up_age_seconds` is a hard cap regardless of mode; bounded
to 7 days at validation.

## 8. Spec — full shape

```typescript
{
    type: 'cron',
    config: {
        name: string,                              // required, unique within triggers[]
        schedule: string,                          // required, cron-parser
        timezone: string,                          // default 'UTC', IANA
        prompt: string,                            // required
        external_key: string | undefined,          // default undefined (= fresh)
        catch_up: 'all' | 'most_recent' | 'skip',  // default 'most_recent'
        max_catch_up_age_seconds: number,          // default 3600, max 604800
    },
}
```

Freeze-time validation in
[`validate-spec.ts`](../../../services/agent-janitor/src/validate-spec.ts):

- `name` matches `^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$`
- All `name`s across `triggers[]` are unique
- `schedule` parses with `cron-parser`
- `timezone` resolves to a real IANA zone
- `prompt` non-empty, ≤ 4096 chars
- `external_key` / `prompt` placeholders are whitelisted
  (`fired_at:iso`, `fired_at:date`, `fired_at:week`, `schedule`,
  `cron_name`)
- `max_catch_up_age_seconds` ∈ [1, 7 * 86400]

## 9. Operational concerns

**Multi-replica.** Covered by the idempotency-key unique index (§6);
no leader needed. Two janitors race on the insert; the unique
constraint resolves it; the loser gets the original session id back
and no-ops.

**Runaway crons** (`schedule: '* * * * *'`). Goes through the same
admission check as every other trigger
([`rate-limiting-sessions.md`](rate-limiting-sessions.md) §5).
Recommended setup: `max_concurrent_sessions: 1` plus append-mode
`external_key` so subsequent firings coalesce into `pending_inputs`
rather than stacking sessions. Document in the registry-vendored
`@posthog/cron-frequent` skill template.

**Timezones.** `cron-parser` handles DST natively. Document that
authors shouldn't schedule for 2:30am on a spring-forward day (that
local time doesn't exist; cron-parser skips it).

**Manual fire.** From v0: `POST /revisions/:id/cron/fire` on the
janitor accepts `{ cron_name: string, fired_at?: string }` and runs
the same firing path with a synthetic idempotency key
(`cron-manual:${revision_id}:${cron_name}:${request_id}`) so repeated
clicks don't double-fire. The concierge surfaces this as
`agent-applications-revisions-cron-fire-create`. Without it, **you
can't sanely author a cron agent** — the user would have to wait
until the next real firing to see whether their prompt works.

**Observability.** Trigger metadata (`trigger_kind: 'cron'`,
`cron_name`, `schedule`, `fired_at`) lands on the session row from
v0. Session-detail in agent-console renders a "fired by `<cron_name>`
at `<fired_at>`" badge. "When did this cron last fire?" is a normal
session-list query filtered on `metadata.cron_name` — no separate
cron-firings table or endpoint.

## 10. Rollout

**v0** (the whole thing, since authoring depends on every piece):

- `idempotency_key` column + partial unique index on `agent_session`
  ([`services/agent-migrations/migrations/`](../../../services/agent-migrations/migrations/))
- `enqueueOrResume()` gains the `idempotencyKey` argument; webhook
  trigger wired to forward provider-supplied keys
- `cron-parser` dep on `agent-janitor`
- `TriggerSchema` extended with `name`, `prompt`, `external_key`,
  `catch_up`, `max_catch_up_age_seconds`
- `PgRevisionStore.listLiveCronRevisions()` (in-memory filter first)
- `cronTick()` runs alongside `sweepOnce`
- `POST /revisions/:id/cron/fire` for manual / dry-run firings
- Session row carries trigger metadata; session-detail UI renders it
- Janitor sweep nulls out `idempotency_key` after 30 days
- Freeze-time validation extended with cron-specific checks
- MCP tool `agent-applications-revisions-cron-fire-create` exposed
  to the concierge; `using-the-registry` updated with cron authoring
  guidance

**v1** (polish):

- JSONB GIN index on `spec->'triggers'` if list-live-cron-revisions
  becomes a hot query
- "Recent firings" panel in agent-console session-list filter
- Registry-vendored `@posthog/cron-frequent` skill template for the
  pile-up avoidance pattern
- Idempotency-key advertised on webhook ingest for all triggers, not
  just Stripe-shaped providers

## 11. Dependencies + what this unblocks

**Depends on:** nothing not already shipped. The new pieces are
additive: a nullable column + partial unique index on
`agent_session`, an optional argument on `enqueueOrResume()`, and the
janitor's `cronTick()`. The existing `external_key` resume mechanism,
the `pending_inputs` queue, and the registry that just shipped all
compose without modification.

**What this unblocks:**

- The time-based half of eight apps in
  [`_APP_IDEAS.md`](_APP_IDEAS.md) (Marketing update, Feature
  prioritization, Industry intelligence, Customer research, Growth
  review, Gap analysis, Financial reconciliation, Warpstream
  forecasting) plus [`self-healing-agents.md`](self-healing-agents.md)
  v3. **The single largest unblock per the feasibility matrix.**
- **Webhook double-delivery safety as a side effect.** The
  `idempotency_key` primitive lets the webhook trigger forward
  provider-supplied keys (Stripe, GitHub, Slack retries) and have the
  platform de-dupe automatically. No more "Stripe redelivered the
  event and now we have two sessions for the same charge" failure
  mode.
