# Sandbox wire-notification rendering: resources_used bar + usage/status/compaction/task/sdk notifications

> **Source:** outstanding_items.md § 8 "\_posthog/resources_used" (§3.2) + § 8 "Other typed-but-unrendered_posthog/\* notifications" (§3.1) · **Locus:** frontend — notification dispatch + render surfaces
> **Effort:** M total, ships incrementally (each notification is an independent slice; resources_used + usage_update are the only two worth a first cut) · **Priority:** Medium (resources_used) / low-medium (rest) · **Blocks rollout:** No
> **Joins:** All five notification families (`resources_used`, `usage_update`, `status`+`compact_boundary`, `task_notification`, `sdk_session`) are folded into one pass because they share a single dispatch locus — they are all typed in `sandboxWireTypes.ts` but silently dropped at the same `method?.startsWith('_posthog/')` catch-all in `sandboxStreamLogic.ingestAcpFrame`. Each needs the identical wiring change (a new `if (method === ...)` branch above that catch-all) plus its own render surface, so doing them together avoids re-touching the dispatch switch five times. `_posthog/progress` is **excluded** (see Approach — it is already consumed).

## Problem

The PostHog AI sandbox runtime streams ACP frames from the in-sandbox agent server (the ported Twig agent) over SSE. A family of `_posthog/*` notifications is fully typed on the frontend (`frontend/src/scenes/max/types/sandboxWireTypes.ts`) but never rendered: the dispatch handler `sandboxStreamLogic.ingestAcpFrame` recognizes a handful of methods (`run_started`, `turn_complete`, `progress`, `error`, `permission_request`, `permission_resolved`) and then **drops everything else** under a `method?.startsWith('_posthog/')` early-return. The dropped set includes:

- **`_posthog/resources_used`** — the agent reports, per turn, the list of PostHog products an answer was grounded in (derived from MCP `exec` inner-tool calls, e.g. `query-trends` → Product analytics). This is the single product signal that _every_ Max data conversation generates. Twig renders it as a persistent "PostHog resources used" badge bar above the composer. PostHog throws it away.
- **`_posthog/usage_update`** — token usage + cost, plus a context-window composition breakdown. Twig renders a context-usage ring + a breakdown popover in the session footer. PostHog throws it away.
- **`_posthog/status`** + **`_posthog/compact_boundary`** — context-compaction start/end and the post-compaction marker. Twig renders both inline in the thread (a spinner line while compacting, a "Conversation compacted" rule after). PostHog throws them away.
- **`_posthog/task_notification`** — task milestone (completed / failed / stopped + summary). Twig renders an inline colored rule. PostHog throws it away.
- **`_posthog/sdk_session`** — maps `taskRunId` → agent `sessionId` + adapter name; diagnostic only. Twig does not render it as UI; it is resume plumbing. PostHog throws it away (correct today, but it is worth at least logging for debugging).

The net effect: Max sandbox conversations lose the "what products did the agent touch", "how much context/cost did this turn use", and "the agent just compacted history" affordances that the reference implementation ships. None of these are correctness bugs — the conversation still works — but they are visible parity gaps versus Twig, and `resources_used` in particular is a high-value product signal that ties to the small-data-sandbox work (G1).

## Current behavior (verified)

**Dispatch drop site — the doc cited `~:914`; confirmed at `frontend/src/scenes/max/sandboxStreamLogic.ts:914-917`:**

```ts
if (method?.startsWith('_posthog/')) {
  // _posthog/usage_update, _posthog/console, _posthog/sdk_session, _posthog/git_checkpoint, ...
  return
}
```

Handlers that already exist _above_ this catch-all (the pattern every new branch follows) — all in `ingestAcpFrame`:

- `_posthog/run_started` → `markRunStarted()` + telemetry (`sandboxStreamLogic.ts:856-877`)
- `_posthog/turn_complete` → `markTurnComplete()` (`:878-881`)
- `_posthog/progress` → `setCurrentProgress(...)` (`:882-886`) — **already consumed**, drives `SandboxThinkingIndicator`
- `_posthog/error` → `pushErrorItem(...)` (`:887-891`)
- `_posthog/permission_request` / `_posthog/permission_resolved` (`:896-913`)

**Wire types — the doc cited `frontend/src/scenes/max/sandboxWireTypes.ts`; the real path is `frontend/src/scenes/max/types/sandboxWireTypes.ts`.** The cited `_posthog/resources_used` type at `~:288-291` is confirmed at `sandboxWireTypes.ts:288-291`:

```ts
export interface PosthogResourcesUsedParams {
  sessionId?: string
  products?: { id?: string; label?: string }[]
}
```

The other notification params (all confirmed present):

- `PosthogUsageUpdateUsedParams` (`sandboxWireTypes.ts:235-240`) — `{ sessionId?, used: PosthogUsageTokens, cost?: { amount?, currency? } | null }`
- `PosthogUsageUpdateBreakdownParams` (`:242-254`) — `{ sessionId?, breakdown: { systemPrompt?, tools?, rules?, skills?, mcp?, subagents?, conversation? } }`
- `PosthogUsageTokens` (`:228-233`) — `{ inputTokens?, outputTokens?, cachedReadTokens?, cachedWriteTokens? }`
- `PosthogStatusParams` (`:256-260`) — `{ sessionId?, status?, isComplete? }`
- `PosthogCompactBoundaryParams` (`:262-267`) — `{ sessionId?, trigger?, preTokens?, contextSize? }`
- `PosthogTaskNotificationParams` (`:269-275`) — `{ sessionId?, taskId?, status?, summary?, outputFile? }`
- `PosthogSdkSessionParams` (`:282-286`) — `{ taskRunId?, sessionId?, adapter? }`
- The method→params map `PosthogNotificationParamsByMethod` (`:319-335`) and the narrowing helper `isPosthogNotification` (`:341-346`), plus two usage discriminators `isUsageUpdateUsedParams` (`:348-352`) and `isUsageUpdateBreakdownParams` (`:354-358`) — all already wired.

**Render plumbing into the thread.** The sandbox thread is a separate render path from LangGraph, selected by `conversation.agent_runtime === 'sandbox'`:

- `SandboxThread` (`frontend/src/scenes/max/Thread.tsx:152-194`) maps `sandboxStreamLogic.values.threadItems` and dispatches tool cards. `ThreadItem` is an append-only ordered list; its discriminator `ThreadItemType` (`frontend/src/scenes/max/types/sandboxStreamTypes.ts:50`) is `'human_message' | 'assistant_message' | 'tool_invocation' | 'turn_separator' | 'error'` — inline notifications (status/compact/task) would extend this union.
- The `threadItems` reducer lives at `sandboxStreamLogic.ts:429-485`; it already folds `pushErrorItem` → `{ type: 'error', errorMessage }` (`:479-482`) and `markTurnComplete` → `{ type: 'turn_separator' }` (`:478`). That is the exact precedent an inline notification follows.
- The composer mounts _separately_ from the thread: `Thread` is rendered at `Max.tsx:145`, and the sticky composer (`SidebarQuestionInput`) at `Max.tsx:147`, both inside a `ThreadAutoScroller`. A persistent "above the composer" bar (resources, usage ring) therefore lives outside `SandboxThread` — it reads `sandboxStreamLogic` values directly via a `BindLogic` and mounts between `<Thread/>` and the composer (or inside the composer's own header).

**Twig reference treatment (confirmed by reading the upstream).** Note: `Twig/...` paths below are **not in this repo** — they live in the sibling checkout at `/Users/georgiy/Projects/posthog/Twig` (the reference agent implementation), per outstanding_items.md § 8. Treat them as read-only design references, not files to edit here.

- Resources bar: `Twig/packages/ui/src/features/sessions/components/SessionResourcesBar.tsx` — a persistent badge row above the composer; hidden until ≥1 product; de-duplicated, first-seen-ordered; each chip is an icon + label, click-through to the product docs page. Accumulation logic (pure, no React): `Twig/packages/ui/src/features/sessions/components/accumulateSessionResources.ts` walks all `_posthog/resources_used` notifications and unions `products` by `id`. Product taxonomy + labels: `Twig/packages/agent/src/posthog-products.ts` (`POSTHOG_PRODUCTS`, `PostHogProductId`) — 14 ids (`product_analytics`, `web_analytics`, `feature_flags`, `experiments`, `error_tracking`, `session_replay`, `surveys`, `llm_analytics`, `data_warehouse`, `cdp`, `logs`, `apm`, `sql`, `posthog`).
- Usage: `extractContextUsage` (`Twig/packages/core/src/sessions/contextUsage.ts`) reads the latest aggregate (`used`/`size`/`cost`) **from a `session/update`-framed `usage_update`**, and the latest `breakdown` **from the `_posthog/usage_update` ext-notification**, then merges. Rendered by `ContextUsageIndicator.tsx` (a `used/size · %` ring) + `ContextBreakdownPopover.tsx`, mounted in `SessionFooter.tsx`.
- Status / compaction: `StatusNotificationView.tsx` (spinner "Compacting conversation history…" only when `status === 'compacting' && !isComplete`, generic "Status: x" otherwise) and `CompactBoundaryView.tsx` ("Conversation compacted" rule with `trigger` badge + `~NK tokens summarized`). Dispatched inline by `session-update/SessionUpdateView.tsx:109-123`.
- Task notification: `TaskNotificationView.tsx` (green/red/orange inline rule by `status`, plus `summary`). Dispatched at `SessionUpdateView.tsx:131-134`.
- SDK session: no UI; it is `taskRunId → sessionId/adapter` resume plumbing on the agent side.

**Wire-shape drift you must account for (verified against the Twig emitters):**
The PostHog `usage_update` types model the **Codex** emission, which sends two separate `_posthog/usage_update` ext-notifications: one `{ used: {…}, cost: null }` and one `{ breakdown: {…} }` (`Twig/packages/agent/src/adapters/codex/codex-agent.ts:750-777`). But the **Claude** adapter sends a _single combined_ ext-notification carrying `used` (tokens object), `cost` (a bare **number**, not `{amount,currency}`), AND `breakdown` together (`Twig/packages/agent/src/adapters/claude/claude-agent.ts:782-798`); and the numeric **`used`/`size` aggregate that drives the percentage ring is NOT in the `_posthog/usage_update` frame at all** — it arrives on a separate `session/update`-framed update (`sessionUpdate: 'usage_update', used: <number>, size: <number>, cost: {amount, currency}`) at `claude-agent.ts:760-774`. So:

1. PostHog's `PosthogUsageUpdateUsedParams.cost` is typed `{ amount?, currency? } | null` — that matches the _session/update_ aggregate's cost shape, but the Claude _ext-notification's_ `cost` is a raw number. The union currently can't represent "used + cost + breakdown in one frame", and the `isUsageUpdateUsedParams`/`isUsageUpdateBreakdownParams` discriminators (which check `'used' in params` / `'breakdown' in params`) would both be true for the Claude combined frame.
2. There is **no PostHog type for the numeric `used`/`size` `session/update` aggregate** that the context ring needs. `KNOWN_SESSION_UPDATES` (`sandboxWireTypes.ts:186-192`) does not include `usage_update`, so even the session/update form is dropped by `isKnownSessionUpdate`.
   This is the single most important thing to get right before building the usage UI — see Decisions.

## Approach

Add one dispatch branch per notification family above the `_posthog/` catch-all (`sandboxStreamLogic.ts:914`), each feeding a new piece of logic state, and render each on the surface that mirrors Twig. Ship in priority order; every slice is independent.

**(A) `_posthog/resources_used` → persistent bar above the composer (priority: Medium; ship first).**

- New reducer `resourcesUsed: ResourceProduct[]` on `sandboxStreamLogic`, folded by a `mergeResourcesUsed(products)` action that unions by `id`, first-seen order (mirrors `accumulateSessionResources`). Cleared on `reset`. _Do not_ clear on `markTurnComplete` — Twig accumulates across the whole session.
- Dispatch: `if (isPosthogNotification(notification, '_posthog/resources_used')) { actions.mergeResourcesUsed(notification.params?.products ?? []); return }`. Folds identically on live SSE and on `bootstrapRun` log replay (both call `ingestAcpFrame`), so a reopened conversation rebuilds the bar for free.
- Render: a new `SandboxResourcesBar.tsx` component reading `sandboxStreamLogic.values.resourcesUsed`, mounted between `<Thread/>` and the sticky composer in `Max.tsx` (or appended at the tail of `SandboxThread` if mounting above the composer proves layout-awkward in the side panel — see Decisions). Hidden when empty. Each chip = product icon + Sentence-cased label; reuse PostHog's own product icons from `@posthog/icons` rather than porting Twig's phosphor set. Optional docs click-through (low value in-app; recommend dropping it for v1 — see Decisions).
- Needs a PostHog-side product-id → label/icon map. Port `POSTHOG_PRODUCTS` ids and labels into a small frontend constant (the wire already sends `{id, label}`, so `label` can be taken from the wire with the constant as the icon source + fallback label). Sentence casing per CLAUDE.md ("Product analytics", not "Product Analytics").

**(B) `_posthog/usage_update` → context-usage ring + cost (priority: low-medium).**
Resolve the wire-shape drift first (Decisions D1). Then:

- New reducer `contextUsage: { used?, size?, percentage?, cost?, breakdown? } | null`. Fold the latest token/cost from the `used` form and the latest `breakdown` from the breakdown form, tolerating the Claude combined frame. The numeric `used`/`size` percentage aggregate requires also accepting the `session/update`-framed `usage_update` (add `'usage_update'` to `KNOWN_SESSION_UPDATES` and a `SessionUpdateUsage` body type, OR special-case it before `isKnownSessionUpdate` — recommend the latter to avoid widening the tool-render switch).
- Render: a compact ring/label in the composer footer area (mirror `ContextUsageIndicator`), reading the logic value. A breakdown popover is a nice-to-have; recommend deferring it (D2). Token + cost can render as a single line first; the ring is polish.

**(C) `_posthog/status` + `_posthog/compact_boundary` → inline thread items (priority: low-medium).**

- Extend `ThreadItemType` with `'status'` and `'compact_boundary'`; extend `ThreadItem` with the small param subset each needs (`status`, `isComplete`, `trigger`, `preTokens`, `contextSize`).
- Dispatch: push a thread item from each. For `status` with `status === 'compacting' && isComplete`, push nothing (Twig renders nothing for the complete case) — or push then remove; simplest is to gate at dispatch. `compact_boundary` always pushes.
- Render in `SandboxThread` (`Thread.tsx`): two new `if (item.type === ...)` branches mirroring `StatusNotificationView` / `CompactBoundaryView`, using `LemonBanner`/inline styling with tailwind utilities (no inline styles). These render in chronological order with the rest of the thread automatically.

**(D) `_posthog/task_notification` → inline thread item (priority: low-medium).**

- Same mechanism as (C): `ThreadItemType` gains `'task_notification'`; dispatch pushes `{ type, status, summary }`; `SandboxThread` renders a colored inline rule (green/red/orange by status) mirroring `TaskNotificationView`. Note: for PHAI data conversations, task milestones may be rare; ship last.

**(E) `_posthog/sdk_session` → diagnostic only (priority: lowest).**

- No UI. Either leave it in the catch-all (status quo) or add a branch that stores `{ adapter, sessionId }` in logic state for debugging + emits nothing visible. Recommend: a one-line branch that stashes `sdkSession` in a reducer (handy for the crash-affordance work in G7) and optionally a `posthog.capture` debug breadcrumb. Do **not** build UI.

**Excluded: `_posthog/progress`.** The doc's § 3.1 calls it deliberately excluded "no Twig adapter emits it". Two things are true and both mean _do nothing_: (1) PostHog **already consumes** it (`sandboxStreamLogic.ts:882-886` → `setCurrentProgress` → `SandboxThinkingIndicator`), and (2) Twig's `ProgressGroupView` exists but the live PHAI agent path does not emit `_posthog/progress` group frames today. So `progress` is neither dropped nor a gap — leave it.

**Alternatives rejected:**

- _Rendering resources/usage inline in the thread_ (as turn-end items) instead of a persistent bar — rejected: Twig's whole-session accumulation model means a per-turn inline list would repeat products and clutter the thread; the persistent bar is the right affordance and matches the reference.
- _One mega-reducer for all notifications_ — rejected: resources (session-cumulative bar), usage (latest-wins footer), and inline events (append-only thread) have genuinely different lifetimes; separate reducers keep each correct and testable.
- _Fixing the usage wire types to the Codex shape only_ — rejected: would silently drop Claude usage (the primary adapter), and Claude is what PHAI runs.

## Implementation steps

1. **Product taxonomy constant (for A).** Add a frontend constant mapping `PostHogProductId` → `{ label, Icon }` (port the ids and their labels verbatim from `POSTHOG_PRODUCTS` in `Twig/packages/agent/src/posthog-products.ts`; icons from `@posthog/icons`). Co-locate with the new bar component. Note: the labels are _not_ a mechanical sentence-casing of the id — `llm_analytics → "AI observability"`, `cdp → "Data pipelines"`, plus all-caps acronyms (`apm → "APM"`, `sql → "SQL"`) — so copy the label map directly rather than deriving it from the id. The wire still sends `{id, label}`, so the local constant is the icon source + fallback label only.
2. **resources_used (A):** add `mergeResourcesUsed` action + `resourcesUsed` reducer (union-by-id, first-seen) to `sandboxStreamLogic`; add the dispatch branch above `:914`; write `SandboxResourcesBar.tsx`; mount it in `Max.tsx` between `<Thread/>` and the composer (behind the sandbox-runtime guard). Ship + verify against a live data conversation.
3. **usage_update (B):** resolve D1; widen/replace the usage param union and add a session/update `usage_update` acceptor; add `contextUsage` reducer + dispatch; write the footer ring/label component; mount near the composer. Ship.
4. **status + compact_boundary (C):** extend `ThreadItemType` + `ThreadItem`; add two dispatch branches (gate the `compacting && isComplete` no-render case); add two render branches in `SandboxThread`. Ship.
5. **task_notification (D):** extend `ThreadItemType` + `ThreadItem`; add dispatch + render branch. Ship.
6. **sdk_session (E):** add a `sdkSession` reducer + branch (no UI); optional debug capture. Ship.
7. Run `pnpm --filter=@posthog/frontend typescript:check` and `format` after each slice; the `sandboxStreamLogicType.ts` kea typegen regenerates on build.

## Files to change

| Path                                                               | Change                                                                                                                                                                                                  |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `frontend/src/scenes/max/sandboxStreamLogic.ts`                    | New actions + reducers (`mergeResourcesUsed`/`resourcesUsed`; `setContextUsage`/`contextUsage`; inline-item pushes; `sdkSession`); new dispatch branches in `ingestAcpFrame` above the `:914` catch-all |
| `frontend/src/scenes/max/types/sandboxStreamTypes.ts`              | Extend `ThreadItemType` + `ThreadItem` with `status` / `compact_boundary` / `task_notification` fields; add `ResourceProduct` and `ContextUsage` interfaces                                             |
| `frontend/src/scenes/max/types/sandboxWireTypes.ts`                | Fix the `usage_update` union to represent the Claude combined frame + the numeric `session/update` aggregate (D1); possibly add `usage_update` to `KNOWN_SESSION_UPDATES`                               |
| `frontend/src/scenes/max/Thread.tsx`                               | New `if (item.type === 'status' / 'compact_boundary' / 'task_notification')` render branches in `SandboxThread`                                                                                         |
| `frontend/src/scenes/max/components/SandboxResourcesBar.tsx` (new) | Persistent product-chip bar; reads `sandboxStreamLogic.resourcesUsed`                                                                                                                                   |
| `frontend/src/scenes/max/components/SandboxContextUsage.tsx` (new) | Context-usage ring/label; reads `sandboxStreamLogic.contextUsage`                                                                                                                                       |
| `frontend/src/scenes/max/Max.tsx`                                  | Mount the resources bar + usage indicator near the composer, behind the sandbox-runtime guard                                                                                                           |
| `frontend/src/scenes/max/messages/posthogProducts.ts` (new)        | Product-id → label + `@posthog/icons` icon map (ported ids/labels)                                                                                                                                      |
| `frontend/src/scenes/max/sandboxStreamLogicType.ts`                | Regenerated by kea typegen (do not hand-edit)                                                                                                                                                           |

## Decisions & open questions

- **D1 — usage_update wire-shape reconciliation (must decide before B).** The typed union models the Codex split; the Claude adapter sends `used`+`cost`(number)+`breakdown` in one frame and the numeric `used`/`size` aggregate on a `session/update`. **Recommendation:** replace the `Used | Breakdown` union with a single permissive `PosthogUsageUpdateParams { sessionId?; used?: PosthogUsageTokens; cost?: number | { amount?; currency? } | null; breakdown?: {…} }`, and add explicit handling of the `session/update`-framed `usage_update` (special-cased before `isKnownSessionUpdate`, carrying numeric `used`/`size`). Keep both discriminators but treat them as "has field" checks rather than mutually exclusive. This is the only change that captures both adapters and the percentage ring.
- **D2 — context-window breakdown popover.** Twig ships a 7-segment breakdown popover. **Recommendation:** defer for v1 — render token/cost (and a ring if cheap) first; the breakdown popover is polish and depends on D1 landing cleanly. Revisit if users ask.
- **D3 — resources-bar mount point.** Above the composer (Twig) vs. tail of the thread. **Recommendation:** mount in `Max.tsx` between `<Thread/>` and `SidebarQuestionInput` so it is persistent and not scrolled away, matching Twig. If the side-panel sticky-composer layout makes that awkward, fall back to a sticky element at the bottom of `SandboxThread`. Decide after one layout spike.
- **D4 — docs click-through on resource chips.** Twig links each chip to posthog.com docs. **Recommendation:** drop external doc links for v1 (in-app users don't want to leave Max); if anything, link to the in-app product scene. Low value — defer.
- **D5 — does PHAI want the resources affordance at all?** outstanding*items.md § 3.2 flags this as a product decision. **Recommendation:** yes — it is the one signal every data conversation emits and it reinforces "Max answered this from \_your* PostHog data", which is on-brand. Confirm with the Max product owner before building B–E, but A is low-risk and high-signal enough to ship regardless.
- **D6 — inline notification ordering vs. turn separators.** status/compact/task items append to `threadItems` and render in arrival order. **Recommendation:** push them as their own items (like `error`/`turn_separator` already do); no special interleaving logic needed since the wire delivers them in order.

## Dependencies & sequencing

- **Within this pass:** order is A → B → C → D → E by priority/value. A and (C/D/E) only touch the dispatch switch + a reducer + a render branch and are mutually independent. B is the only one with a real prerequisite (D1 wire-shape reconciliation) and is the riskiest, so it can lag A.
- **G1-small-data-sandboxes.md** — `resources_used` (A) is _exactly_ the per-turn signal that data-only conversations emit; it is the product evidence that motivates G1's small tier. A is the natural UI companion to G1 but does **not** depend on it (no shared code) — cross-reference only.
- **G5-sandbox-tool-card-parity.md** — owns the `_meta.claudeCode.*` consumption and tool-card display mapping. The `resources_used` products are derived by the agent from the _same_ `exec` inner-tool calls G5's `resolveToolKey` inspects, but the rendering surfaces are disjoint (G5 = per-tool cards; G6 = aggregate bar). No code overlap; do not touch `resolveToolKey` or `mcpToolRegistry` here.
- **G7-sandbox-streaming-resilience.md** — the `sdk_session` reducer (E) gives G7's crash affordance the adapter/session identity for telemetry; coordinate the reducer shape if G7 lands first, otherwise G7 can read whatever E stores.
- No backend changes. No serializer/viewset/`lib/api` changes, so `/improving-drf-endpoints` and `/adopting-generated-api-types` do **not** apply.

## Testing

- **Jest unit (logic):** add cases to the `sandboxStreamLogic` test suite asserting `ingestAcpFrame` with each new `_posthog/*` frame mutates the right reducer: `resources_used` unions by id and survives `bootstrapRun` replay (feed the same frame twice → one entry); `usage_update` (both Codex split frames and the Claude combined frame + the `session/update` aggregate) lands the right `contextUsage`; status/compact/task push the expected `ThreadItem`s; `compacting && isComplete` pushes nothing. Use the existing dedup/replay harness (the `ingestedEntryHashes` path) so replay-no-double-count is covered.
- **Jest unit (accumulation):** a pure `mergeResourcesUsed`/accumulate helper test mirroring `Twig/.../accumulateSessionResources.test.ts` — de-dup, first-seen order, empty-products tolerance.
- **Jest component:** `SandboxResourcesBar` renders nothing when empty, one chip per product, Sentence-cased labels; `SandboxContextUsage` renders token/cost and hides when null.
- **Playwright (optional, after A+B):** drive a sandbox data conversation and assert the resources bar appears with ≥1 product and the usage indicator updates — gated behind `PHAI_SANDBOX_MODE`; only worth it once the bar is the default affordance.
- No query-count / backend tests (no backend changes).

## Rollout / flagging

- All work is behind the existing sandbox-runtime selection (`conversation.agent_runtime === 'sandbox'`) and the `PHAI_SANDBOX_MODE` feature flag already guarding the sandbox render path (`Thread.tsx:219`). No new flag needed — these surfaces only mount for sandbox conversations, which are already flag-gated to internal users.
- **Telemetry:** optionally `posthog.capture` a lightweight event when the resources bar first shows products in a session (validates the G1 hypothesis that PHAI conversations are pure data Q&A across a small product set). The `sdk_session` branch (E) can emit an adapter breadcrumb for debugging. Keep both behind the same sandbox guard; nothing fires for LangGraph conversations.
- Each slice (A–E) ships independently; no big-bang. Recommend shipping A alone first, gathering the resources-bar signal, then B.

## Effort & risk

- **Effort:** M total, but front-loaded — A is S (one reducer, one component, one mount point), C/D/E are each S (one dispatch branch + one render branch), and B is the only M sub-task because of the wire-shape reconciliation (D1) and the dual-frame usage model. A practical first PR is A alone (S); B is a second PR; C/D/E can be a third batched PR.
- **Risks:**
  - _Usage wire drift (B)_ — the highest risk. If D1 is mis-modeled, the Claude combined frame is dropped or the percentage ring never populates (the numeric aggregate hides on a `session/update`, not the ext-notification). Mitigate by testing against captured frames from both adapters before shipping B.
  - _Product-id taxonomy skew_ — the ported `PostHogProductId` set must stay in sync with the agent's `POSTHOG_PRODUCTS`. Since the wire already sends `{id, label}`, fall back to the wire `label` for any id missing from the local icon map (render with a generic PostHog/sparkle icon) so an unknown id degrades gracefully rather than disappearing — mirror Twig's `?? SparkleIcon` and `Partial` doc map.
  - _Thread-item ordering_ — low; inline items follow the existing `error`/`turn_separator` precedent and the wire delivers them in order.
  - _Mount-point layout (D3)_ — low; a layout spike resolves it; the fallback (tail of `SandboxThread`) always works.
