# Plan — approvals UI in agent-console

**Status:** drafting. **Owner:** ben.

Backend for approval-gated tools shipped in v0 (see
[approval-gated-tools.md](approval-gated-tools.md) §10).
Frontend is empty.
This plan ships the console UI on top of the existing janitor + Django surface.

## 1. Context (don't re-derive)

Already on disk:

- Runtime store: `agent_tool_approval_request` table,
  [PgApprovalStore.listByTeam / listByApplication / listBySession](../../../services/agent-shared/src/persistence/pg-approval-store.ts).
- Janitor HTTP: `GET /approvals?application_id=…`,
  `GET /approvals/:id`, `POST /approvals/:id/decide` in
  [server.ts:529-644](../../../services/agent-janitor/src/server.ts).
- Django proxy: `agent_applications_approvals_{list,retrieve,decide}` in
  [api.py:1343-1466](../../../products/agent_platform/backend/api.py),
  team-admin gated.
- Generated FE types: `AgentApprovalRequest`, `DecideApprovalRequest` etc.
  in [products/agent_platform/frontend/generated/api.schemas.ts](../../../products/agent_platform/frontend/generated/api.schemas.ts).
- e2e backend coverage:
  [services/agent-tests/src/cases/approval-gated.test.ts](../../../services/agent-tests/src/cases/approval-gated.test.ts).
- Existing fleet shell: `/agent_fleet/stats/` + `/agent_fleet/live_sessions/`
  in [api.py:2560](../../../products/agent_platform/backend/api.py),
  consumed by [agent-console/src/lib/apiClient.ts:getFleetStats](../../../services/agent-console/src/lib/apiClient.ts).

Console gaps:

- `getFleetStats` hardcodes `approvalsPendingCount: 0`
  ([apiClient.ts:744-751](../../../services/agent-console/src/lib/apiClient.ts)).
- No fleet-wide approvals list endpoint (only per-app exists).
- No screen / route / detail surface in the console.
- `awaiting_approval` SessionState dot in
  [runnerReducer.ts:177-178](../../../services/agent-console/src/lib/runnerReducer.ts)
  - SessionsList / LiveNowPanel / AgentOverview is **misleading** —
    the runner doesn't park on approval gates per the plan. Clean up alongside.

## 2. Decisions (calls made now)

- **Surfaces:** top-level `/approvals` (fleet, with agent filter chip) +
  per-agent tab `/agents/[slug]/approvals`.
  Both reuse the same list component.
- **Detail UX:** drawer slide-in over the list (not a separate page) so
  approvers can rip through a queue. Mirror existing dock idiom.
- **`allow_edit` diff UX:** free-form JSON editor (CodeMirror via Quill)
  pre-filled with `proposed_args`, plus a "Reset to proposed" button.
  Client-side parse check only; server already 422s on
  `edits_not_allowed` and downstream tool schema rejection lands as
  `dispatch_outcome.error`.
  Structured/schema-driven editing deferred — tool input schemas aren't on
  the approval row payload today.
- **Refresh:** 10s poll while the list is mounted, pause when
  `document.hidden`. No SSE wiring.
- **Auth UX:** API 404s for non-admins.
  Hide the sidebar item + per-agent tab when the current user isn't a
  team admin.
  Bootstrap payload already carries org-membership level —
  check what `agent-console` already loads (probably need to plumb
  `is_team_admin` through).
- **Cleanup:** kill the `awaiting_approval` SessionState branch in
  runnerReducer + the three render sites.
  The runner's `waiting` event is only fired by `meta-ask-for-input`
  today; rename the state to `awaiting_user_input` (or fold into the
  `awaiting_client_tool` bucket) once verified.
  Do this as the last commit, separate from the approvals feature
  itself.

## 3. Backend

### 3.1 Janitor — fleet-wide list

[services/agent-janitor/src/server.ts](../../../services/agent-janitor/src/server.ts):

- Extend `ListApprovalsQuerySchema` to accept `team_id` **or**
  `application_id` (one required, mutually exclusive).
- When `team_id` set, call `opts.approvals!.listByTeam(team_id, …)`.
- Existing `application_id` path unchanged.
- Optional: add a `?count=true` short-circuit returning
  `{ pending: number }` for the stats roll-up, or just expose a sibling
  `GET /approvals/stats?team_id=…`.
  Pick the sibling — clearer.

### 3.2 Janitor — fold pending count into existing aggregate

Cheaper than a second round-trip from the fleet-stats endpoint.

[services/agent-shared/src/persistence/queue.ts](../../../services/agent-shared/src/persistence/queue.ts) +
[pg-queue.ts](../../../services/agent-shared/src/persistence/pg-queue.ts):

- Don't touch `AggregateStats` (queue concern).
- Instead extend the janitor's `/sessions/stats` (or `/fleet/stats`,
  whichever the Django `aggregate_for_team` hits) to also query
  `ApprovalStore` for `count(state='queued') WHERE team_id=…`.
  Add `pendingApprovalsCount` to the response.
- New `ApprovalStore.countQueuedByTeam(teamId)` method —
  one-line `SELECT count(*) … WHERE team_id=$1 AND state='queued'`.

### 3.3 Django proxy

[products/agent_platform/backend/api.py](../../../products/agent_platform/backend/api.py):

- New `AgentFleetViewSet.approvals` action:
  `GET /agent_fleet/approvals/?state=queued&agent_id=…&limit=…&offset=…`.
  Same admin gate (`_require_team_admin`).
  Proxies `janitor_client.list_approvals_for_team(team_id, …)`.
  Decide action stays on the per-app viewset (URL needs an
  application_id for cross-checking ownership).
- `_AGENT_AGGREGATE_STATS` serializer gains `pendingApprovalsCount`
  field — schema annotation flows into generated types automatically.
- [janitor_client.py](../../../products/agent_platform/backend/janitor_client.py):
  add `list_approvals_for_team(team_id, state=…, agent_id=…, limit=…, offset=…)`.

### 3.4 Regen types

```bash
hogli build:openapi
```

Will update both
[frontend/generated/api.schemas.ts](../../../products/agent_platform/frontend/generated/api.schemas.ts)
and
[services/agent-console/src/generated/agent-platform.api.schemas.ts](../../../services/agent-console/src/generated/agent-platform.api.schemas.ts)
(check both regenerate — the console pulls a separate snapshot).

## 4. Frontend — agent-console

### 4.1 Wire pendingApprovalsCount

[services/agent-console/src/lib/apiClient.ts](../../../services/agent-console/src/lib/apiClient.ts) —
in `getFleetStats`, replace the hardcoded `0` with the new field.
Existing Overview / AgentsList tiles will light up automatically.

### 4.2 Shared list component

New
`services/agent-console/src/components/ApprovalsList.tsx`:

- Props: `teamId`, optional `agentId`, optional `agentsById` for name
  rendering in fleet mode.
- Internal: state-tab strip (`queued` default, plus
  approving / dispatched / rejected / expired), agent filter chip
  (fleet mode only), simple `Card`-style rows.
- Row content: agent name (fleet), tool name (monospace), proposed-args
  one-liner (`JSON.stringify` truncated to ~80 chars), age, expires-in
  countdown when queued.
- 10s `setInterval` poll wrapped in `cache.disposables.add` so the
  hidden-tab pause comes for free.
  See [.agents/skills/using-kea-disposables.md] equivalent — agent-console
  isn't kea, so just `setInterval` + cleanup in `useEffect`, gated on
  `document.visibilityState`.
- Click → `onSelect(id)`; parent owns the drawer.

Storybook companion `ApprovalsList.stories.tsx` covering: empty,
queued-only, mixed-states, agent-filtered, loading-skeleton.

### 4.3 Detail drawer

`services/agent-console/src/components/ApprovalDetail.tsx`:

- Loads via the existing per-app retrieve endpoint
  (`agent-applications-approvals-retrieve`).
  Easier than building a top-level retrieve; we already have the
  agent id from the row.
- Sections (top → bottom):
  1. Header: tool name + state pill + age + expires countdown.
  2. Assistant reasoning: render `assistant_message.text` and
     `assistant_message.thinking` as plain blocks (mirror the
     `<AgentChat />` turn-part styling — extract a shared
     `<AssistantBlocks>` component if needed).
  3. Proposed args: read-only JSON tree (Quill code block).
  4. Decision panel (queued state only):
     - Reason `textarea`.
     - "Approve" button.
     - "Approve with edits" disclosure (only when
       `approver_scope.allow_edit`) → CodeMirror JSON editor seeded
       with `proposed_args`, "Reset" button, parse-error inline.
     - "Reject" button (destructive variant).
     - All three buttons honor `loading` + `disabledReason` per the
       CLAUDE.md double-submit rule.
  5. Decided footer (non-queued state):
     - `decision_by` (resolve to display name via
       team-members lookup — already cached for sessions UI), timestamp,
       reason, diff of proposed → decided args when present.
     - `dispatch_outcome` block:
       success renders the result JSON; failure renders the error red.

Decide action posts through the generated
`agentApplicationsApprovalsDecide` client (or the equivalent name —
check `agent-platform.api.ts`).
Optimistically remove the row from the list on success.

Storybook companion covering each state + edit-enabled and not.

### 4.4 Fleet screen

New `services/agent-console/src/screens/Approvals.tsx` + a Next.js
route page under `services/agent-console/src/app/approvals/page.tsx`:

- Page layout matches Overview / AgentsList — `max-w-5xl`,
  header + helper text.
- Mounts `<ApprovalsList teamId={…} agentsById={…} />` with no
  `agentId`.
- Drawer-style detail uses
  `<Dialog>` / `<Sheet>` from Quill — pick whichever the existing
  surfaces use (SessionDetail's secret edit dialog is the precedent
  via [SecretEditDialog.tsx](../../../services/agent-console/src/components/SecretEditDialog.tsx)).

Add to the sidebar:
[AppShell.tsx](../../../services/agent-console/src/components/AppShell.tsx) —
new `<SidebarTooltip label="Approvals">` icon block between Agents and
"Tools & skills".
`CheckSquareIcon` from lucide is the natural pick.
Show a count badge from `fleetStats.pendingApprovalsCount` when > 0.

Gate the sidebar item on `is_team_admin`.

### 4.5 Per-agent tab

[AgentLayout.tsx](../../../services/agent-console/src/components/AgentLayout.tsx) —
extend `TABS` and `TAB_DEFS`:

```ts
{ key: 'approvals', label: 'Approvals', path: '/approvals' },
```

Insert between `sessions` and `memory`.
Page lives at
`services/agent-console/src/app/agents/[slug]/approvals/page.tsx`,
renders the same `<ApprovalsList>` with `agentId` set.
Drawer same as fleet.

Hide the tab for non-admins.
Drop a count badge on the tab label when there are pending approvals
for this agent (cheap — already filtered list response carries the count).

### 4.6 Cross-link from session detail

[SessionLogs.tsx](../../../services/agent-console/src/components/SessionLogs.tsx) —
when a `tool_result` payload parses as
`{ approval: { request_id, state: "queued", approval_url } }`,
render the tool name with a "Pending approval" chip that opens the
drawer directly (preload the row by `request_id` via the per-app
retrieve endpoint).
Same parse logic the harness uses in
[approval-gated.test.ts:parseApprovalPayload](../../../services/agent-tests/src/cases/approval-gated.test.ts) —
factor that out into the runtime types package so it's shared.

### 4.7 Cleanup — misleading awaiting_approval state

Last commit of the stack.

- [runnerReducer.ts:177-178](../../../services/agent-console/src/lib/runnerReducer.ts) —
  remove the `awaiting_approval` case; map the `waiting` event to
  `awaiting_user_input` (a new state) or fold into the existing
  `awaiting_client_tool` bucket if semantics line up.
  Verify by reading what triggers the `waiting` SSE event in
  [services/agent-runner/src/loop/bus.ts](../../../services/agent-runner/src/loop/bus.ts) /
  [agent-ingress/src/triggers/chat.ts](../../../services/agent-ingress/src/triggers/chat.ts).
- Remove the `awaiting_approval` branch from
  [SessionsList.tsx:158-159](../../../services/agent-console/src/components/SessionsList.tsx),
  [LiveNowPanel.tsx:130-131](../../../services/agent-console/src/components/LiveNowPanel.tsx),
  [AgentOverview.tsx:286-287](../../../services/agent-console/src/components/AgentOverview.tsx).
- Remove `awaiting_approval` from `LIVE_STATES` in
  [SessionsList.tsx:30](../../../services/agent-console/src/components/SessionsList.tsx).

## 5. Test paths

### 5.1 Backend

[services/agent-tests/src/cases/approval-gated.test.ts](../../../services/agent-tests/src/cases/approval-gated.test.ts)
already covers the runtime loop.
Extend it (or sibling case) for the new wire shapes:

- `GET /approvals?team_id=…` returns rows across multiple agents.
- `GET /sessions/stats` (or whichever endpoint backs
  `aggregate_for_team`) includes `pendingApprovalsCount`.

Django unit test in
`products/agent_platform/backend/test_approvals_api.py` for the new
fleet action's admin gate + agent_id filter.

### 5.2 Frontend

Storybook stories per component drive visual coverage.
No jest tests for the components themselves —
console convention.
The console already runs `pnpm storybook` for review.

### 5.3 Manual e2e

The point of this work is to drive a real approval through the UI.
Steps to verify locally:

1. `hogli start` + `pnpm --filter @posthog/agent-console dev`.
2. Use the concierge agent OR the
   [agent-tests/src/examples/agent-concierge](../../../services/agent-tests/src/examples/agent-concierge)
   fixture as a seed.
   Add a single gated tool to its `spec.json` —
   `requires_approval: true` on something cheap like
   `@posthog/memory-write`.
   Promote to live.
3. Trigger a chat session from the playground asking the agent to
   write to memory.
4. Watch the session detail page — the tool_result chip should render
   "Pending approval".
5. Open `/approvals` in another tab → row should appear, count badge
   should update on next 10s tick.
6. Click → drawer opens → approve.
7. Session detail refreshes → memory write lands → row state flips to
   `dispatched` in the inbox.

If we don't already have a concierge variant with a gated tool,
add `services/agent-tests/src/examples/agent-concierge/spec.json`
note (or a sibling fixture) so this stays reproducible.

## 6. PR slicing

1. Backend: janitor team-list + fleet stats count + Django proxy + regen.
2. Frontend: `<ApprovalsList>` + `<ApprovalDetail>` + Storybook.
3. Frontend: fleet screen + sidebar entry + wire pendingApprovalsCount.
4. Frontend: per-agent tab.
5. Frontend: session-detail cross-link.
6. Cleanup: kill the misleading `awaiting_approval` state.

Ship 1+2 together if 2 is small, otherwise keep separate so the
backend can land independently.
