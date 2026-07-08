# PostHog AI scene — agent guide

This is the scene for **PostHog AI**, PostHog's agent. It hosts **two coexisting runtimes**, chosen per conversation by `conversation.agent_runtime` (`'langgraph' | 'sandbox'`):

- **`langgraph`** — the **legacy** runtime. Frozen.
- **`sandbox`** — the **new** runtime (Claude Code/Codex agent-server over SSE). New work goes here.

> **Naming:** the user-facing product is **PostHog AI** (was "Max"). Use "PostHog AI" in all user-facing copy. The directory stays `scenes/max/`, and existing internal identifiers (`Max*` components, `MaxUIContext`, `maxThreadLogic`, `maxContextLogic`, the "Max Context" subsystem) keep their names — don't mass-rename. New code shouldn't introduce fresh "Max" branding in copy.

> For the **Max Context** subsystem (how scenes expose dashboards/insights/events to the assistant), see [`README.md`](./README.md). This guide does not repeat it.

## 1. Legacy vs new runtime — read this first

Per-concern mapping, `langgraph` (LEGACY, frozen) → `sandbox` (NEW, build here):

- **Runtime flag**: `agent_runtime === 'langgraph'` → `agent_runtime === 'sandbox'`
- **Stream logic**: `maxThreadLogic.tsx` (LangGraph stream loop) → `runStreamLogic` (SSE; in `products/posthog_ai/frontend/logics/`)
- **Activity renderer**: `components/Activity/LangGraphActivity.tsx` → `RunActivity` (in `products/posthog_ai/frontend/components/`)
- **Thread renderer**: `Thread.tsx` (default path) → `Thread.tsx` binds the surface's `ThreadView`
- **Context shape**: rich `MaxUIContext` (full objects) → flat `AttachedContext` (typed refs, agent fetches)
- **Approvals**: `DangerousOperationApprovalCard.tsx` / `approvalOperationUtils.ts` → the surface's `PermissionInput` / `QuestionInput`
- **Tool widgets**: `messages/` + `messages/adapters/` → the surface's `toolRegistry` (Max's product renderers register via `messages/adapters/registerMaxToolRenderers`)

### Rule: do not extend the LangGraph path unless explicitly asked

New behavior — new tools, new context types, new UI affordances — goes on the **sandbox** path. The LangGraph runtime is slated for removal once sandbox reaches parity; keeping its surface from growing makes the eventual deletion a clean removal rather than an untangling.

- ✅ Bugfixes that keep existing LangGraph conversations working.
- ❌ Net-new capability on the LangGraph path.
- ❌ New fields on `MaxUIContext` for a sandbox feature — use `AttachedContext` instead.
- ❌ No new MaxTools.

If a task genuinely needs the LangGraph path extended, confirm that intent explicitly before touching `maxThreadLogic.tsx`, `LangGraphActivity.tsx`, `max-constants.tsx` (`EnhancedToolCall`), the `MaxUIContext` half of `maxContextLogic.ts`, or `messages/` + `messages/adapters/`.

## 2. Sandbox architecture &amp; conventions live with the surface

The sandbox runtime's heart — `runStreamLogic` (SSE connection, the append-only `log`, the pure
`foldLogToThread` projection, permission routing) — and the conventions for working on it (logic-not-
component, runtime-agnostic plain-props UI, atomic memoized leaves, pure projection) are documented in
**`products/posthog_ai/frontend/AGENTS.md`**, where that code now lives. Read it before touching the surface.

What's Max-specific on the sandbox path and stays here: `Thread.tsx` branches **high** on
`conversation.agent_runtime` and, for the sandbox branch, binds `runStreamLogic` (keyed by the
conversation id) and renders `ThreadView` from the surface — passing resolved props down, never
parsing wire frames in a Max component.

## 4. The sandbox surface lives in `products/posthog_ai/frontend`

The conversation-agnostic sandbox run surface (stream logic, thread/tool/permission/composer components,
policy, wire types) **no longer lives under `scenes/max`** — it's the composable PostHog AI agent-run
library at `products/posthog_ai/frontend`, consumed here through its tiered `api/<module>` facade
(`import { ... } from 'products/posthog_ai/frontend/api/readableRun'` / `api/runSurface` / `api/primitives` /
`api/logics` / `api/types` / `api/tools` — there is no root barrel; pick the narrowest tier). See that
directory's `README.md` for the tier decision table + recipes and its `AGENTS.md` for layout, the public API
(`ReadonlyRunSurface`, the `RunSurface` compound, `Thread`, `Composer`, `runStreamLogic`, the tool registry),
and the hard rule that it must never import `scenes/max`.

What stays in `scenes/max`: conversation orchestration (`maxLogic`, `maxThreadLogic`, `maxGlobalLogic`), the
Max Context subsystem, slash commands, `useMaxTool`/`MaxTool`, feedback/ratings, the frozen LangGraph path,
and Max's **product-specific tool renderers** (`messages/adapters/*`), which register themselves into the
shared `toolRegistry` via `messages/adapters/registerMaxToolRenderers` (imported once from
`Thread.tsx`). Add a new product tool renderer there, not in `products/posthog_ai/frontend`.

## 5. Where do I add X?

The first three now live in `products/posthog_ai/frontend` (the shared surface) — make the change there, not in `scenes/max`:

- **A new thread-item type** → `products/posthog_ai/frontend/types/streamTypes.ts` (the `ThreadItem` union), handle it in `foldLogToThread`, and add a memoized leaf renderer wired into `ThreadView`/`ThreadRow`.
- **A new permission affordance / auto-approval rule** → `products/posthog_ai/frontend/policy/toolPolicy.ts`, then surface it through `PermissionInput`.
- **New stream telemetry** → a guarded `posthog.capture` in the relevant `runStreamLogic` listener (fire-once, suppressed on replay).
- **A new product tool renderer** (renders a PostHog entity) → `scenes/max/messages/adapters/*` + register it in `messages/adapters/registerMaxToolRenderers`.
- **New context the agent should see** → extend `AttachedContext` (not `MaxUIContext`).

## 6. Don'ts

- Don't extend the LangGraph runtime unless explicitly asked.
- Don't parse wire frames or hold SSE state inside a component.
- Don't mutate thread/invocation state from a listener — derive it in the projection.
- Don't add `MaxUIContext` fields for a sandbox feature — use `AttachedContext`.
- Don't subscribe to all sandbox selectors when you need one.
- Don't big-bang-move files on the active branch.
