# Cancel button keeps showing the "Let's bail" stop affordance after cancellation

> **Source:** outstanding_items.md § 2 (Item 2) · **Locus:** frontend — Max composer
> **Effort:** S (LangGraph fix) → S–M once the sandbox bug below is folded in · **Priority:** High · **Blocks rollout:** No (visible bug)
> **Joins:** Standalone item, but the investigation uncovered a **second, always-on sandbox bug in the same code path** (`streamingActive` never tears down on the sandbox runtime). Both bugs surface through the exact same selector chain (`streamingActive → threadLoading → showStopButton`) in the same two files, so they must be fixed together — fixing only the LangGraph race would leave the sandbox composer button stuck in the "Let's bail" state permanently. Cross-references G7 (sandbox stream lifecycle) for the terminal-event wiring this plan touches.

## Problem

After a user cancels an in-flight turn, the Max composer's primary button keeps rendering the **stop** state — the red `IconStopFilled` icon with the "Let's bail" tooltip — instead of returning to the **send** state ("Let's go!" with the arrow icon). The button text/icon/click-behaviour are all derived from `showStopButton`, which is derived from `threadLoading`, which is the union of two loading flags (`conversationLoading || streamingActive`). At cancel time, those flags are not all cleared, so the union stays `true` and the button stays stuck on "stop".

There are actually **two distinct defects** in the same selector chain:

1. **LangGraph cancel race (the reported symptom).** In `stopGeneration` the loading flags are cleared by a fire-and-forget conversation refetch that races with a synchronous `setCancelLoading(false)`. The refetch is supposed to bring back a non-`InProgress` status that clears `conversationLoading`, but it is not awaited and its success handler is gated behind a `streamingActive` guard, so the button can be left showing "Let's bail" until something else nudges the state.

2. **Sandbox runtime: `streamingActive` never tears down (always-on bug).** On the sandbox runtime, `streamingActive` is flipped **on** when the turn starts (`streamConversation` reducer) but is **only ever** flipped **off** by `completeThreadGeneration` — and `completeThreadGeneration` is **never dispatched on the sandbox path**. The sandbox terminal events (`markTurnComplete` / `handleTerminalStatus` / `handleStreamError`) only release the streaming lock; they do not flip `streamingActive`. So on the sandbox runtime the composer button gets stuck on "Let's bail" after **every** turn — cancel or not — not just after a cancel.

This plan fixes both.

## Current behavior (verified)

All line numbers below were confirmed by reading the files on 2026-06-13. The source-doc citations had drifted; corrected locations are recorded here and in `citationCorrections`.

### Button-state derivation — `frontend/src/scenes/max/components/QuestionInput.tsx`

- `frontend/src/scenes/max/components/QuestionInput.tsx:191-192` — the two locals that drive everything:

  ```ts
  const isQueueingSubmission = queueingEnabled && threadLoading && hasQuestion
  const showStopButton = threadLoading && !isQueueingSubmission
  ```

  (Doc cited `:463-479`; the **derivation** lives at `:191-192`. `:463-479` is where the tooltip uses it.)

- `frontend/src/scenes/max/components/QuestionInput.tsx:150-166` — `threadLoading`, `cancelLoading`, `streamingActive` are all pulled from `maxThreadLogic` via `useValues`.
- `frontend/src/scenes/max/components/QuestionInput.tsx:209-215` — `disabledReason` precedence. When `cancelLoading` is `true`, `disabledReason = 'Cancelling...'`.
- `frontend/src/scenes/max/components/QuestionInput.tsx:463-479` — the tooltip: `disabledReason ? disabledReason : showStopButton ? "Let's bail" : isQueueingSubmission ? "Queue message" : "Let's go!"`. **Important consequence:** while `cancelLoading` is `true` the tooltip correctly reads "Cancelling…"; the stale "Let's bail" only appears in the window **after** `cancelLoading` flips back to `false` while `threadLoading` is still `true`. That precisely matches the report and rules out the tooltip itself.
- `frontend/src/scenes/max/components/QuestionInput.tsx:442-491` — icon (`IconStopFilled` vs `IconArrowRight`), `data-attr` (`max-stop-generation` vs `max-send-message`), `type`, and the `onClick` branch (`if (threadLoading) { … stopGeneration() }`) are all gated on `showStopButton` / `threadLoading`.

### State derivation — `frontend/src/scenes/max/maxThreadLogic.tsx`

- `frontend/src/scenes/max/maxThreadLogic.tsx:1596-1599` — `threadLoading` selector: `(conversationLoading, streamingActive) => conversationLoading || streamingActive`. (Doc implied this lived near `:53`; it is at `:1596`.)
- `frontend/src/scenes/max/maxThreadLogic.tsx:341-347` — `conversationLoading` reducer. Initial value `props.conversation?.status === ConversationStatus.InProgress`; only setter is `setConversation` → `conversation.status === ConversationStatus.InProgress`. So it clears only when a `setConversation` arrives carrying a non-`InProgress` status.
- `frontend/src/scenes/max/maxThreadLogic.tsx:349-356` — `streamingActive` reducer: `reconnectToStream → true`, `streamConversation → true`, `completeThreadGeneration → false`. **These are the only three responders** (verified). Nothing else flips it.
- `frontend/src/scenes/max/maxThreadLogic.tsx:465-471` — `cancelLoading` reducer: `stopGeneration → true`, `setCancelLoading → payload`.

### `stopGeneration` listener — `frontend/src/scenes/max/maxThreadLogic.tsx:1295-1313`

(Doc cited `:1295-1313`; still accurate.)

```ts
stopGeneration: async () => {
  if (!values.conversation?.id) {
    actions.setCancelLoading(false)
    return
  }
  try {
    await api.conversations.cancel(values.conversation.id) // :1302
    cache.generationController?.abort() // :1303 — aborts LangGraph SSE loop
    actions.clearQueuedMessages()
    actions.resetThread() // :1305 — does NOT touch streamingActive
  } catch (e: any) {
    posthog.captureException(e)
    lemonToast.error(e?.data?.detail || 'Failed to cancel the generation.')
  }
  actions.loadConversation(values.conversation.id) // :1311 — fire-and-forget refetch
  actions.setCancelLoading(false) // :1312 — fires synchronously, races :1311
}
```

- `api.conversations.cancel` is `frontend/src/lib/api.ts:6672-6674` → `PATCH /conversations/{id}/cancel/`.
- `actions.loadConversation` is **connected from `maxGlobalLogic`** (`maxThreadLogic.tsx:189-190`), not local. Its loader is `maxGlobalLogic.tsx:127-139` — a plain `api.conversations.get(id)` that merges the result into `conversationHistory`. It shares the `conversationHistory` loader, so on success it triggers `loadConversationHistorySuccess`, handled at `maxThreadLogic.tsx:1393-1414`.
- `loadConversationHistorySuccess` (`maxThreadLogic.tsx:1393-1414`) **returns early if `values.streamingActive` is `true`** (`:1397`) and otherwise calls `setConversation(conversation)` (`:1410`), which is what would clear `conversationLoading`.

### How the LangGraph race produces the stale button

On the LangGraph path `streamConversation` runs the SSE loop inline and, on `AbortError` (triggered by `cache.generationController?.abort()` at `:1303`), the listener falls through to its tail and calls `completeThreadGeneration()` (`maxThreadLogic.tsx:927`), flipping `streamingActive → false`. So `streamingActive` does eventually clear on LangGraph. The residual problem is `conversationLoading`: it only clears when a `setConversation` with a non-`InProgress` status arrives. That comes from the fire-and-forget `loadConversation` refetch (`:1311`), but:

- it is not awaited, and
- its success handler (`loadConversationHistorySuccess`) bails out early while `streamingActive` is still `true` (`:1397`) — a timing window — so the freshly-fetched (canceled/idle) status may be dropped, leaving `conversationLoading` stuck `true`.

Net: `threadLoading = conversationLoading || streamingActive` can stay `true` after cancel ⇒ `showStopButton` stays `true` ⇒ "Let's bail" persists.

### How the sandbox path is worse (always-on, not just on cancel)

- `streamConversation` for sandbox conversations (`maxThreadLogic.tsx:658-717`) routes the turn to a products/tasks Run and hands the SSE off to `sandboxStreamLogic` via `openSandboxSse`. The LangGraph EventSource loop and its tail `completeThreadGeneration()` are **never reached** (it `return`s at `:707`).
- The streaming lock is released by `cache.sandboxStreamRelease` (`maxThreadLogic.tsx:702-706`), which calls only `decrActiveStreamingThreads()` + `releaseStreamingLock()` — **not** `completeThreadGeneration()`.
- The sandbox terminal listeners (`maxThreadLogic.tsx:937-944`) map `sandboxStreamLogic`'s `markTurnComplete` / `handleTerminalStatus` / `handleStreamError` to `cache.sandboxStreamRelease?.()` — again **not** `completeThreadGeneration()`.
- Therefore `streamingActive` (flipped `true` by the `streamConversation` reducer at `:353`) is **never flipped back to `false`** on the sandbox runtime. `threadLoading` stays `true` permanently after the first sandbox turn, so `showStopButton` is permanently `true` regardless of cancel.

### Both cancel paths share ONE frontend entry point — resolving the doc's open question

The doc asks "is the report from the LangGraph path, the sandbox path, or both?" Answer, verified from code:

- There is **no separate frontend sandbox cancel path.** Grepping the entire `frontend/src/scenes/max/` tree for a `method: "cancel"` command relay returns nothing. The `method:"cancel"` relay the doc references is **backend-only**.
- Both runtimes cancel through the **same** `stopGeneration` listener → the **same** `api.conversations.cancel(id)` call → the **same** `PATCH /conversations/{id}/cancel/` endpoint.
- The endpoint branches by runtime server-side (`ee/api/conversation.py:752-796`): sandbox conversations go through `MessageRoutingService(conversation, user).cancel()` (`:756-778`), which issues the `method:"cancel"` command relay in-process; LangGraph conversations go through `AgentExecutor.cancel_workflow()` (`:786-791`). The relay allowlist that permits `cancel` is `TaskRunCommandRequestSerializer.ALLOWED_METHODS` at `products/tasks/backend/serializers.py:1400-1406`.

So the **fix lives entirely in the frontend** (`maxThreadLogic.tsx` + a defensive selector change in `QuestionInput.tsx`). No `sandboxStreamLogic.ts` change is strictly required for the cancel symptom, but `sandboxStreamLogic.ts`'s terminal events are what `maxThreadLogic`'s sandbox listeners (`:937-944`) react to — and **that listener block is where the sandbox `streamingActive` teardown must be added.** The symptom exists on **both** paths: a race on LangGraph, and an always-on stuck flag on sandbox.

## Approach

Three small, independent changes, in priority order. (1) is the minimum to fix the reported LangGraph symptom; (2) fixes the always-on sandbox variant uncovered here; (3) is a cheap defense-in-depth selector tweak that makes the button correct even if a future loading-flag leak recurs.

1. **Clear the loading flags deterministically in `stopGeneration`, not via a raced fire-and-forget refetch.** Drive `conversationLoading` to `false` immediately by `setConversation` with a definite post-cancel status (`Idle`) instead of relying on the un-awaited `loadConversation(...)` round-trip to deliver it. Keep `loadConversation(...)` as the eventual source-of-truth reconcile, but do not depend on it for the button transition. Concretely: in the `try` block after a successful `cancel`, optimistically set the conversation to `Idle` (mirroring `completeThreadGeneration`'s `:1359-1365` pattern) and only then fire-and-forget the refetch. This removes the race entirely and is runtime-agnostic.

2. **Tear down `streamingActive` on the sandbox terminal events.** In the sandbox terminal listener block (`maxThreadLogic.tsx:937-944`), have each of the three terminal events also end streaming. This is the real fix for the always-on sandbox stuck-button bug and must land regardless of the cancel work. Reusing `completeThreadGeneration` is attractive for normal completion (`markTurnComplete`) because it is the canonical "turn ended" action (it finalizes message statuses, refreshes history, sets the conversation to `Idle`, and — for sandbox — drains the next queued message). **Caveat:** `completeThreadGeneration` also runs a sandbox-queue-drain that dispatches `askMax` to start a new turn (`:1371-1385`); that is wrong on the **error/terminal** paths (`handleStreamError` / `handleTerminalStatus`). Prefer a narrow `endStreaming` action (flips only `streamingActive`) for those two, and reserve `completeThreadGeneration` for `markTurnComplete` — or gate the queue-drain. See implementation step 1 for the decision.
   - Rejected alternative: have `sandboxStreamLogic` itself dispatch into `maxThreadLogic`. Rejected because the existing architecture deliberately keeps the dependency one-directional — `maxThreadLogic` subscribes to `sandboxStreamLogic`'s action types (`:937-944`); reversing that would create a cycle.

3. **Make `showStopButton` robust to a `cancelLoading` overlap (defense-in-depth, recommended).** While `cancelLoading` is `true` the user has already asked to stop; the button should never offer "stop" again. Change the derivation in `QuestionInput.tsx:192` to `const showStopButton = threadLoading && !isQueueingSubmission && !cancelLoading`. This guarantees that during the cancel-in-flight window the button shows "Cancelling…" (already wired via `disabledReason` at `:213-214`) and can never flash "Let's bail". This does not by itself fix the post-cancel window (where `cancelLoading` is already `false`) — (1) and (2) do — but it removes a whole class of "stop shown while we're already canceling" glitches cheaply and with no logic-layer risk.

**Rejected overall alternative — replace the loading-flag union with a single `conversationStatus`-derived enum.** The doc floats deriving button state from a definite status (`idle`/`canceling`) rather than the `conversationLoading || streamingActive` union. This is the "right" long-term shape, but it is a larger refactor that touches every consumer of `threadLoading` (20+ references in `maxThreadLogic.tsx` alone, plus `QuestionInput`, `Thread`, etc.) and risks regressing the queueing / reconnect / consent flows. For an S-effort visible-bug fix, the targeted changes (1)+(2)+(3) are safer and sufficient. Note the enum refactor as a follow-up.

## Implementation steps

1. **Fix the sandbox `streamingActive` teardown (bug 2).** In `maxThreadLogic.tsx:937-944`, make each terminal listener also end streaming:

   ```ts
   listeners(({ props, cache, actions, values }) => {
     const sandboxStreamActionTypes = sandboxStreamLogic({ conversationId: props.conversationId }).actionTypes
     // Normal completion: full turn-end (incl. sandbox-queue drain -> askMax).
     const completeSandboxTurn = (): void => {
       cache.sandboxStreamRelease?.()
       if (values.streamingActive) {
         actions.completeThreadGeneration()
       }
     }
     // Error / terminal: just stop streaming. MUST NOT run completeThreadGeneration's
     // queue-drain (:1371-1385) — auto-starting the next queued message after a failure is wrong.
     const endSandboxStream = (): void => {
       cache.sandboxStreamRelease?.()
       if (values.streamingActive) {
         actions.endStreaming() // new action: streamingActive -> false only
       }
     }
     return {
       [sandboxStreamActionTypes.markTurnComplete]: completeSandboxTurn,
       [sandboxStreamActionTypes.handleTerminalStatus]: endSandboxStream,
       [sandboxStreamActionTypes.handleStreamError]: endSandboxStream,
     }
   })
   ```

   - Guard on `values.streamingActive` so neither teardown action fires for history-replay terminal events (`handleTerminalStatus` is also dispatched during `bootstrapRun` replay with `replayedFromHistory: true` — `sandboxStreamLogic.ts:624` — when no live turn is in flight). The new `endStreaming` action needs a one-line reducer entry in the `streamingActive` block (`maxThreadLogic.tsx:349-356`): `endStreaming: () => false`.
   - Verify `completeThreadGeneration`'s side effects (`maxThreadLogic.tsx:1346-1391`) are safe to run on the sandbox path: it calls `loadConversationHistory`, sets the conversation to `Idle`, and `loadConversation` (mostly idempotent). **But it also contains a sandbox-queue-drain block (`:1371-1385`): when `isSandboxMode && queuedMessages.length > 0` it `consumeQueuedMessage` + `askMax(nextMessage.content)` — i.e. it starts a brand-new turn.** Today `completeThreadGeneration` is never dispatched on the sandbox path (only the LangGraph tail at `:927` dispatches it), so this block currently never runs; wiring it into the terminal listeners newly activates it. On normal turn-completion (`markTurnComplete`) auto-draining the next queued message is the intended behavior. On the **error/terminal** paths (`handleStreamError`, `handleTerminalStatus`) it is **not** — auto-starting the next queued message after a failure is wrong. **This pushes toward the narrow `endStreaming` action** (whose only reducer is `streamingActive → false`) for the error/terminal listeners, reserving full `completeThreadGeneration` for `markTurnComplete` only — or gating the queue-drain on a success flag. Decide this during implementation; do not blanket-reuse `completeThreadGeneration` for all three terminal events without confirming the queue-drain behavior on each.

2. **Fix the LangGraph cancel race (bug 1).** In the `stopGeneration` listener (`maxThreadLogic.tsx:1295-1313`), inside the `try` after a successful `cancel`, optimistically flip the conversation to `Idle` before the refetch:

   ```ts
   await api.conversations.cancel(values.conversation.id)
   cache.generationController?.abort()
   actions.clearQueuedMessages()
   actions.resetThread()
   if (values.conversation) {
     const canceledConversation = { ...values.conversation, status: ConversationStatus.Idle }
     actions.setConversation(canceledConversation)
     actions.updateGlobalConversationCache(canceledConversation)
   }
   ```

   This clears `conversationLoading` synchronously (the `setConversation` reducer at `:344-345` sees a non-`InProgress` status). Keep the existing `actions.loadConversation(...)` (`:1311`) as the eventual reconcile and keep `setCancelLoading(false)` (`:1312`) — order no longer matters because the button no longer depends on the refetch landing.
   - `ConversationStatus` is already imported (`maxThreadLogic.tsx:61`); `updateGlobalConversationCache` is already an action (used at `:1277`, `:1365`).

3. **Defense-in-depth selector tweak (bug class).** In `QuestionInput.tsx:192`, add the `cancelLoading` guard:

   ```ts
   const showStopButton = threadLoading && !isQueueingSubmission && !cancelLoading
   ```

   `cancelLoading` is already destructured at `:156`. No other change needed — the "Cancelling…" `disabledReason` is already wired at `:213-214`, and the `onClick` already no-ops correctly because `disabledReason` short-circuits.

4. **Type-check and lint.** `pnpm --filter=@posthog/frontend typescript:check` and `pnpm --filter=@posthog/frontend format`. Note `maxThreadLogicType.ts` is generated by kea-typegen — adding the `endStreaming` action (now part of step 1, used for the error/terminal listeners) regenerates it automatically. If you end up reusing `completeThreadGeneration` for all three events (not recommended — see step 1's queue-drain caveat) no type change is needed.

5. **Tests** — see Testing section.

## Files to change

| Path                                                        | Change                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| ----------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `frontend/src/scenes/max/maxThreadLogic.tsx`                | (a) `:937-944` sandbox terminal listeners → tear down `streamingActive` (guarded on `streamingActive`): `markTurnComplete` → `completeThreadGeneration()`; `handleStreamError`/`handleTerminalStatus` → narrow `endStreaming` (new action, flips only `streamingActive`) to avoid the sandbox-queue-drain-on-error in `completeThreadGeneration` (`:1371-1385`). (b) `stopGeneration` listener `:1295-1313` → optimistically `setConversation({...Idle})` + `updateGlobalConversationCache` after a successful cancel, before the fire-and-forget refetch. |
| `frontend/src/scenes/max/components/QuestionInput.tsx`      | `:192` → add `&& !cancelLoading` to `showStopButton`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `frontend/src/scenes/max/maxThreadLogic.test.ts`            | Add `stopGeneration` button-state assertions (LangGraph) and a sandbox terminal-event teardown assertion.                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `frontend/src/scenes/max/components/QuestionInput.test.tsx` | Add a render-level assertion that the button shows send (not stop) after `cancelLoading` true→false with `threadLoading` resolved.                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `frontend/src/scenes/max/sandboxStreamLogic.ts`             | **No change required.** Listed only to record that it was traced and the cancel/teardown wiring is consumed from `maxThreadLogic`, not authored here.                                                                                                                                                                                                                                                                                                                                                                                                      |

## Decisions & open questions

- **Q: Which path does the report come from? (the doc's open question)** — **Resolved by code.** Both runtimes share one frontend cancel entry point (`stopGeneration` → `api.conversations.cancel`); there is no separate sandbox cancel path in the frontend (the `method:"cancel"` relay is backend-only, `ee/api/conversation.py:756-778`). The reported stale-button symptom is reproducible on **both** runtimes, by **different** mechanisms: a post-cancel `conversationLoading` race on LangGraph, and an always-stuck `streamingActive` on sandbox. **Recommendation: fix both.**
- **Decision: reuse `completeThreadGeneration` vs. add a narrow `endStreaming` action for the sandbox teardown.** Recommendation: **mixed** — reuse `completeThreadGeneration` for `markTurnComplete` (normal completion, where its sandbox-queue-drain dispatching `askMax` at `:1371-1385` is the intended next-turn behavior), but use a narrow `endStreaming` action (flips only `streamingActive`) for the **error/terminal** events (`handleStreamError` / `handleTerminalStatus`), where auto-starting the next queued message after a failure would be wrong. Blanket-reusing `completeThreadGeneration` for all three would introduce a queue-drain-on-error bug, so `endStreaming` is part of the plan, not just a fallback.
- **Decision: optimistic `Idle` set in `stopGeneration` vs. awaiting the refetch.** Recommendation: **optimistic set.** Awaiting the `loadConversation` round-trip would block the button transition behind a network call and still race with the streaming teardown. The optimistic set is instant, runtime-agnostic, and the existing fire-and-forget refetch still reconciles the true server status moments later.
- **Decision: keep or drop the `loadConversationHistorySuccess` `streamingActive` guard (`:1397`).** Recommendation: **keep it** — it exists to avoid clobbering the live thread mid-stream. With the optimistic `Idle` set in step 2, the button no longer depends on this handler firing, so the guard is harmless to the fix.
- **Open: should the larger `threadLoading` → `conversationStatus`-enum refactor be scheduled?** Recommendation: **defer** to a separate `chore` once the sandbox runtime is the default; track it but don't block this bug fix on it.

## Dependencies & sequencing

- **Within this pass:** Step 1 (sandbox teardown) and step 2 (LangGraph race) are independent and can land in either order; step 3 (selector guard) is independent of both. No migrations, no backend changes. Step 1 adds a new `endStreaming` kea action, so `maxThreadLogicType.ts` regenerates via kea-typegen (automatic on typecheck/format). Self-contained frontend change.
- **Cross-references (do not duplicate their scope):**
  - **G7 (`G7-sandbox-streaming-resilience.md`)** owns the sandbox SSE terminal/error/reconnect model in `sandboxStreamLogic.ts`. This plan only **consumes** G7's terminal action types (`markTurnComplete` / `handleTerminalStatus` / `handleStreamError`) in `maxThreadLogic`'s listener block; it does not change how those events are produced. If G7 renames or restructures those actions, the listener block here must be updated in lockstep — coordinate.
  - No overlap with G1, G3, G4, G5, G6, G8, G9 (different loci).

## Testing

- **Jest — `maxThreadLogic.test.ts` (primary).** Mount the logic, mock `api.conversations.cancel` to resolve.
  - **LangGraph cancel:** seed `conversation.status = InProgress` (so `conversationLoading = true`), simulate an active stream, dispatch `stopGeneration`, await, then assert `conversationLoading === false`, `streamingActive === false`, `threadLoading === false`, `cancelLoading === false`. This is the regression test for bug 1; before the fix `threadLoading` stays `true`.
  - **Sandbox teardown:** with an existing sandbox conversation, dispatch `streamConversation` (asserts `streamingActive === true`), then dispatch the `sandboxStreamLogic` `markTurnComplete` (and separately `handleTerminalStatus`, `handleStreamError`) action and assert `streamingActive` flips to `false` and `threadLoading === false`. This is the regression test for bug 2; before the fix `streamingActive` stays `true` forever.
  - **Error path must not drain the queue:** with a sandbox conversation, a `streamingActive` turn, and one queued message, dispatch `handleStreamError` and assert `streamingActive === false` **and** that the queued message was **not** consumed and **no** `askMax` was dispatched (i.e. `endStreaming`, not `completeThreadGeneration`, ran). Conversely, `markTurnComplete` with a queued message **should** drain it (`consumeQueuedMessage` + `askMax`).
  - **History-replay guard:** dispatch `handleTerminalStatus` with `replayedFromHistory: true` while `streamingActive === false` and assert no teardown action's side effects fire (no spurious `Idle` set / history reload / `askMax`).
  - Reuse the existing `cancelCount` describe block (`maxThreadLogic.test.ts:2723-2768`) patterns and the streaming-state setup already present in the file.
- **Jest — `QuestionInput.test.tsx`.** Render with `maxThreadLogic` values forced (`threadLoading` then resolved; toggle `cancelLoading`), assert the button `data-attr` is `max-send-message` (not `max-stop-generation`) and the tooltip is not "Let's bail" after cancel resolves. Add a case: `cancelLoading === true` ⇒ button shows `Cancelling…` and `data-attr === max-send-message`.
- **Manual / Playwright (optional, recommended for the sandbox always-on bug since it's so visible):** on a sandbox conversation, send a message, let it complete normally (do not cancel), confirm the composer button returns to the send arrow. Then repeat with a mid-turn cancel. Run on both a LangGraph and a sandbox conversation. A dedicated Playwright test is likely overkill for an S fix; the jest logic tests cover the state machine, which is where both bugs live.
- Run via `hogli test frontend/src/scenes/max/maxThreadLogic.test.ts` and `hogli test frontend/src/scenes/max/components/QuestionInput.test.tsx`.

## Rollout / flagging

n/a — this is a pure bug fix in the composer's local state derivation. No new flag: the sandbox runtime is already feature-flagged at a higher level, and shipping the teardown fix only improves behaviour for users already on it. No telemetry change required; the existing `max conversation turn completed { status: 'cancelled' }` capture (`maxThreadLogic.tsx:792-799`, LangGraph) and `task_run_cancelled` capture (`ee/api/conversation.py:765-776`, sandbox) already record cancellations. Optionally add a one-line capture if we want to confirm the fix in production telemetry, but not necessary.

## Effort & risk

- **Effort: S** for the LangGraph race + selector guard alone; **S–M** with the sandbox `streamingActive` teardown folded in (the sandbox change requires the `replayedFromHistory` guard and a teardown assertion test, but is still a few lines).
- **Risks:**
  - **`completeThreadGeneration` side effects on the sandbox path** (medium). It triggers `loadConversationHistory` + `loadConversation` + sets `Idle` (mostly idempotent — worst case an extra history fetch), **but it also drains the sandbox queue and dispatches `askMax` for the next message (`:1371-1385`).** That is correct on normal completion (`markTurnComplete`) but wrong on the error/terminal paths (`handleStreamError` / `handleTerminalStatus`), where it would auto-start a new turn after a failure. Mitigation: use the narrow `endStreaming` action (flips only `streamingActive`) for the error/terminal listeners and reserve `completeThreadGeneration` for `markTurnComplete`. This makes `endStreaming` part of the planned change, not just a fallback — regenerate `maxThreadLogicType.ts` via kea-typegen (step 4).
  - **Double-fire of teardown** (low). The sandbox terminal events can fire in close succession (e.g. `handleStreamError` then a terminal status). `cache.sandboxStreamRelease` already nulls itself after the first call (`maxThreadLogic.tsx:702-703`), and `completeThreadGeneration` is idempotent against an already-`false` `streamingActive`. The `if (values.streamingActive)` guard makes the second dispatch a no-op.
  - **Coordination with G7** (low-medium). If G7 restructures the sandbox terminal action surface, this listener block must follow. Flagged in Dependencies.
