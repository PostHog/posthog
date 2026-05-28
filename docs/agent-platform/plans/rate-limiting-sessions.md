# Design — rate limiting of concurrent sessions

**Status:** draft / open questions. **Owner:** ben.

This is `_TODO.md` item #4. Per-team and per-agent caps on in-flight
sessions, plus a queueing policy for when the cap is hit, plus an
"open-ask" budget that composes with the [approval-gated
tools](approval-gated-tools.md) and [per-session access
elevation](per-session-access-elevation.md) designs.

## 1. Problem

Today there is **no admission control** on the agent platform:

- `enqueueOrResume()` in
  `services/agent-ingress/src/enqueue/enqueue.ts:44-69` creates rows
  unconditionally. No per-team, per-agent, or per-principal limit.
- Runner concurrency is process-local. Each `Worker` instance claims up
  to `maxConcurrency = 8` sessions in parallel
  (`services/agent-runner/src/workers/worker.ts:85-142`). Scaling
  horizontally adds capacity but doesn't bound any one tenant's share.
- Claim is pure FIFO by `created_at` (`pg-queue.ts:62-92`,
  `SELECT ... FOR UPDATE SKIP LOCKED`). A team that triggers 1000
  sessions in 10 seconds gets all 1000 claimed ahead of every other
  team's traffic.

Failure modes this enables:

- **Noisy neighbor**: one team's runaway loop monopolizes runner
  capacity; other teams' sessions starve.
- **Runaway cost**: an agent in a tight loop (broken `end_session`,
  janky tool returning errors that the model retries forever) burns
  unbounded LLM credits before anyone notices.
- **Slack flood amplification**: a misconfigured webhook posts 500
  Slack messages in a minute; each one triggers a new session; runner
  fan-out goes wide.
- **Janitor compounding pressure**: stuck-running reaper requeues
  failures (poison-pill threshold 3) — a broken agent multiplies its
  own runner footprint until the threshold hits.

What we want:

1. **Per-agent caps** declared in spec — the author knows their agent's
   profile. A high-volume helpdesk agent might allow 50 concurrent
   sessions; a destructive ops agent should be 1.
2. **Per-team caps** as a platform safety net, configurable by env /
   admin, defaulting to a sane ceiling (200 concurrent across all of a
   team's agents).
3. **Queue-and-drain, not reject-first**. Slack threads and resumes
   should not be dropped because a team is busy. Sessions queue beyond
   the concurrent cap (up to a depth ceiling) and drain FIFO.
4. **Open-ask budget**: independent of the runner concurrency cap, cap
   how many pending approvals / elevation requests a user can have
   open at once. Prevents a user from being flooded with prompts they
   can't act on.
5. **Composes** with the lifecycle work — suspends, waits, approvals,
   elevations all need a consistent definition of "what counts".

## 2. What "in-flight session" precisely means

The platform tracks several session states. For rate-limiting purposes:

| State                  | Counts toward concurrent cap? | Counts toward queue depth? |
| ---------------------- | ----------------------------- | -------------------------- |
| `queued`               | no                            | **yes**                    |
| `running`              | **yes**                       | no                         |
| `waiting`              | **yes**                       | no                         |
| `suspended`            | no (separate cap, §3)         | no                         |
| `completed` / `failed` | no                            | no                         |

Reasoning:

- `queued` is "not yet claimed". It's pure backlog — the queue-depth
  budget caps it.
- `running` is actively holding a runner slot.
- `waiting` is actively holding a session "open" — the model is
  parked, but the team still has an active conversation, an open
  approval, or a pending elevation. It counts because each `waiting`
  session is a candidate for re-entry into `running` at any moment.
- `suspended` was compacted by the long-running-sessions design
  specifically so it doesn't pin runner state. Its cap is
  `spec.resume.max_suspended_sessions` (see
  [long-running-sessions.md](long-running-sessions.md) §4).

The `concurrent` count is `running + waiting`. The `queue_depth` count
is `queued` only. The `suspended` count has its own cap.

## 3. Per-agent caps — new spec fields

Extend `SpecLimitsSchema` in `services/agent-shared/src/spec/spec.ts`:

```typescript
export const SpecLimitsSchema = z.object({
  // existing
  max_turns: z.number().int().positive().default(50),
  max_tool_calls: z.number().int().positive().default(200),
  max_wall_seconds: z
    .number()
    .int()
    .positive()
    .default(15 * 60),

  // NEW
  max_concurrent_sessions: z.number().int().positive().default(20), // running + waiting, per agent

  max_queued_sessions: z.number().int().positive().default(100), // queued only, per agent — admission ceiling

  max_inflight_per_principal: z.number().int().positive().nullable().default(3), // running + waiting per (agent, principal)
})
```

`max_inflight_per_principal` is the per-user dimension. A team's helpdesk
agent allowing 20 concurrent sessions still shouldn't let one user
spawn all 20 — limit them to 3.

Spec validation rejects: any value ≤ 0; `max_queued_sessions` smaller
than `max_concurrent_sessions` (the queue should be at least the size
of the burst the agent allows running).

Choosing defaults: 20 concurrent / 100 queued / 3 per principal is
roughly "enough for a healthy Slack helpdesk agent on a small team".
Authoring AI should call out when an agent's expected profile pushes
past these defaults.

## 4. Per-team caps — platform safety net

Independently, the platform sets per-team ceilings. Source of truth:

- Environment variables on the ingress + janitor services:
  `AGENT_PLATFORM_TEAM_MAX_CONCURRENT` (default 200),
  `AGENT_PLATFORM_TEAM_MAX_QUEUED` (default 1000).
- Optional per-team overrides via a new Django table
  `AgentPlatformTeamLimits` (small, indexed by `team_id`). Admin
  surface only — not a customer-self-service thing in v0.

These ceilings are platform-wide and per-team. An agent's spec cap is
always lower than or equal to the team's. Effective cap for an agent =
`min(spec_cap, team_cap_remaining_after_other_agents)`.

## 5. Queue admission policy

Two enforcement points, doing different jobs.

### 5.1 Ingress admission — depth check

When ingress receives a `/run` or a `/send` that would create a new
session (no `externalKey` match):

1. Atomic count: `SELECT COUNT(*) FROM agent_session WHERE
application_id = $1 AND state IN ('queued', 'running', 'waiting')`.
2. If `count >= spec.limits.max_queued_sessions +
spec.limits.max_concurrent_sessions`, reject with **HTTP 429**:

   ```jsonc
   {
     "error": "agent_capacity",
     "scope": "agent",
     "current": 120,
     "limit": 120,
     "retry_after_seconds": 30,
   }
   ```

3. Same check at team scope. If team is over the team cap, reject
   with `scope: "team"` and the team's limit.
4. Same check at principal scope (`max_inflight_per_principal`). If
   the calling principal is over, reject with `scope: "principal"`.

Resumes that match an existing `externalKey` **skip this check**: they
don't add a new session row, just append to `pending_inputs` and
re-queue an existing one (`enqueueOrResume()` line 48). A Slack thread
that's been going all week isn't dropped because the team is busy.

The 429 includes `Retry-After`; clients are expected to back off and
retry. For Slack triggers we additionally post a thread reply: "⚠️
your team has hit its agent capacity (NNN sessions). I'll be back when
there's a free slot." The runner's existing Slack post path handles
this.

### 5.2 Claim admission — concurrent check

When a worker calls `queue.claim()`:

Today's claim SQL (pseudo):

```sql
SELECT * FROM agent_session
WHERE state = 'queued'
ORDER BY created_at ASC
LIMIT 1
FOR UPDATE SKIP LOCKED;
```

New claim SQL adds a per-agent concurrent-cap subquery filter:

```sql
WITH agent_inflight AS (
    SELECT application_id, COUNT(*) AS n
    FROM agent_session
    WHERE state IN ('running', 'waiting')
    GROUP BY application_id
),
team_inflight AS (
    SELECT team_id, COUNT(*) AS n
    FROM agent_session
    WHERE state IN ('running', 'waiting')
    GROUP BY team_id
)
SELECT s.* FROM agent_session s
JOIN agent_application a ON a.id = s.application_id
LEFT JOIN agent_inflight ai  ON ai.application_id = s.application_id
LEFT JOIN team_inflight ti   ON ti.team_id        = s.team_id
WHERE s.state = 'queued'
  AND COALESCE(ai.n, 0) < a.max_concurrent_sessions
  AND COALESCE(ti.n, 0) < <team-cap>  -- via settings table
ORDER BY s.created_at ASC
LIMIT 1
FOR UPDATE SKIP LOCKED;
```

Sessions whose agent/team is at capacity are skipped — they stay
`queued`, get picked up the next time a slot frees. **Fairness** comes
from the strict FIFO order within whatever rows pass the cap check.

This shifts the burden from "tell the client to retry" to "the queue
drains itself". The team's queue-depth budget (§5.1) bounds how big
the backlog can grow.

### 5.3 Why both checks

Without §5.1, a team could pile up unbounded `queued` rows that hold
nothing back except DB row count. Without §5.2, the runner would
claim every queued row immediately and burst the team past its
concurrent cap. Together: ingress shapes the queue depth; claim shapes
the concurrent draw.

## 6. Open-ask budget — composing with approvals + elevation

Independent of the runner concurrency budget, each user has an "open
ask" budget — pending approvals (from
[approval-gated-tools.md](approval-gated-tools.md) §3) and pending
elevation requests (from
[per-session-access-elevation.md](per-session-access-elevation.md) §3)
addressed to them.

Why a separate budget: a user with 50 open approvals can't make
decisions on any of them well. A noisy agent that fires 50 sequential
approval-gated tool calls is hostile UX, even if it's within the
session concurrency cap.

Shape: a single env-tunable global default,
`AGENT_PLATFORM_MAX_OPEN_ASKS_PER_PRINCIPAL` (default 10). When an
ingress or runner action would create an 11th open ask addressed to
the same principal:

- For `PendingApproval`: reject the approval intercept upstream. The
  runner returns a synthetic tool error to the model:
  `{ error: "approver_at_capacity", reason: "<principal> has 10
pending approvals" }`. The model handles it as a tool failure.
- For `PendingElevationRequest`: the rejected user gets the 403 but
  the elevation surface is NOT posted (no Slack ping, no thread reply).
  The audit log records `elevation_dropped_owner_at_capacity`.

This is a soft cap — administrators can override per principal — but
the default prevents notification flooding.

## 7. Resume / Slack thread continuity

The platform's existing strength is that a Slack thread reply re-enters
an existing session via `externalKey` match without creating a new
row. The rate-limit design preserves this:

- Resumes (`enqueueOrResume()` line 44 — `existing` found, append
  pending_input, flip to `queued`) are **not subject** to the ingress
  admission check. They re-occupy an already-counted slot.
- They **are subject** to the claim concurrent check. If the team is
  already over its concurrent cap when the resume re-queues, the row
  waits in `queued` until a slot frees. The Slack user sees a slight
  delay but the thread doesn't break.

A subtle case: a long-running session in `suspended` (compacted) wakes
on a new Slack reply. The wake path is in
[long-running-sessions.md](long-running-sessions.md) §6 — the state
transition is `suspended → queued`. At claim time the rate-limit check
applies; if the team is at capacity, the wake just waits.

## 8. Indexes — query shape for fast counts

The current schema lacks composite indexes for per-team / per-app
count queries (per the agent's survey: no `(team_id, state)` or
`(application_id, state)` index). Add three:

```sql
CREATE INDEX idx_agent_session_app_state
    ON agent_session (application_id, state)
    WHERE state IN ('queued', 'running', 'waiting');

CREATE INDEX idx_agent_session_team_state
    ON agent_session (team_id, state)
    WHERE state IN ('queued', 'running', 'waiting');

CREATE INDEX idx_agent_session_principal_state
    ON agent_session (team_id, ((principal->>'id')), state)
    WHERE state IN ('queued', 'running', 'waiting');
```

Partial indexes on the active states keep the index small (terminal
sessions are the majority of rows over time).

The §5.2 claim SQL benefits from a fourth aggregate-friendly index
(`application_id, state`), but Postgres can also satisfy the count
via the per-state index. Profile before optimizing further.

## 9. Audit / observability

What gets surfaced:

- **Metrics** (Prometheus / OTel): `agent_session_inflight{team,app,state}`,
  `agent_session_queue_depth{team,app}`,
  `agent_session_admission_rejected_total{scope, reason}`,
  `agent_session_claim_skipped_total{reason}`.
- **Activity log** (shared with `per-session-access-elevation.md` §8):
  every 429 admission rejection writes a single row at
  `activity: agent_session_capacity_rejected` so teams can see "we
  hit our cap N times today".
- **Janitor extension**: the existing sweep result becomes
  `{ requeued, poisoned, failed, capacity_skipped }`. A high
  `capacity_skipped` ratio over consecutive sweeps signals an
  under-provisioned team.

## 10. Open questions

1. **Per-principal aggregation across agents.** Today
   `max_inflight_per_principal` is per-agent. Should there also be a
   team-wide "this user has more than N open sessions across ALL
   agents" cap? Probably yes — but defer to v1 once we see how
   per-agent behaves.
2. **Burst handling.** A team with cap 20 and a burst of 100
   incoming Slack messages will queue 80 of them. They'll drain over
   the next several minutes. Is that acceptable? Probably yes; the
   alternative (rejecting the surplus) is worse for Slack-thread
   semantics. Document the expected latency.
3. **Priority lanes.** Should certain triggers jump the queue?
   E.g. "manual UI invocations from the agent author always claim
   first". Out of scope for v0 — strict FIFO is the easiest to reason
   about — but we'll need this when the platform hosts paid tenants
   with SLAs.
4. **Spec-declared per-principal exemptions.** "The agent owner is
   exempt from `max_inflight_per_principal`" so authors can run tests.
   Probably a spec field `limits.exempt_principals` listing
   `agent_owner` / specific IDs. v1.
5. **429 + Retry-After tuning.** Static `retry_after_seconds: 30` is
   crude. A smarter version computes from queue position: if 5 rows
   ahead and average run time is 4s, suggest ~20s. Defer; static is
   fine for v0.
6. **Resume thrash.** A buggy Slack integration that re-sends the
   same thread message every 100ms — each one is a `resume`, all
   skip the admission cap, all pile into the same session's
   `pending_inputs` array. The runner sees an exploding pending list.
   Mitigation: cap `pending_inputs` length (e.g. 20) and dedupe by
   message content hash on append. Worth a separate hardening pass.
7. **Suspended count.** Suspended sessions have their own cap
   (`spec.resume.max_suspended_sessions`). Should they roll up into
   any team-level cap? Probably yes —
   `AGENT_PLATFORM_TEAM_MAX_SUSPENDED` default 5000. Cheap to add.
8. **Composing with poison-pill retry.** When the janitor requeues a
   stuck-running session (`reapStuckRunning`, `pg-queue.ts:160-197`),
   the session goes `running → queued`. Counts shift: `running`
   decrements, `queued` increments. The claim subquery sees the same
   capacity arithmetic; nothing special. _But_ a session that
   poison-pills 3 times in a row burns 3 retries worth of capacity.
   Probably fine — the row goes to `failed` after, freeing the
   capacity. Document.
9. **Per-agent vs per-revision.** A spec is frozen per revision. If
   an agent has revision A with cap 20 and is upgraded to revision B
   with cap 5, what happens to A's already-running sessions? They
   continue under A's cap; new admissions go under B's cap.
   `application_id` is stable across revisions, so capacity is per
   `application_id`. Document.

## 11. Rollout

This is mostly additive but has one behavior-changing piece (claim
SQL). Phases:

**v0** (foundation — observability first):

- Add the partial indexes (§8).
- Wire the metrics (§9) — `inflight`, `queue_depth`,
  `admission_rejected_total`, `claim_skipped_total`.
- Add the spec fields with **soft enforcement**: ingress records
  metrics but doesn't reject. Claim SQL unchanged. We watch the
  metric to size sensible defaults against real traffic.
- Build the `AgentPlatformTeamLimits` Django table + admin surface,
  populated with infinite caps to start.

**v1** (hard enforcement):

- Flip ingress to actually 429 when over caps.
- Update claim SQL to skip over-capacity teams/agents.
- Slack post-back for capacity rejections.
- Activity-log integration for `agent_session_capacity_rejected`.

**v2** (open-ask budget + composition):

- Implement the open-ask budget for approvals + elevations (§6).
- Per-principal global cap (open q #1).
- Authoring skill documents the limits and helps the authoring AI
  pick a sensible profile.

## 12. Dependencies + what this enables

**Depends on:**

- `long-running-sessions.md` — the `suspended` state must exist and
  be excluded from the concurrent count.
- `approval-gated-tools.md` — the open-ask budget composes with
  pending approvals.
- `per-session-access-elevation.md` — the open-ask budget composes
  with pending elevation requests; activity-log integration is shared.

**Enables / interacts with:**

- A future "agent fleet view" / observability surface — the metrics
  introduced here (`inflight`, `queue_depth`) are the primitive for a
  team-wide "what are my agents doing?" dashboard.
- Cost controls — once we measure capacity properly, we can put price
  controls on top of it (a team that pays for a higher tier gets a
  higher cap).
- A future "priority lanes" plan (open q #3) — once strict FIFO
  proves limiting, the same admission-control surface can be extended
  to lanes without re-architecting.
- `agent-authoring-flow.md` — the reference authoring skill should
  reason about expected concurrent volume per agent shape (Slack
  helpdesk vs cron digest vs interactive ops) and suggest sensible
  cap values.
