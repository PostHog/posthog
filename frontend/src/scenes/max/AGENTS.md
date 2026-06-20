# PostHog AI scene — agent guide

This is the scene for **PostHog AI**, PostHog's agent. It hosts **two coexisting runtimes**, chosen per conversation by `conversation.agent_runtime` (`'langgraph' | 'sandbox'`):

- **`langgraph`** — the **legacy** runtime. Frozen.
- **`sandbox`** — the **new** runtime (Claude Code/Codex agent-server over SSE). New work goes here.

> **Naming:** the user-facing product is **PostHog AI** (was "Max"). Use "PostHog AI" in all user-facing copy. The directory stays `scenes/max/`, and existing internal identifiers (`Max*` components, `MaxUIContext`, `maxThreadLogic`, `maxContextLogic`, the "Max Context" subsystem) keep their names — don't mass-rename. New code shouldn't introduce fresh "Max" branding in copy.

> For the **Max Context** subsystem (how scenes expose dashboards/insights/events to the assistant), see [`README.md`](./README.md). This guide does not repeat it.

## 1. Legacy vs new runtime — read this first

Per-concern mapping, `langgraph` (LEGACY, frozen) → `sandbox` (NEW, build here):

- **Runtime flag**: `agent_runtime === 'langgraph'` → `agent_runtime === 'sandbox'`
- **Stream logic**: `maxThreadLogic.tsx` (LangGraph stream loop) → `sandboxStreamLogic.ts` (SSE over products/tasks)
- **Activity renderer**: `components/Activity/LangGraphActivity.tsx` → `components/Activity/SandboxActivity.tsx`
- **Thread renderer**: `Thread.tsx` (default path) → `Thread.tsx` → `SandboxThread()`
- **Context shape**: rich `MaxUIContext` (full objects) → flat `AttachedContext` (typed refs, agent fetches)
- **Approvals**: `DangerousOperationApprovalCard.tsx` / `approvalOperationUtils.ts` → `SandboxPermissionInput` / `SandboxQuestionInput`
- **Tool widgets**: `messages/` + `messages/adapters/` → `mcpToolRegistry` / `mcpToolMessageResolver`

### Rule: do not extend the LangGraph path unless explicitly asked

New behavior — new tools, new context types, new UI affordances — goes on the **sandbox** path. The LangGraph runtime is slated for removal once sandbox reaches parity; keeping its surface from growing makes the eventual deletion a clean removal rather than an untangling.

- ✅ Bugfixes that keep existing LangGraph conversations working.
- ❌ Net-new capability on the LangGraph path.
- ❌ New fields on `MaxUIContext` for a sandbox feature — use `AttachedContext` instead.
- ❌ No new MaxTools.

If a task genuinely needs the LangGraph path extended, confirm that intent explicitly before touching `maxThreadLogic.tsx`, `LangGraphActivity.tsx`, `max-constants.tsx` (`EnhancedToolCall`), the `MaxUIContext` half of `maxContextLogic.ts`, or `messages/` + `messages/adapters/`.

## 2. Sandbox architecture (the new path)

`sandboxStreamLogic.ts` is the heart of the sandbox runtime:

- **SSE connection** — a `fetch` body reader pumped through `eventsource-parser`; a reconnect resumes after the last Redis stream id via `Last-Event-ID` (capped exponential backoff + healthy-connection forgiveness + cumulative cap).
- **Ordered, append-only `log` is the single source of truth** — every wire frame (plus a few client-injected synthetic entries) is appended, never keyed or per-entry deduped.
- **Pure projection** `foldLogToThread(entries) → { threadItems, toolInvocations }`, memoized on `log` identity, derives the rendered thread.
- **Keyed by `streamKey`** (conversation id for Max, task id for a generic task viewer), so concurrent streams stay independent.

**Lifecycle:** `bootstrapRun` (connect SSE → buffer live frames → read the S3 `logs/` snapshot → `dedupeBufferedAgainstHistory` drains the seam) → `ingestAcpFrame` appends + fires fire-once side effects → projection → `Thread.tsx`'s `SandboxThread()` renders `threadItems`, looking up `toolInvocations` by id.

**Permissions:** parse (`parsePermissionRequestFrame`) → route (`sandboxToolPolicy.defaultPermissionDecision` auto-approves built-ins + read-only PostHog `exec`, else surfaces a card) → answer (`respondToPermission`) → resolve (clears the card, pins the id so a reconnect replay can't re-surface it).

**Supporting modules:** `sandboxToolPolicy`, `sandboxPermissionUtils`, `sandboxPermissionDisplayUtils`, `sandboxQuestionUtils`, `mcpToolMessageResolver`; types in `types/sandboxStreamTypes.ts` (folded thread shapes) + `types/sandboxWireTypes.ts` (ACP wire shapes + discriminant guards).

**Wire types are loosely typed** (`notification.params` is `Record<string, unknown>`) — guard at the parse boundary with runtime `typeof`/shape checks; never assume a field is present because the type says so.

## 3. Conventions for new sandbox code

### Streaming/runtime logic stays in the logic, never in a component

Wire parsing, log folding, SSE handling, telemetry, and permission routing belong in `sandboxStreamLogic` (or a sibling logic/util). Components **consume selectors and dispatch actions** — never parse ACP frames, hold SSE/connection state, or fold wire data in a component body.

Selectors to consume: `threadItems`, `toolInvocations`, `isThinking`, `streamPhase`, `pendingPermissionRequest`, `respondingToPermission`, `contextUsage`, `resourcesUsed`.

### Keep UI runtime-agnostic

Render components take **plain props** — `ThreadItem`, `ToolInvocation`, `PermissionRequestRecord` — and know nothing about langgraph vs sandbox; this is what lets the legacy path be deleted later without touching shared UI. If a component must branch on runtime, branch **high** (in `Thread.tsx`, off `agent_runtime`) and pass resolved props down.

### Atomic components

One responsibility per component: extract each thread-item type into a **small leaf presenter**, not a giant inline `switch`/`map`. `SandboxThread()` in `Thread.tsx` (inline dispatch over 15+ item types) and the 1900-line `sandboxStreamLogic.ts` are anti-patterns to shrink, not extend.

### Memoize — `threadItems` re-projects on every appended frame

- Wrap leaf renderers in `React.memo`, keyed by the stable item `id`.
- Derive per-item data with `useMemo`; wrap callbacks passed to children in `useCallback`.
- **Subscribe narrowly** — select only what the component renders; pulling in unrelated selectors means an unrelated fold re-renders it.

### Keep the projection pure

`foldLogToThread` and its helpers must be **pure and deterministic** — item ids stay stable across re-folds. Never mutate thread/invocation state from a listener; derive everything in the projection. Listeners fire only **side effects** (telemetry, API calls), each with its own fire-once guard, suppressed on `source: 'replay'`.

## 4. Target directory organization

The `max/` root is a flat sprawl (~70 files) with sandbox code scattered across the root, `sandbox/`, `components/`, `components/Activity/`, and `types/`. **Do not big-bang-move on the active branch** — it conflicts with in-flight work. Follow this target layout incrementally: new sandbox files land in the right place; an existing file moves only when you're already editing it and the move is low-risk.

Target `sandbox/` subtree:

```text
sandbox/
  sandboxStreamLogic.ts            # stream logic + orchestration (+ .test, + generated *LogicType.ts)
  components/                      # SandboxActivity, SandboxApproval, SandboxPermissionInput,
                                  # SandboxQuestionInput, SandboxResourcesBar, SandboxContextUsage,
                                  # SandboxThreadItems, SandboxQuestionRenderer
  policy/                          # sandboxToolPolicy, sandboxPermissionUtils,
                                  # sandboxPermissionDisplayUtils, sandboxQuestionUtils
  types/                           # sandboxStreamTypes, sandboxWireTypes
```

## 5. Where do I add X?

- **A new thread-item type** → add to the `ThreadItem` union in `types/sandboxStreamTypes.ts`, handle it in `foldLogToThread`, and add a memoized leaf renderer wired into `SandboxThread()`.
- **A new permission affordance / auto-approval rule** → `sandboxToolPolicy.ts`, then surface it through `SandboxPermissionInput`.
- **New telemetry** → a guarded `posthog.capture` in the relevant `sandboxStreamLogic` listener (fire-once, suppressed on replay).
- **New context the agent should see** → extend `AttachedContext` (not `MaxUIContext`).

## 6. Don'ts

- Don't extend the LangGraph runtime unless explicitly asked.
- Don't parse wire frames or hold SSE state inside a component.
- Don't mutate thread/invocation state from a listener — derive it in the projection.
- Don't add `MaxUIContext` fields for a sandbox feature — use `AttachedContext`.
- Don't subscribe to all sandbox selectors when you need one.
- Don't big-bang-move files on the active branch.
