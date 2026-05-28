# Design — cron trigger scheduler

**Status:** draft. **Owner:** ben.

`TriggerSchema` already has a `cron` variant
(`services/agent-shared/src/spec/spec.ts:36`) carrying `schedule` (a cron
expression) + `timezone`. Nothing wakes them up. This plan adds the
server-side scheduler.

## 1. Problem

A handful of agent patterns are cron-shaped:

- Weekly digest of "what changed in the product this week"
- The self-healing introspection pass
  ([`self-healing-agents.md`](self-healing-agents.md) v3)
- A "stale PR reminder" agent that posts to Slack every weekday morning

Today the spec says they're cron-triggered. Nothing scans the live
agents and fires them. Without a scheduler, those agents can be
created and freeze, but never run.

## 2. Where the scheduler runs

**Janitor.** It already runs a periodic sweep (`sweepOnce` every 30s),
already has the `PgRevisionStore`, already opens two pools. Adding a
cron-evaluation pass alongside the sweep is the smallest possible
addition — no new deploy unit, no new shape to operate.

(Alternative considered: a dedicated `agent-scheduler` service. Rejected
for now — the work is small, sharing the janitor's lifecycle and DB
access is fine. We can split later if cron volume forces it.)

## 3. Evaluation cadence

A new `cronTick()` runs on the same interval the janitor sweep does
(default 30s). Each tick:

1. Reads every live `agent_revision` whose `spec.triggers[].type === 'cron'`.
   In practice this is bounded — most teams have a handful of cron agents.
   Cached with TTL ≈ 5 minutes; refreshed on cache miss.
2. For each cron trigger, computes the most-recent firing time in `(last_tick_at, now]`
   using a deterministic cron evaluator (`cron-parser` npm package). Multiple
   firings can fall inside the window — fire each.
3. For each firing, calls `enqueueOrResume()` (same path Slack /
   webhook triggers use) with a synthetic "wake" pending_input.

This means **the scheduler doesn't store any per-agent next-fire-time** —
it just looks back at `now - 30s` on each tick. Simple, stateless,
correct under restart.

## 4. Drift / catch-up semantics

The naive "fire everything in `(last_tick_at, now]`" approach breaks
under outage: if the janitor is down for 4h then comes back, a daily-2am
cron that fired 3 times during the outage would fire 3 times in a
burst.

Two knobs, both on the cron config:

```typescript
{
    type: 'cron',
    config: {
        schedule: '0 2 * * *',          // existing
        timezone: 'UTC',                 // existing
        // NEW
        catch_up: 'most_recent',         // 'all' | 'most_recent' (default) | 'skip'
        max_catch_up_age_seconds: 3600,  // hard cap, default 1h
    }
}
```

- `most_recent` (default): fire once for the most recent missed
  firing within `max_catch_up_age_seconds`. Anything older gets dropped.
  Right for "weekly digest" agents — you want the digest, but only the
  current one.
- `all`: fire every missed firing. Right for "process every event"
  shapes — rare, opt-in.
- `skip`: drop everything missed. Useful for time-sensitive agents
  ("good morning posts") where firing late is worse than not firing.

`max_catch_up_age_seconds` bounds the blast radius regardless of mode.

## 5. Dedup on missed-tick recovery

Each firing is keyed by `(revision_id, fired_at_iso_minute)`. Insert into
a new `agent_cron_firing` table with that pair as a unique constraint.
If the insert collides (we've already enqueued this firing), skip.

Schema (in the agent DB — high churn, runtime data):

```sql
CREATE TABLE agent_cron_firing (
    revision_id     UUID NOT NULL,
    fired_at_minute TIMESTAMPTZ NOT NULL,  -- truncated to the minute
    session_id      UUID NOT NULL,
    PRIMARY KEY (revision_id, fired_at_minute)
);
CREATE INDEX agent_cron_firing_session_idx ON agent_cron_firing(session_id);
```

The minute-truncated key tolerates clock skew between janitor replicas.
A periodic janitor sweep deletes rows older than 30 days (audit
retention, no longer needed for dedup).

## 6. Synthetic wake input

When the cron fires, we don't have a user message. The session gets
this synthetic `pending_input`:

```jsonc
{
  "role": "user",
  "content": "[cron tick] fired_at=2026-05-28T02:00:00Z trigger=daily-digest",
  "metadata": {
    "trigger_kind": "cron",
    "schedule": "0 2 * * *",
    "fired_at": "2026-05-28T02:00:00Z",
  },
}
```

The model sees a normal user-role message; the metadata is there for
the model to inspect if it wants. Authors who want richer wake context
write a skill that explains what to do when this message arrives.

For `external_key_reuse` (per
[`long-running-sessions.md`](long-running-sessions.md) §6), the cron's
external key is `cron:<schedule>` so the same daily-2am cron always
appends to the same session if `external_key_reuse: 'within_resume_window'`
is set. That's how a self-healing pass builds a multi-day investigation
across nightly ticks.

## 7. Spec config — full shape

```typescript
{
    type: 'cron',
    config: {
        schedule: string,                          // required
        timezone: string,                          // default 'UTC'
        catch_up: 'all' | 'most_recent' | 'skip',  // NEW, default 'most_recent'
        max_catch_up_age_seconds: number,          // NEW, default 3600
    },
}
```

Validation at freeze time:

- `schedule` parses with `cron-parser`.
- `timezone` resolves to a real IANA zone.
- `max_catch_up_age_seconds` is positive and ≤ 7 days.

## 8. Open questions

1. **What stops a runaway cron?** An agent with `schedule: '* * * * *'`
   firing every minute will pile up sessions fast. Hook into
   [`rate-limiting-sessions.md`](rate-limiting-sessions.md): cron
   firings go through the same admission check as any other trigger,
   so a per-agent `max_concurrent_sessions` cap of 1 means subsequent
   ticks coalesce into pending_inputs on the live session (the
   `external_key_reuse` path). Document this as the recommended setup
   for cron agents.
2. **Cron evaluation in production with multiple janitor replicas.**
   Two janitors firing the same minute both try to insert the dedup row
   → one wins, one no-ops. Correct by construction; worth a test.
3. **Time-zone edge cases.** DST transitions cause some local times to
   exist 0 or 2 times in a day. `cron-parser` handles this; document
   the behavior so authors know not to schedule for 2:30am on the
   spring-forward day.
4. **Manual fire** for testing. Add a janitor endpoint
   `POST /revisions/:id/cron/fire { schedule: ... }` so the authoring
   AI / a human can trigger a cron firing on demand. Useful for
   debugging without waiting for the next real tick.

## 9. Rollout

**v0** (foundation):

- New `cron-parser` dep on `agent-janitor`.
- `agent_cron_firing` table added to the queue-DB schema bootstrap.
- `cronTick()` runs alongside the sweep; defaults to most-recent + 1h
  catch-up.
- Validation lands on the cron trigger at freeze time.

**v1** (production):

- Manual-fire endpoint for the authoring AI's test flow
  ([`agent-authoring-flow.md`](agent-authoring-flow.md) §5).
- Expose recent firings on the session detail surface so users see
  "this session was started by the daily cron".

## 10. Dependencies + what this enables

**Hard depends on:**

- [`long-running-sessions.md`](long-running-sessions.md) for the
  `external_key_reuse` policy that lets cron firings coalesce into a
  single long-running session.

**Composes with:**

- [`rate-limiting-sessions.md`](rate-limiting-sessions.md) §5 admission
  applies to cron firings unchanged.

**What this unblocks:**

- [`self-healing-agents.md`](self-healing-agents.md) v3 (periodic
  introspection pass).
- "Weekly digest" / "morning standup" / "stale PR reminder" agent
  patterns generally.
