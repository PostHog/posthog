# PostHog AI → Sandbox Agent Migration — Overview

Migration of PostHog AI ("Max") from the LangGraph-backed `ee/hogai/chat_agent/` runtime onto the cloud-agent / sandbox architecture documented in [`CLOUD_AGENTS_FRONTEND_SPEC.md`](../CLOUD_AGENTS_FRONTEND_SPEC.md).

**The frontend stays in `frontend/src/scenes/max/`.** The public `/api/.../conversations/*` contract stays (plus one additive sandbox-only POST endpoint). The migration is split: Django gains a thin non-streaming message-routing endpoint `POST /conversations/{id}/sandbox/` (`ee/hogai/sandbox/message_view.py`) that wraps + dedupes + creates a cloud-agent Task/Run, and returns the IDs the frontend needs. The frontend then opens SSE **directly** against the cloud-agent endpoint `/api/projects/{tid}/tasks/{taskId}/runs/{runId}/stream/` — the same endpoint PostHog Code consumes (`Twig/apps/code/src/main/services/cloud-task/service.ts`). A new frontend module (`sandboxStreamLogic.ts`) owns the SSE connection, parses the wire format (default `event: message` + `data.type` discrimination, per PostHog Code), and produces thread-shaped state without touching today's LangGraph event handlers.

This shifts the migration from "rewrite the chat UI" to "build the relay + a frontend stream processor + a small handful of additive `maxThreadLogic` cases".

| # | Topic | Spec |
|---|---|---|
| 1 | Context (passing context to the agent) | [`01_CONTEXT.md`](./01_CONTEXT.md) |
| 2 | Core functionality (message routing endpoint + frontend stream processor) | [`02_CORE.md`](./02_CORE.md) |
| 3 | Rich UI (MCP tool dispatch → existing renderers) | [`03_RICH_UI.md`](./03_RICH_UI.md) |
| 4 | Prompts (`ee/hogai/chat_agent/prompts/` → sandbox `systemPrompt`) | [`04_PROMPTS.md`](./04_PROMPTS.md) |
| 5 | Sandbox sizing + Task model adjustments (constrained profile for PostHog AI) | [`05_SANDBOX.md`](./05_SANDBOX.md) |
| — | **Backward-compatibility audit** (read before any spec) | [`BACKWARD_COMPAT.md`](./BACKWARD_COMPAT.md) |
| — | Open backfill items | [`TODO.md`](./TODO.md) |

> **⚠ Coexistence mode.** The migration runs behind a per-user feature flag (`posthog-ai-sandbox`). Users without the flag must see today's Max exactly as today. Sub-specs `01_CONTEXT.md`, `03_RICH_UI.md`, and `04_PROMPTS.md` describe the *end-state* code shape; [`BACKWARD_COMPAT.md`](./BACKWARD_COMPAT.md) overrides them for the rollout window — sandbox logic lives **alongside** the existing code, not in place of it. `maxContextLogic.ts`, `maxBillingContextLogic.tsx`, `MaxTool.tsx`, `useMaxTool.ts`, all 38 `useMaxTool` call sites, and every existing `messages/*.tsx` renderer stay untouched during the migration. Cleanup is a follow-up phase after default-on.

---

## 1. Why migrate

Today the agent runtime is a LangGraph DAG in `ee/hogai/`; tools are Python classes registered in `chat_agent/toolkit.py`; streaming uses a custom SSE protocol assembled by graph nodes; conversation state lives in a `Conversation` model.

We want the runtime to be `@posthog/agent` (the same package powering PostHog Code) running inside a sandbox, with tools exposed as MCP servers. The frontend doesn't need to know any of this — it keeps talking to `/conversations/*`. The backend mediates.

Wins:

- **Shared agent runtime.** PostHog AI and PostHog Code converge on `@posthog/agent`. Bug-fixes, model upgrades, ACP improvements land in one place.
- **MCP-first tools.** Tools live in MCP servers. Customer-installed MCPs become first-class for PostHog AI without per-tool plumbing on our side.
- **Resumable conversations.** The Task/Run + SSE backfill model handles disconnects, multi-turn queueing, terminal-then-resume in one place.
- **Permission modes / sandboxing.** Dangerous-operation approvals reuse the sandbox's `permission_request` channel instead of a parallel reducer.
- **Smaller blast radius.** Frontend stays. Tests stay green. The migration ships behind a single per-conversation routing decision.

---

## 2. Architecture target

```
┌──────────────────────────────────────────────┐
│ frontend/src/scenes/max  (mostly unchanged)  │
│  LangGraph path: existing handlers verbatim  │
│  Sandbox path: + sandboxStreamLogic.ts       │
│    - owns EventSource to cloud-agent stream  │
│    - parses default event:message + data.type│
│    - reconnect/backoff/dedup (ports Twig)    │
│    - raw ACP → ToolInvocation / thread items │
│  - Thread.tsx + mcpToolRegistry adapter      │
│  - DangerousOperationApprovalCard (variant)  │
│  - Slash commands, history, FeedbackPrompt   │
└───────────────────┬──────────────────────────┘
                    │ POST /conversations/{id}/sandbox/     (NEW — message routing)
                    │ GET  /conversations/{id}/log/         (NEW — multi-Run history)
                    │ POST /conversations/{id}/stream/      (LangGraph, unchanged)
                    │ POST /conversations/{id}/cancel/      (existing)
                    │ POST /conversations/{id}/permission/  (NEW — approval)
                    ▼
┌──────────────────────────────────────────────┐
│ Django (ee/hogai/sandbox/)                   │
│  - Conversation.agent_runtime: 'langgraph'   │
│       | 'sandbox'   ◀── routing decision     │
│  - Conversation.sandbox_task (FK)            │
│  - current_sandbox_run (derived from Task)   │
│  - sandbox-route only (non-streaming):       │
│    - creates Task + Run on first message     │
│    - sends POST /command/ on follow-up       │
│    - wraps user content in <posthog_context> │
│    - returns { task_id, run_id, ... } JSON   │
└───────────────────┬──────────────────────────┘
                    │ REST + POST /command/    (cloud-agent spec)
                    │
                    │   ╔════════════════════════════════════╗
                    │   ║ Frontend opens SSE DIRECTLY here:  ║
                    │   ║ GET /api/projects/{tid}/tasks/     ║
                    │   ║     {taskId}/runs/{runId}/stream/  ║
                    │   ║ (same endpoint PostHog Code uses)  ║
                    │   ╚════════════════════════════════════╝
                    ▼
┌──────────────────────────────────────────────┐
│ Cloud agent relay (existing)                 │
│  - /api/projects/{tid}/tasks/{tid}/runs/...  │
│  - SSE bridge + JWT-scoped sandbox connection │
└───────────────────┬──────────────────────────┘
                    │ ACP via JWT
                    ▼
┌──────────────────────────────────────────────┐
│ Sandbox: @posthog/agent + Claude/Codex       │
│  - systemPrompt built by Django at Run-start │
│  - MCP servers:                              │
│    - posthog-data (taxonomy, hogql, search)  │
│    - posthog-notebook                        │
│    - posthog-code (PostHog Code integration) │
│    - user-installed MCPs                     │
│  TodoWrite is Claude Code SDK built-in       │
└──────────────────────────────────────────────┘
```

The browser talks to Django for **routing** (POSTs) and to the cloud-agent endpoint for **streaming** (GET SSE). Both are PostHog-cloud HTTPS endpoints — same origin, no CORS pain. The sandbox is never reachable from the browser.

---

## 3. Concept mapping — PostHog AI today ↔ sandbox tomorrow

| PostHog AI today | Backed by tomorrow (when `agent_runtime === 'sandbox'`) | Note |
|---|---|---|
| `Conversation` row | `Conversation` row **+** linked `Task` + first `TaskRun` | The conversation stays the user-facing entity. Task/Run are storage for the agent runtime. |
| Conversation message thread | Conversation messages (unchanged on the wire) **+** the Task's persisted log (NDJSON in S3, source-of-truth for replay) | The chat UI reads conversation messages exactly as today. |
| `POST /conversations/stream/` | Same endpoint; new branch in the view that opens the cloud-agent SSE upstream and passes ACP frames through verbatim per `02_CORE.md` § 4 | Public API unchanged. |
| Conversation continuation (next user message) | Same endpoint; relay sends `POST /command/` `user_message` on the existing Run | Same Task, same Run, additive ACP turn. |
| Terminal conversation + new prompt | A new `TaskRun` with `resume_from_run_id` pointing at the prior Run | Relay handles transparently — frontend just sees a normal next-message. |
| `ui_context: MaxUIContext` (rich serialized entities) | `attached_context: AttachedContext[]` (typed IDs + labels) | See `01_CONTEXT.md`. Wrapping into `<posthog_context>` happens in the relay. |
| `contextual_tools` registered via `useMaxTool` | **Removed for sandbox runtime.** Only the static MCP tool set is available. | Scenes can still subscribe to thread state read-only; they can no longer expose callbacks the agent calls. LangGraph path keeps using `useMaxTool` unchanged — see `BACKWARD_COMPAT.md` #6. |
| Tool result `ui_payload.kind` dispatch | Tool dispatch on **MCP qualified tool name** (`server.tool`) via a frontend `mcpToolRegistry` consuming `ToolInvocation` records emitted by `sandboxStreamLogic` | See `03_RICH_UI.md`. Existing `messages/*Answer.tsx` components survive behind thin adapters that read raw `rawInput` / output. |
| `DangerousOperationApprovalCard` | Same component; bound to ACP `permission_request` events (hoisted by the relay as a convenience event) | Wiring layer changes; UI doesn't. |
| `agent_mode` (`plan`, `sql`, `product_analytics`, …) | Collapsed to one unified prompt + tool gating; `plan` maps to ACP `permission_mode: 'plan'` | See `04_PROMPTS.md` § 4. |
| `is_sandbox` flag | Always true when `agent_runtime === 'sandbox'` | Becomes a read of `agent_runtime`. |
| `trace_id` per turn | Same (generated server-side at message create) | Telemetry plumbing untouched. |
| Slash commands (`/init`, `/remember`, `/usage`, `/feedback`, `/ticket`) | Same client behavior; `/remember` becomes a no-op for the sandbox path (core memory is dropped — see `TODO.md`) or routes to an MCP tool if/when one exists | See `02_CORE.md` § 7. |
| Conversation history (`GET /conversations/`) | Same endpoint, same shape, optionally filtered by `agent_runtime` | Sandbox runs surface in the same list. |
| `core_memory` / `ManageMemoriesTool` | **Dropped.** | See `TODO.md` for backfill. |
| `maxBillingContextLogic` / billing in systemPrompt | **Dropped.** | See `TODO.md` for backfill (likely a billing MCP tool). |

---

## 4. What stays on the frontend (i.e., does **not** change)

Everything in `frontend/src/scenes/max/` that isn't explicitly called out below.

Concretely:

| Surface | File(s) | Why preserved |
|---|---|---|
| Scene shell | `Max.tsx`, `Intro.tsx`, `MaxChangelog.tsx`, `floatingMaxPositionLogic.tsx` | Pure shell — agnostic to runtime |
| Conversation list + thread state | `maxLogic.tsx`, `maxThreadLogic.tsx`, `maxGlobalLogic.tsx` | EventSource SSE consumer keeps working; we just add a few new event-name cases (see `02_CORE.md` § 4) |
| Thread + message dispatch | `Thread.tsx`, `MarkdownMessage.tsx`, `messages/MessageTemplate.tsx` | New dispatch path for MCP tool calls layered on top — see `03_RICH_UI.md` § 2 |
| Tool-output renderers | `messages/VisualizationArtifactAnswer.tsx`, `NotebookArtifactAnswer.tsx`, `UIPayloadAnswer.tsx`, `ErrorTrackingIssueCard.tsx`, `ErrorTrackingFiltersSummary.tsx`, `MultiQuestionForm.tsx`, `RecordingsFiltersSummary.tsx`, `SessionSummarizationProgress.tsx`, `maxErrorTrackingWidgetLogic.ts` | Reused behind ~5–15-line adapters that pull props from raw MCP `rawInput`/output — see `03_RICH_UI.md` § 3 |
| Approval flow | `DangerousOperationApprovalCard.tsx`, `approvalOperationUtils.ts` | Wired to ACP `permission_request` (surfaced by the cloud-agent stream as `data.type === 'permission_request'`; ingested by `sandboxStreamLogic`) — see `02_CORE.md` § 5 and `03_RICH_UI.md` § 5 |
| Feedback + ticketing | `FeedbackPrompt.tsx`, `useFeedback.ts`, `TicketPrompt.tsx`, `ticketUtils.ts` | Orthogonal to runtime |
| Input area + slash commands | `components/InputFormArea.tsx`, `QuestionInput.tsx`, `SidebarQuestionInput.tsx`, `components/SlashCommandAutocomplete.tsx`, `slash-commands.tsx` | UI unchanged; `/remember` becomes a no-op for sandbox runs (see `02_CORE.md` § 7) |
| Thinking messages | `utils/thinkingMessages.ts` | Driven by ACP `_posthog/progress` notifications — see `03_RICH_UI.md` § 6 |
| Type shapes (entity contexts) | `maxTypes.ts` | Slimmed to `AttachedContext` shape — see `01_CONTEXT.md` § 1 |
| Tab-aware scene integration | `Max.tsx` + `tabAwareScene` plumbing | Unchanged |

---

## 5. What changes on the frontend (additive, mostly small)

| Change | Where | Spec |
|---|---|---|
| Add new SSE event-name handlers (`acp`, `permission_request`, `status`, `error`) | `maxThreadLogic.tsx` SSE event-handler section. `acp` delegates to `sandboxStreamLogic`; the others reuse existing handlers with sandbox-runtime branches. | `02_CORE.md` § 7 |
| New ACP stream processor — parses raw `StoredLogEntry` frames into `ToolInvocation` / `ThreadItem` state for the renderer | New file: `frontend/src/scenes/max/sandboxStreamLogic.ts` | `02_CORE.md` § 6 |
| Tool-name → renderer registry | New file: `frontend/src/scenes/max/mcpToolRegistry.tsx` | `03_RICH_UI.md` § 3 |
| Thread.tsx dispatch on MCP tool call messages (registry lookup, fallback for unknown tools) | `Thread.tsx` (single new switch case) | `03_RICH_UI.md` § 2 |
| Renderer adapters per existing `messages/*.tsx` (turn raw `rawInput`/output into the props the component expects) | `frontend/src/scenes/max/messages/adapters/` (new directory) | `03_RICH_UI.md` § 3 |
| `AttachedContext` collection (replaces `MaxContextInput` compilation) | `maxContextLogic.ts` simplification — drop helpers, drop nested data, return flat list | `01_CONTEXT.md` § 3 |
| Send `attached_context: AttachedContext[]` field on conversation create/message endpoints | `maxThreadLogic.tsx` request body | `01_CONTEXT.md` § 3.5 |

## 6. What gets deleted on the frontend

| Surface | File(s) |
|---|---|
| Dynamic tool registration (no longer applicable — only static MCP tools exist) | `MaxTool.tsx` (already `@deprecated`), `useMaxTool.ts`, `maxGlobalLogic.toolMap` reducer, `max-constants.tsx` `TOOL_DEFINITIONS` / `ToolDefinition` / `ToolRegistration` types |
| All `useMaxTool(…)` call sites across the codebase | Various scenes (grep for `useMaxTool`) — replaced with read-only thread-state subscriptions where they actually need something |
| Billing context resolution on the frontend | `maxBillingContextLogic.tsx` + `*Type.ts` companion |
| Pre-interpolated context payloads | `MaxUIContext`, `compiledContext` selector, `createMaxContextHelpers` (helpers serialize nested entity data — no longer needed); the lightweight `MaxContextItem` types stay for the chip UI |

For now these stay co-located with `scenes/max/` for ease of rollback during the soak. They're flagged for deletion in the cleanup PR after the sandbox path defaults on.

---

## 7. What changes on the backend (the bulk of the work)

| Change | Where | Spec |
|---|---|---|
| `Conversation.agent_runtime: 'langgraph' \| 'sandbox'` + nullable `Conversation.sandbox_task` FK | Conversation model + migration | `02_CORE.md` § 2 |
| New sandbox-only routing endpoint `POST /conversations/{id}/sandbox/` (non-streaming) + `GET /conversations/{id}/log/` (multi-Run history); LangGraph `POST /stream/` unchanged | Conversation views | `02_CORE.md` §§ 3–4 |
| New sandbox message-routing handler (`ee/hogai/sandbox/message_view.py`): wraps + dedupes user content; creates Task+Run on first message; sends `POST /command/` for follow-ups; returns `{task_id, run_id, ...}` JSON. No Django-side SSE relay — the frontend opens SSE directly against `/api/projects/{tid}/tasks/.../stream/`, the same endpoint PostHog Code consumes. | `ee/hogai/sandbox/` (mostly new) | `02_CORE.md` §§ 3–5 |
| `<posthog_context>` wrapper builder | `ee/hogai/sandbox/context_wrapper.py` | `01_CONTEXT.md` § 4 |
| `build_posthog_ai_system_prompt(team, user, conversation)` — composes the sandbox `systemPrompt` from the migrated chat_agent prompts | `ee/hogai/sandbox/system_prompt.py` | `04_PROMPTS.md` § 6 |
| MCP servers exposing the existing toolkit tools (`posthog-data`, `posthog-notebook`, `posthog-tasks`, etc.) | New module per server | `04_PROMPTS.md` § 5 |
| Conversation rollover: when a Run goes terminal, a follow-up message creates a new Run with `resume_from_run_id`; conversation gets re-pointed to the new run | Adapter | `02_CORE.md` § 6 |
| Feature flag `posthog-ai-sandbox` chooses `agent_runtime` at Conversation create | Conversation create view | `02_CORE.md` § 2 + `00_OVERVIEW.md` § 9 |

---

## 8. Spec dependencies and reading order

```
00_OVERVIEW (this doc)
        │
        ├── 04_PROMPTS    ◀── leaf, can start immediately (backend prompt builder)
        │
        ├── 01_CONTEXT    ◀── needs the AttachedContext field on the conversation
        │                     create/message request body (defined here, used by 02)
        │
        ├── 02_CORE       ◀── depends on 04 (knows how the systemPrompt is built)
        │                     depends on 01 (knows how attached_context lands)
        │
        └── 03_RICH_UI    ◀── depends on 02 (event shapes the registry consumes)
```

Suggested phasing (each phase ships behind the `posthog-ai-sandbox` flag):

1. **Phase 0 — Prompts** (`04_PROMPTS.md`): `build_posthog_ai_system_prompt()` + the 5–6 MCP server stubs (just enough to return tool descriptions, even with empty implementations). Verified by snapshot tests of the produced prompt.

2. **Phase 1 — Relay happy path** (`02_CORE.md`): relay creates Task + Run, opens upstream SSE, passes ACP frames straight through wrapped in `StoredLogEntry`. Frontend `sandboxStreamLogic` parses them. End-to-end: user says "hello", agent responds. No tools yet beyond a heartbeat MCP server.

3. **Phase 2 — Context** (`01_CONTEXT.md`): `<posthog_context>` wrapping in the relay; `attached_context` field on the conversation request shape; new sandbox context logic on the frontend.

4. **Phase 3 — Tools** (`04_PROMPTS.md` § 5 + `03_RICH_UI.md`): turn on real MCP server implementations one at a time, each with a frontend renderer adapter behind a sub-flag (`posthog-ai-sandbox-tool-{slug}`). Tools roll out individually to bound risk.

5. **Phase 4 — Approval flow** (`02_CORE.md` § 5, `03_RICH_UI.md` § 5): `permission_request` ↔ `DangerousOperationApprovalCard` rewiring.

6. **Phase 5 — Default on** for internal users → dogfood window → external rollout.

7. **Phase 6 — Cleanup**: delete `useMaxTool` / `MaxTool.tsx` / `maxBillingContextLogic`, prune `MaxUIContext` shapes, decommission the LangGraph stack.

---

## 9. Feature-flagging strategy

- Single boolean flag: `posthog-ai-sandbox` (default `false`).
- Read at conversation-create time. The chosen runtime is stamped onto `Conversation.agent_runtime` and stays for the lifetime of the conversation (avoids mid-conversation engine swaps).
- Per-tool sub-flags `posthog-ai-sandbox-tool-{slug}` gate individual MCP servers during Phase 3 rollout.
- Per-user resolution lets internal users flip ahead of customers.

---

## 10. Open questions for the team

Spec-specific opens are at the bottom of each spec. Cross-spec:

1. **Conversation ↔ Task lifecycle.** A conversation can outlive multiple Runs (resume after terminal). Where should the *Task* reset boundary be? Two options: (a) one Task per conversation, many Runs; (b) one Task per Run cluster, multiple Tasks per conversation. (a) is cleaner. *Owner: backend.* See `02_CORE.md` § 2.
2. **Permission mode default.** `bypassPermissions` (no friction) or `acceptEdits` (require user OK on data writes like notebook creation)? Today's `DangerousOperationApprovalCard` implies the latter for some ops. *Owner: AI.* See `02_CORE.md` § 5.
3. **Mode replacement.** What happens to "plan mode" specifically? Three candidates in `04_PROMPTS.md` § 4. Recommendation: ACP `permission_mode: 'plan'`. *Owner: AI.*
4. **Slash command `/remember`.** Core memory is dropped. Does `/remember` become a no-op with a tooltip, or do we keep a degenerate path until a memory MCP server lands? *Owner: AI.* See `02_CORE.md` § 7.
5. **Per-tool sub-flag granularity.** Per MCP server, or per tool inside a server? Per server is simpler; per tool gives finer rollout control. *Owner: AI.*
6. **Telemetry continuity.** All existing LLM Analytics dashboards filter on conversation/event shapes that the LangGraph path emits. Confirm parity from the relay side. *Owner: AI + LLM Analytics.*
7. **Backfills.** See [`TODO.md`](./TODO.md) — billing context, anything else discovered during build.

---

## 11. Glossary

| Term | Definition |
|---|---|
| **ACP** | Agent Connection Protocol. NDJSON-framed JSON-RPC between the agent-server and the underlying coding agent (Claude Code, Codex). The wire format the agent-server taps and broadcasts as cloud-agent SSE. |
| **Sandbox message-routing handler** (in this spec) | The Django module under `ee/hogai/sandbox/` (entry point: `message_view.py`) that bridges the new public endpoint `POST /conversations/{id}/sandbox/` to the cloud-agent REST API. Owns conversation routing, context wrapping + dedupe, system-prompt build, Run-create / `POST /command/` dispatch. Non-streaming; stateless across requests. The SSE stream itself bypasses Django — the frontend opens it directly against the cloud-agent endpoint. |
| **Sandbox** | Ephemeral container running `@posthog/agent` + the underlying model. Provisioned per Task/Run by PostHog cloud. |
| **agent-server** | HTTP server (`Twig/packages/agent/src/server/agent-server.ts`) running inside the sandbox. Frontend and Django both talk to it only through PostHog cloud's REST+SSE bridge — never directly. |
| **MCP** | Model Context Protocol. Tools exposed to the agent as MCP servers. PostHog data tools become MCP servers. |
| **Task** | Unit of work in cloud agents (cloud spec § 2.3). For PostHog AI, one Task per conversation. |
| **Run** | A single execution of a Task. New Run = new sandbox session. Resume-after-terminal creates a new Run with `state.resume_from_run_id`. |
| **`StoredLogEntry`** | Wire envelope around a single ACP notification: `{ type: 'notification', timestamp?, notification: { method?, params?, result?, error? } }`. The cloud-agent stream emits these as the bulk of `data.type === 'notification'` traffic — see `02_CORE.md` § 4.1. |
| **`session/update`** | ACP notification carrying agent message chunks, tool calls, mode changes. Frontend dispatches off its `params.update.sessionUpdate` discriminator. |
| **`_posthog/*` notification** | Custom ACP notification namespace from the agent-server. Examples: `_posthog/run_started`, `_posthog/turn_complete`, `_posthog/progress`. Cloud spec § 10.8. |
| **systemPrompt** | The composed string passed via `clientConnection.newSession({ _meta: { systemPrompt } })`. Built by Django's `POST /sandbox/` handler from `ee/hogai/chat_agent/prompts/` content. |

---

## 12. Out of scope

- **Local↔cloud handoff** (Twig spec § 11). PostHog AI doesn't have a local mode.
- **GitHub integration / PR creation.** The Django `POST /sandbox/` handler creates Tasks with no repository; agent-server runs in "No Repository Mode" with `--createPr=false`.
- **Sandbox environment CRUD UI.** Use the default sandbox environment for all PostHog AI runs.
- **Conversation export / sharing.** Not part of this migration.
- **A separate `scenes/posthog-ai/` directory.** We're not creating one — existing `scenes/max/` carries the new behavior behind the runtime flag.
