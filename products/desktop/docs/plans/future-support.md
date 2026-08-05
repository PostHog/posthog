# future-support — Support Engineer Harness

Owner: Luke Belton
Status: **Scope settled — ready to build** (decisions recorded below, 2026-07-28)
Last updated: 2026-07-28

## Summary

An agent-assisted support engineer's working life revolves around **context
switching**. The recurring decision is: work on an existing ticket — one a
customer has just added information to — or pick something new out of the queue.

AI compounds this rather than relieving it. The engineer continuously hands work
off to an agent (investigate this, draft a PR), the agent goes away, and then it
returns needing human input. So at any moment there are N tickets in flight at
different stages of agent handoff, plus a live queue of new work, and the
engineer is the scheduler.

This plan builds two things, in order:

1. **"What do I work on"** — assisted prioritisation across *both* in-flight and
   new work, with newly-urgent items injected as they appear. A background loop
   keeps it current.
2. **"How do I work on it"** — checklist-style tracking on a ticket recording what
   needs to happen next, so returning to a ticket doesn't mean rebuilding state
   from scratch. PostHog Desktop tasks already do the agent work; this is the
   tracking layer above them. The checklist is **two-way**: humans and agents
   contribute to it equally, and because tickets get shared across support and
   product engineers it persists server-side and doubles as an audit log.

The organising insight: the unit of work is not a ticket, it is **an attention
decision**. Everything below optimises for making that decision cheap and
correct, and for making the return trip to a parked ticket cheap.

## The problem, stated precisely

A support engineer's queue is not a list of new tickets. At any moment it is a
merge of at least four populations, and only the first is what a ticket list
normally shows:

| Population | Why it needs attention | Where the state lives |
| --- | --- | --- |
| New / unassigned | Never triaged | Conversations API |
| Customer replied | Ball is back in your court | Conversations API (`unread_team_count`) |
| Agent handed back | Investigation or PR draft awaits review | **posthog/code tasks** |
| Parked / at risk | Snooze elapsed, or SLA approaching | Conversations API |

The third row is the reason this belongs in `posthog/code`: agent-handoff state
does not exist in the Conversations product at all. It lives here, in the tasks
and cloud-task services. **A unified attention queue is a join between remote
ticket state and local agent state, and this repo is the only place both are
visible.** That join is the novel part of this feature — not the ticket list.

## Goals

- One ranked "what next" surface merging all four populations above, where every
  rank carries a visible reason.
- Make resume-vs-new an explicit, informed choice rather than an accident of
  which tab is open.
- Continuously surface newly-urgent work (customer replied, agent finished, SLA
  now at risk) without the engineer polling for it.
- Per-ticket checklists capturing what needs to happen next — two-way (human and
  agent write equally), shared across everyone touching the ticket, and usable
  as an audit trail of who did what, when.
- Keep the agent work itself on the existing tasks machinery — this feature
  schedules and tracks, it does not re-implement execution.

## Non-goals (explicitly out of scope)

- **No new ticket storage.** `products/conversations` in `PostHog/posthog` stays
  the system of record for tickets and messages.
- **No new task/agent execution machinery.** `packages/core/src/{tasks,cloud-task}`
  already does this well; checklists reference tasks, they don't replace them.
- **No new SLA engine.** `sla_due_at` is computed server-side; we rank by it.
- **Not a replacement for the Conversations web UI.** That remains the
  general-purpose surface. This is an engineer-facing scheduler.
- **No auto-sending customer-facing replies.** Out of scope for both initial
  halves; if drafting lands later it stays assistive.
- **Reply drafting and diagnosis tooling are deferred.** Both are attractive and
  neither is one of the two initial halves. Notes retained under
  [Deferred](#deferred).

## Design principles

1. **Rank the work, don't just list it.** A queue that doesn't say what to do next
   pushes the scheduling cost back onto the human.
2. **Never rank without a reason.** An unexplained ordering won't be trusted, and
   an untrusted ordering gets ignored — surface the *why* on every item.
3. **Optimise for the return trip.** The expensive moment is coming back to a
   ticket after 40 minutes elsewhere. Checklists exist to make that cheap.
4. **The checklist is the human↔agent handoff protocol — in both directions.**
   An agent finishing an investigation ticks what it did and appends what's
   next; a human queuing up agent work leaves unchecked items the agent reads
   as its brief. Same artefact, both authors, every item attributed.
5. **Interruptions must be earned.** A loop that injects work is a loop that can
   destroy focus. Only genuine state changes notify; re-ranking alone is silent.
6. **Everything ships behind a feature flag, internal first.** The whole surface
   (UI feature + background loop registration) gates on one flag via the
   existing `useFeatureFlag` seam; first users are PostHog's own support team.
7. **Standard layering** (per `AGENTS.md`): Conversations calls in `api-client`;
   ranking and the ticket↔task join in a `core` service; pure ranking logic as
   testable functions; UI renders and calls one hook per query/mutation.

## Key findings (already verified)

### The resume signal already exists — no posthog-side work needed

`Ticket` (`products/conversations/backend/models/ticket.py`) already carries
everything the "what do I work on" half needs:

- `status`: `new | open | pending | on_hold | resolved`
- `priority`: `low | medium | high | critical` (**nullable** — untriaged tickets
  have no priority, so ranking cannot assume it's set)
- `unread_team_count` — *"messages team hasn't seen (from customer)"*
- `sla_due_at`, `snoozed_until`, `last_message_at`, `message_count`
- `ai_triage` (JSON), `ai_resolved`, `escalation_reason`
- `session_id` / `session_context` (carries `session_replay_url`)
- `github_repo` / `github_issue_number` — a ticket↔GitHub issue link already exists

The highest-value signal in the whole feature falls straight out of these:
**`status ∈ {pending, on_hold}` AND `unread_team_count > 0` means the customer
came back and the ticket is actionable again.** That is the "existing ticket a
customer has provided more information on" case, computable today, no schema
change.

`TicketAssignment` is a `OneToOne` on ticket with a check constraint of exactly
one of `user` / `role` — so "mine" means assigned to me directly *or* to a role I
hold. Role-assigned tickets are effectively an unclaimed shared pool and should
rank differently from personally-assigned ones.

### Agent-handoff state is only in this repo

`packages/core/src/{tasks,cloud-task,task-detail}` and
`packages/ui/src/features/{tasks,task-detail}` own task lifecycle; `cloud-task`
streams remote run progress back over SSE (`sse-parser.ts`). Nothing about a
running or completed agent investigation is visible to the Conversations API.
Hence the join described above.

### The loop machinery exists

`packages/harness/src/extensions/background-jobs/` is a real extension with tests
— the seam for a recurring re-prioritisation job. `packages/core/src/notification`
handles surfacing. `packages/core/src/scouts/` is the closest behavioural
precedent (recurring scan → findings → presentation), and notably includes
`scoutScratchpad.ts` for state carried **across** runs — directly applicable to a
loop that must remember what it already told you about.

### Checklists have no server-side home yet — one new model needed

Nothing in `products/conversations/backend` implements a checklist, todo, or
next-step concept (`tasks.py` there is Celery, not user-facing tasks). Decision
made 2026-07-28: build it server-side (see decision record below).
`TicketView` shows the model convention to follow:
`class TicketView(CreatedMetaFields, UpdatedMetaFields, UUIDModel)` with a
`team` FK — `CreatedMetaFields` supplies `created_by`/`created_at` for free.

### Feature-flag gating already has a seam

`packages/ui/src/features/feature-flags/` exposes `useFeatureFlag(flagKey)` and
`useFeatureFlagsLoaded()` over a host-agnostic `FEATURE_FLAGS` service
(desktop adapter wraps posthog-js). Convention per
`features/agent-applications/featureFlag.ts`: a `featureFlag.ts` in the feature
dir exporting the key const with a doc comment naming what it gates, mirroring
a flag defined on the PostHog side.

### Naming collisions to avoid propagating

- `products/support/` in `PostHog/posthog` is unrelated internal ops tooling.
- `[Support]`-prefixed dashboards in PostHog project 2 track PostHog's *internal*
  support team ops via Zendesk, not Conversations usage.
- `support-sidebar-max` is the docs AI-chat widget.
- Inbox's `SignalCard.tsx` has a `"Zendesk · Ticket"` source label that is **not**
  the Conversations `Ticket` type.
- Ticket API types are already generated in `packages/api-client/src/generated.ts`
  (`Ticket`, `TicketView`, `TicketStatusEnum`, `TicketAssignment`, `PatchedTicket`,
  paginated lists, plus `suggest_reply` / `bulk_update_tags` / `unread_count`
  endpoints) and referenced nowhere else in this repo yet.

### Reusable seams

| Need | Existing seam |
| --- | --- |
| Ticket REST types + endpoints | `packages/api-client/src/generated.ts` |
| API client method pattern | MCP installation methods in `packages/api-client/src/posthog-client.ts` |
| Queue list/detail/tabs precedent | `packages/ui/src/features/inbox/` (+ its `CLAUDE.md`) |
| Agent work execution | `packages/core/src/{tasks,cloud-task,task-detail}` |
| Recurring background work | `packages/harness/src/extensions/background-jobs/` |
| Cross-run loop memory | `packages/core/src/scouts/scoutScratchpad.ts` |
| Surfacing / interrupts | `packages/core/src/notification` |
| Local durable state (if needed) | workspace-server SQLite + Drizzle (`docs/plans/browser-tabs.md` precedent) |
| Pure-transform test shape | `packages/core/src/panels/panelLayoutTransforms.test.ts` |
| Service test shape (faked deps) | `packages/core/src/focus/service.test.ts` |

---

## Decision record (2026-07-28)

1. **Checklists persist server-side** — a new model in `products/conversations`.
   Rationale: tickets get shared across multiple support/product engineers, so a
   local checklist solves half the problem; and the checklist doubles as an
   **audit log**, which a per-device store cannot be. Server-side also dissolves
   the worst constraint of the local option: cloud agents write directly via the
   API, so agent work completing while the desktop app is closed still lands.
2. **Loop cadence: every 30 minutes** to start. Interrupt thresholds within that
   cadence stay a tuning question, not a design question.
3. **Internal first, behind a feature flag.** PostHog's own support team
   dogfoods; the flag gates the whole surface.
4. **No checklist templates for now.** Freeform entry only; templates move to
   [Deferred](#deferred).
5. **Ticket↔task linkage rides with PR 4a** (2026-07-28). `Task.origin_product`
   already has a `support_queue` value but no ticket reference; add a
   `Task.ticket` field mirroring the `signal_report` precedent in the same
   posthog/posthog PR as the checklist model. Until it lands, the queue ships
   with three of the four populations — `agent-handed-back` is typed and
   ranked but never produced.
6. **Placement: top-level sidebar destination** at `/code/support` (Loops
   pattern: `CUSTOMIZABLE_NAV_ITEMS` entry, flag-gated, Alpha badge). Flag
   creation in the PostHog project deferred until closer to dogfood; dev
   builds default the flag on (`import.meta.env.DEV`).
7. **POC pivot (2026-08-05).** The PR stack above is superseded: the work
   migrated with the posthog/code → posthog/posthog monorepo move (now under
   `products/desktop/`) and lives squashed on a single branch as a demoable
   POC. Ticket actions (status/priority/snooze via PATCH, plus a human-typed
   reply / internal-note composer over the existing `reply` action) were
   pulled forward ahead of the loop — a queue that ranks work you can't act
   on isn't demoable. The stack's per-PR sections remain as the intended
   slicing if the POC graduates to reviewable PRs.

### Checklist model (the posthog/posthog piece)

`TicketChecklistItem` in `products/conversations/backend/models/`, following the
`TicketView` convention (`CreatedMetaFields, UpdatedMetaFields, UUIDModel`,
`team` FK):

- `ticket` FK, `text`, `position` (gap-spaced integer), `completed_at` /
  `completed_by` (nullable — completion is attributed, not boolean-only).
- **Author attribution on every item**: `created_by` (user FK, from
  `CreatedMetaFields`) for humans; nullable, with an `author_type` +
  agent/task-run reference, for agent-authored items. Humans and agents are
  equal writers — the API must not privilege either.
- **Audit-log semantics**: soft-delete only (`deleted` boolean, the standard
  posthog convention); state changes keep their actor and timestamp. Never
  hard-delete — a checklist that forgets who did what stops being an audit log.
- Exposed as a nested DRF route under `/conversations/tickets/{id}/checklist/`,
  then regenerated into `packages/api-client/src/generated.ts` alongside the
  existing `Ticket` types.

### The feature flag

- Key: `future-support` (matches the channel/plan name; distinct from the
  server-side `product-support-*` family, which gates the Conversations product
  itself — worth a comment on the flag to prevent the two being confused).
- Created in the PostHog App + Website project, rolled out to PostHog-internal
  only.
- Repo side: `packages/ui/src/features/support/featureFlag.ts` exporting
  `FUTURE_SUPPORT_FLAG = "future-support"` per the `agent-applications`
  precedent; UI gates on `useFeatureFlag(FUTURE_SUPPORT_FLAG)`, and the PR 3
  loop registration checks the same flag so a disabled feature schedules
  nothing.

---

## The PR stack (Graphite)

```
posthog/code (main)
└── support-01-ticket-read              # PR 1 ─┐
    └── support-02-attention-queue      # PR 2  ├─ "what do I work on"
        └── support-03-priority-loop    # PR 3 ─┘
            └── support-04-checklists       # PR 4 ─┐ "how do I work on it"
                └── support-05-agent-checklist  # PR 5 ┘
                    └── support-06-skill        # PR 6

posthog/posthog (independent, must land before PR 4)
└── PR 4a — TicketChecklistItem model + migration + nested DRF API
```

PR 4a is the only posthog/posthog work in the plan; PRs 1–3 need none. Cut it
early so review/migration lead time doesn't block the desktop side.

Each PR must pass `pnpm typecheck`, `pnpm lint`, `pnpm test`, and
`node scripts/check-host-boundaries.mjs` independently.

---

### PR 1 — Ticket read path (foundation)

**api-client**
- `conversations` methods per the `posthog-client.ts` pattern:
  `listTickets(projectId, params)`, `getTicket`, `listTicketViews`,
  `getUnreadCount`. Zod schemas alongside; generated types are the shape source.

**core**
- `SupportQueueService` (`@injectable`, api-client injected): list/read, view
  selection, pagination. Domain state in `zustand/vanilla`.

**ui**
- `packages/ui/src/features/support/` per the standard layout, plus a `CLAUDE.md`
  modelled on `features/inbox/CLAUDE.md` — including a **Backend Contracts**
  section pinning the exact Conversations REST paths.
- Ticket list + detail: thread, status, priority (**including "unset"**), assignee
  (user vs role), channel source, SLA due, tri-state `identity_verified`.
- `featureFlag.ts` exporting `FUTURE_SUPPORT_FLAG` — the whole feature surface
  mounts only when `useFeatureFlag(FUTURE_SUPPORT_FLAG)` is true.

**Acceptance**
- Real tickets list and open; untriaged (null-priority) and role-assigned tickets
  render correctly; an org with only some channels enabled renders without gaps.
- With the flag off, nothing renders and nothing fetches.

---

### PR 2 — The attention queue (resume vs new)

The core of the first half. Merges the four populations into one ranked surface.

**core (pure functions, no I/O, no LLM)**
- `classifyAttention(ticket, tasks, now)` → a reason-tagged actionability state:
  `customer-replied` (`pending`/`on_hold` + `unread_team_count > 0`),
  `agent-handed-back` (linked task complete/awaiting input),
  `sla-at-risk`, `snooze-elapsed`, `untriaged`, `in-progress`, `waiting-on-customer`.
- `rankQueue(classified, now, opts)` → deterministic ordering given a fixed `now`.
  Null priority must not sort as lowest by accident — untriaged is *unknown*, not
  *unimportant*.
- The ticket↔task join lives in `SupportQueueService`; the ranking functions stay
  pure and take the joined shape.

**ui**
- Ranked queue with a **reason chip on every row** ("customer replied 4m ago",
  "PR draft ready", "SLA in 90m"). Resume-vs-new is visible as a comparison, not
  buried in separate tabs.

**Acceptance**
- Unit tests per rule (`it.each`) covering each state, snooze boundaries, null
  priority, and role-vs-user assignment. Ranking deterministic for fixed `now`.
- A ticket whose customer just replied outranks an equivalent untouched new
  ticket, and the UI says why.

---

### PR 3 — Prioritisation loop

**harness / core**
- Background job (`background-jobs` extension) refreshes the queue **every 30
  minutes** (the agreed starting cadence — make it a named constant, expect
  tuning), re-classifies, and diffs against the previous run. Registration
  checks `future-support`; flag off → no job scheduled.
- Cross-run memory via the `scoutScratchpad` pattern so the loop doesn't
  re-announce what it already surfaced.
- **Notify only on genuine transitions** into an actionable state (customer
  replied, agent handed back, SLA crossed a threshold). Silent re-ranking
  otherwise — per design principle 5.

**ui**
- Newly-actionable items are marked in place; notifications route through
  `packages/core/src/notification`.

**Acceptance**
- A ticket transitioning to customer-replied surfaces without manual refresh, and
  announces exactly once across consecutive loop runs.
- Re-ranking with no state change produces zero notifications (regression test —
  this is the failure mode that gets the feature muted).

---

### PR 4a — Checklist model + API (posthog/posthog)

Per the [decision record](#decision-record-2026-07-28): `TicketChecklistItem`
model, migration, nested DRF endpoints, activity attribution, soft-delete.
Then regenerate `packages/api-client/src/generated.ts` in this repo.

**Acceptance**
- Human- and agent-authored items round-trip with correct attribution; deleting
  soft-deletes; completion records who and when.

### PR 4 — Ticket checklists (desktop)

**api-client / core**
- Checklist methods over the new endpoints; `TicketChecklistService` in core:
  ordered items (`text`, completion, optional `task_id` link, author) keyed by
  ticket. Reordering follows the gap-spaced-integer + reindex-on-collision
  approach used for tabs in `docs/plans/browser-tabs.md`.

**ui**
- Checklist on ticket detail: add/edit/tick/reorder/delete (delete = soft).
  Author attribution visible per item (human avatar vs agent marker). Visible
  from the queue row as progress (e.g. 2/5) so the return trip is legible
  before opening.

**Acceptance**
- Round-trip create → tick → reorder → restart the app → state intact (it's
  server-side now — also visible to a second engineer opening the same ticket).
- Queue rows show progress without an N+1 fetch per row.

---

### PR 5 — Agent-written checklists (the handoff)

Where the two halves meet: the agent that took the work reports back into the
same artefact the human reads on return.

**core**
- On linked-task lifecycle events, update the ticket's checklist: tick completed
  steps, append discovered next steps, link the produced task/PR.
- **Both directions**: an agent picking up a ticket reads the unchecked
  human-authored items as its brief — the checklist is the instruction channel
  in, not just the report channel out. Cloud agents write via the API directly
  (server-side persistence makes this work even with the desktop app closed).
- Agent-authored items are **visually distinct and human-editable** — an
  unreviewable agent-generated list is a second thing to audit, not a saving.

**Acceptance**
- Ticket → investigation task → completion → checklist reflects what happened and
  what's next, attributed to the agent.
- An unchecked human-authored item ("check if this reproduces on EU") shapes
  what the agent investigates.
- Returning to the ticket after an unrelated 40-minute detour requires no
  re-reading of the thread to know the next action. (This is the whole feature;
  worth an explicit E2E.)

---

### PR 6 — Support playbook skill

- `.claude/skills/handling-support-tickets/SKILL.md`: the resume-vs-new heuristics,
  how to leave a checklist for the next human touch, the identity-verification
  caveat, and the never-auto-send rule.

**Acceptance**
- An agent handed a ticket updates the checklist correctly without bespoke
  prompting.

---

## Security and privacy notes

- **Tickets contain customer PII and private operational detail.** Ticket or
  checklist text must never reach a PR description, commit message, or any public
  artifact. A ticket-spawned PR describes the *bug*, never the reporter.
- **`identity_verified` is tri-state deliberately** — only widget HMAC,
  SPF-verified email, or signed webhooks attest identity. An unverified reporter's
  claims about their own account are not authenticated; don't let ranking or an
  agent treat them as such.
- **Loop notifications leak metadata.** Titles/previews surface on the desktop;
  keep customer-identifying detail out of notification bodies.
- Ticket access inherits PostHog access control and API scopes; nothing custom.

## Testing

- **Unit (Vitest, colocated):** `classifyAttention` / `rankQueue` as pure-function
  tests (`it.each`) covering every state, snooze/SLA boundaries, null priority, and
  user-vs-role assignment; loop diffing including the announce-exactly-once and
  no-change-no-notification cases; `SupportQueueService` with a faked api-client
  per `docs/testing.md`; checklist reorder transforms.
- **E2E (Playwright, `tests/e2e/`):** ranked queue with reasons; customer-replied
  item surfacing via the loop; checklist round-trip; the return-trip flow in PR 5.
- After `packages/core` changes, `biome lint packages/core` with zero
  `noRestrictedImports`.

## Deferred

Deliberately out of the initial two halves, retained because the groundwork exists:

- **Reply drafting** — `POST .../{id}/suggest_reply/` is already generated and
  typed (`SuggestReplyResponse` / `SuggestReplyError`), backed by the existing
  Temporal pipeline in `products/conversations`. Consume that before building
  anything bespoke.
- **Diagnosis tooling** — scoped PostHog MCP access for replay/error-tracking
  lookup on the ticket's project. Needs a service-level project-scoping guard with
  a direct cross-project-read test before it ships.
- **Checklist templates** — explicitly deferred (decision 4). If real usage shows
  most tickets follow a handful of shapes, revisit; freeform first.

## Open questions

1. **Interrupt thresholds within the 30-minute loop** — the cadence is set, but
   which transitions earn a notification vs a silent re-rank (SLA at 2h? at
   30m?) is a judgement call best tuned by someone living in the queue during
   dogfood.
2. **Checklist API shape details** — item-level PATCH vs bulk reorder endpoint,
   and how the agent/task-run reference is modelled (`created_by=null` +
   metadata vs a dedicated FK). Settle in the PR 4a review, doesn't block PRs 1–3.

Recommended next step (per decision 7): demo the POC branch, then either
graduate it into the PR slicing above or keep building on it — the
30-minute loop and the server-side checklist/`Task.ticket` model are the
next pieces either way.
