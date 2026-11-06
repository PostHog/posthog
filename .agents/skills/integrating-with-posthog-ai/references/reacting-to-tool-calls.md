# Reacting to tool calls

`toolStreamEventsLogic` (`api/logics`) is a global bus. `runStreamLogic` is its only publisher, emitting a tool-call lifecycle event with a **resolved** tool name — the inner PostHog tool, not the exec wrapper — plus turn-complete and run-terminal events.

This is what makes the side panel feel connected to the page: the user asks PostHog AI to change something, and their open page updates instead of going stale.

## The event

```ts
type ToolStreamPhase = 'started' | 'updated' | 'completed' | 'failed'

interface ToolStreamEvent {
  streamKey: string // conversation id, or run/task id
  toolCallId: string
  toolName: string // resolved inner tool
  rawToolName: string
  phase: ToolStreamPhase
  invocation: ToolInvocation
  source: 'live' | 'replay' | 'client'
}
```

## `useToolStreamListener` — plain reaction

Reload a list, refetch a record, flash a notice:

```ts
useToolStreamListener({
  tools: ['cdp-functions-partial-update'],
  onEvent: (event) => {
    if (event.phase !== 'completed' || !hogFunction?.id) {
      return
    }
    const innerInput = resolveToolCall(event.invocation).innerInput
    const targetId = typeof innerInput?.id === 'string' ? innerInput.id : null
    if (targetId && targetId !== hogFunction.id) {
      return
    }
    loadHogFunction()
  },
})
```

Note the targeting: the bus is global, so an event for _some other_ record still reaches you. Parse the inner args with `resolveToolCall` and check the call was actually about the thing you are showing. Real caller: `frontend/src/scenes/hog-functions/configuration/HogFunctionConfiguration.tsx`.

Pass `tools: '*'` to see everything, but then filter hard.

## `useMcpToolApplyBack` — apply an edit into an open editor

When the user is editing something and the agent changes it, this applies the result back into the open form:

```tsx
useMcpToolApplyBack({
  tools: ['insight-create', 'insight-update'],
  targetKey: `dashboard:${dashboard?.id ?? 'unloaded'}`,
  active: !!dashboard && canEditDashboard,
  onApply: (_event, { innerInput }) => {
    if (dashboard && insightIsAddedToDashboard(innerInput, dashboard.id)) {
      loadDashboard({ action: DashboardLoadAction.Update })
    }
  },
})
```

It is a hardened wrapper over the bus, not a convenience alias:

- **Foreground-gated.** Only the run rendered in the panel the user is watching can trigger it. A background task cannot rewrite the page under them.
- **Replay-excluded**, always.
- **Snapshotted at send time.** The active registration is captured when the prompt is sent, so navigating to a different editor mid-run cannot hand the response to the new one.
- **Fails closed on ambiguity.** If more than one claimed target matches the same tool, nothing is applied.

`targetKey` is what makes those guarantees work: it must be a **stable identity for the resource being edited**, and it must change when the resource changes. Include the id, and include a sentinel for the unloaded state (the example uses `'unloaded'`) so a not-yet-loaded editor never shares a key with a loaded one.

`applyOn` picks the timing:

- `'tool_call_completed'` (default) — fire per matching completion.
- `'turn_end'` — buffer, and apply only the last matching completion, once, when the turn finishes. Use this when the agent may call the tool several times converging on an answer and you only want the final state.

Other real callers: `frontend/src/scenes/dashboard/DashboardHeader.tsx`, `frontend/src/scenes/data-warehouse/editor/QueryWindow.tsx`, `frontend/src/scenes/web-analytics/WebAnalyticsFilters.tsx`, `frontend/src/scenes/session-recordings/filters/RecordingsUniversalFiltersEmbed.tsx`.

Pair an apply-back with a trusted instruction telling the agent that its tool calls are reflected on the open page — otherwise it does not know the user can see the result, and may narrate the change instead of making it.

## Two caveats that bite

**Replay is suppressed by default.** A reload replays the run's history through the same code path. Without suppression every handler would re-fire on every reload — creating things twice, re-applying stale edits. Set `includeReplay: true` only if you have thought about that.

**`toolName` is unreliable at `phase: 'started'`.** For exec-wrapped PostHog tools the command streams in through later updates, so the resolved name can still be `__posthog_exec_unknown__` when the call starts. It is reliable by `'completed'`. Match on `'completed'` whenever correctness depends on knowing which tool ran.

## From a kea logic

Either listen to the bus action and filter yourself:

```ts
listeners({
  [toolStreamEventsLogic.actionTypes.emitToolEvent]: ({ event }) => {
    if (event.source === 'replay' || event.phase !== 'completed') {
      return
    }
    // …
  },
})
```

Or register a subscription through a disposable, calling `registerToolListener(listenerId, { tools, onEvent })` in setup and `deregisterToolListener(listenerId)` in cleanup — with `pauseOnPageHidden: false`, because tool events fire while the tab is hidden and a missed live event is never redelivered.

Subscriber callbacks are isolated: a throwing listener is captured and reported, never breaking stream ingestion. That is a safety net, not a license — a throwing handler still means your reaction did not happen.
