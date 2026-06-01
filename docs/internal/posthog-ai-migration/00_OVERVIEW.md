# PostHog AI → Sandbox Agent Migration — Overview

Migration of PostHog AI ("Max") from the LangGraph-backed `ee/hogai/chat_agent/` runtime onto the cloud-agent / sandbox architecture documented in [`CLOUD_AGENTS_FRONTEND_SPEC.md`](../CLOUD_AGENTS_FRONTEND_SPEC.md).

**The frontend stays in `frontend/src/scenes/max/`.** The public `/api/.../conversations/*` contract stays (plus one additive sandbox-only POST endpoint). The migration is split: Django gains a thin non-streaming routing endpoint `POST /conversations/{id}/sandbox/`, implemented in the **new** `products/posthog_ai/` product (`products/posthog_ai/backend/message_routing.py`), that wraps + dedupes attached context, builds the `systemPrompt`, and creates/continues a `products/tasks` Task/Run via **in-process Python calls** (`Task.create_and_run` / `signal_task_followup_message` / `task.create_run` — see `products/tasks/backend/models.py:279`, `products/tasks/backend/temporal/client.py:314`, `products/tasks/backend/models.py:230`). It returns the IDs the frontend needs. There is **no** new bridge and **no** HTTP-to-self: `products/tasks` is the in-monorepo cloud-agent backend, reused directly. The frontend then opens SSE **directly** against the existing `products/tasks` endpoint `GET /api/projects/{tid}/tasks/{taskId}/runs/{runId}/stream/` (`products/tasks/backend/api.py:2659`) — the same endpoint PostHog Code consumes. A new frontend module (`sandboxStreamLogic.ts`) owns the SSE connection, parses the wire format (default `event: message` + `data.type` discrimination, per PostHog Code), and produces thread-shaped state without touching today's LangGraph event handlers.

This shifts the migration from "rewrite the chat UI" to "build a thin in-process router + a frontend stream processor + a small handful of additive `maxThreadLogic` cases".

| #   | Topic                                                                        | Spec                                                   |
| --- | ---------------------------------------------------------------------------- | ------------------------------------------------------ |
| 1   | Context (passing context to the agent)                                       | [`01_CONTEXT.md`](./01_CONTEXT.md)                     |
| 2   | Core functionality (message routing endpoint + frontend stream processor)    | [`02_CORE.md`](./02_CORE.md)                           |
| 3   | Rich UI (MCP tool dispatch → existing renderers)                             | [`03_RICH_UI.md`](./03_RICH_UI.md)                     |
| 4   | Prompts (`ee/hogai/chat_agent/prompts/` → sandbox `systemPrompt`)            | [`04_PROMPTS.md`](./04_PROMPTS.md)                     |
| 5   | Sandbox sizing + Task model adjustments (constrained profile for PostHog AI) | [`05_SANDBOX.md`](./05_SANDBOX.md)                     |
| 6   | MCP tool contracts (per-tool input/output shapes)                            | [`MCP_TOOLS.md`](./MCP_TOOLS.md)                       |
| —   | **Backward-compatibility audit** (read before any spec)                      | [`BACKWARD_COMPAT.md`](./BACKWARD_COMPAT.md)           |
| —   | Open backfill items                                                          | [`TODO.md`](./TODO.md)                                 |
| —   | Upstream cloud-agent REST + SSE reference                                    | [`cloud_implementation.md`](./cloud_implementation.md) |

> **⚠ Coexistence mode.** The migration runs behind a per-user feature flag (`phai-sandbox-mode`). Users without the flag must see today's Max exactly as today. Sub-specs `01_CONTEXT.md`, `03_RICH_UI.md`, and `04_PROMPTS.md` describe the _end-state_ code shape; [`BACKWARD_COMPAT.md`](./BACKWARD_COMPAT.md) overrides them for the rollout window — sandbox logic lives **alongside** the existing code, not in place of it. `maxContextLogic.ts`, `maxBillingContextLogic.tsx`, `MaxTool.tsx`, `useMaxTool.ts`, all 38 `useMaxTool` call sites, and every existing `messages/*.tsx` renderer stay untouched during the migration. Cleanup is a follow-up phase after default-on.

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

```text
┌──────────────────────────────────────────────┐
│ frontend/src/scenes/max  (mostly unchanged)  │
│  LangGraph path: existing handlers verbatim  │
│  Sandbox path: + sandboxStreamLogic.ts       │
│    - owns EventSource to products/tasks stream│
│    - parses default event:message + data.type│
│    - reconnect/backoff/dedup (ports Twig)    │
│    - raw ACP → ToolInvocation / thread items │
│  - Thread.tsx + mcpToolRegistry adapter      │
│  - DangerousOperationApprovalCard (variant)  │
│  - Slash commands, history, FeedbackPrompt   │
└───────────────────┬──────────────────────────┘
                    │ POST /conversations/{id}/sandbox/     (NEW — in-process routing)
                    │ POST /conversations/{id}/stream/      (LangGraph, unchanged)
                    ▼
┌──────────────────────────────────────────────┐
│ Django request handler                       │
│ (products/posthog_ai/backend/)               │
│  - Conversation.agent_runtime: 'langgraph'   │
│       | 'sandbox'   ◀── routing decision     │
│  - Conversation.task (FK)                    │
│  - current_run (derived from Task)           │
│  - sandbox-route only (non-streaming):       │
│    - wraps user content in <posthog_context> │
│    - builds systemPrompt                      │
│    - calls products/tasks IN-PROCESS:        │
│        Task.create_and_run (first message)   │
│        signal_task_followup_message (in-prog)│
│        task.create_run (terminal resume)     │
│    - NO HTTP-to-self, NO Django SSE relay    │
│    - returns { task_id, run_id, ... } JSON   │
└───────────────────┬──────────────────────────┘
                    │ in-process Python calls
                    │
                    │   ╔════════════════════════════════════╗
                    │   ║ Frontend opens SSE DIRECTLY against ║
                    │   ║ the EXISTING products/tasks stream: ║
                    │   ║ GET /api/projects/{tid}/tasks/     ║
                    │   ║     {taskId}/runs/{runId}/stream/  ║
                    │   ║ (same endpoint PostHog Code uses)  ║
                    │   ╚════════════════════════════════════╝
                    ▼
┌──────────────────────────────────────────────┐
│ products/tasks backend (REUSED — not new)    │
│  - Temporal workflows + sandbox provisioning │
│  - GET /runs/{id}/stream/  (Redis → SSE)     │
│  - POST /runs/{id}/command/ (cancel, perms,  │
│       user_message → Temporal signal)        │
│  - GET /runs/{id}/logs/  (resume-chain S3)   │
└───────────────────┬──────────────────────────┘
                    │ ACP via JWT
                    ▼
┌──────────────────────────────────────────────┐
│ Sandbox: @posthog/agent + Claude/Codex       │
│  - systemPrompt from products/posthog_ai,    │
│      carried in initial Run state            │
│  - MCP (injected by products/tasks           │
│      start_agent_server):                    │
│    - posthog (single-exec — services/mcp/)  │
│      (one outer tool `exec`; inner tools     │
│       enabled per yaml: execute-sql,         │
│       insight-create, read-data-schema, …;   │
│       consumer x-posthog-mcp-consumer:       │
│       posthog-ai)                            │
│    - user-installed MCPs                     │
│  TodoWrite is Claude Code SDK built-in       │
└──────────────────────────────────────────────┘
```

The browser talks to Django for **routing** (the `POST /conversations/{id}/sandbox/` handler in `products/posthog_ai/backend/`) and to the existing `products/tasks` stream endpoint for **streaming** (GET SSE). Both are PostHog-cloud HTTPS endpoints — same origin, no CORS pain. The Django handler reaches `products/tasks` via in-process Python calls, not HTTP. The sandbox is never reachable from the browser.

---

## 3. Concept mapping — PostHog AI today ↔ sandbox tomorrow

| PostHog AI today                                                        | Backed by tomorrow (when `agent_runtime === 'sandbox'`)                                                                                                                                                                                                                         | Note                                                                                                                                                                                        |
| ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Conversation` row                                                      | `Conversation` row **+** linked `Task` + first `TaskRun`                                                                                                                                                                                                                        | The conversation stays the user-facing entity. Task/Run are storage for the agent runtime.                                                                                                  |
| Conversation message thread                                             | Conversation messages (unchanged on the wire) **+** the Task's persisted log (NDJSON in S3, source-of-truth for replay)                                                                                                                                                         | The chat UI reads conversation messages exactly as today.                                                                                                                                   |
| `POST /conversations/stream/`                                           | New non-streaming `POST /conversations/{id}/sandbox/` handler creates/continues the Task/Run via in-process `products/tasks` calls; the **frontend** then opens the existing `products/tasks` SSE endpoint directly (Option B). See `02_CORE.md` § 4                            | Public API still `/conversations/*`; no Django SSE relay.                                                                                                                                   |
| Conversation continuation (next user message)                           | In-process `signal_task_followup_message(run.workflow_id, wrapped_content, artifact_ids)` (`products/tasks/backend/temporal/client.py:314`) — the same Temporal signal `POST /runs/{id}/command/` `method=user_message` fires internally (`products/tasks/backend/api.py:2249`) | Same Task, same Run, additive ACP turn — no HTTP.                                                                                                                                           |
| Terminal conversation + new prompt                                      | In-process `task.create_run(mode="interactive", extra_state={resume_from_run_id, ...})` (`products/tasks/backend/models.py:230`) + `execute_task_processing_workflow(...)` — a new Run with `resume_from_run_id` pointing at the prior Run                                      | `products/tasks` handles resume — frontend just sees a normal next-message.                                                                                                                 |
| `ui_context: MaxUIContext` (rich serialized entities)                   | `attached_context: AttachedContext[]` (typed IDs + labels)                                                                                                                                                                                                                      | See `01_CONTEXT.md`. Wrapping into `<posthog_context>` happens in the `products/posthog_ai/backend/` handler.                                                                               |
| `contextual_tools` registered via `useMaxTool`                          | **Removed for sandbox runtime.** Only the static MCP tool set is available.                                                                                                                                                                                                     | Scenes can still subscribe to thread state read-only; they can no longer expose callbacks the agent calls. LangGraph path keeps using `useMaxTool` unchanged — see `BACKWARD_COMPAT.md` #6. |
| Tool result `ui_payload.kind` dispatch                                  | Tool dispatch on **MCP qualified tool name** (`server.tool`) via a frontend `mcpToolRegistry` consuming `ToolInvocation` records emitted by `sandboxStreamLogic`                                                                                                                | See `03_RICH_UI.md`. Existing `messages/*Answer.tsx` components survive behind thin adapters that read raw `rawInput` / output.                                                             |
| `DangerousOperationApprovalCard`                                        | Same component; bound to ACP `permission_request` events surfaced on the existing `products/tasks` stream; approvals reply via `POST /runs/{id}/command/` `method=permission_response` (`products/tasks/backend/api.py:2249`)                                                   | Wiring layer changes; UI doesn't.                                                                                                                                                           |
| `agent_mode` (`plan`, `sql`, `product_analytics`, …)                    | Collapsed to one unified prompt + tool gating; `plan` maps to ACP `permission_mode: 'plan'`                                                                                                                                                                                     | See `04_PROMPTS.md` § 4.                                                                                                                                                                    |
| `is_sandbox` flag                                                       | Always true when `agent_runtime === 'sandbox'`                                                                                                                                                                                                                                  | Becomes a read of `agent_runtime`.                                                                                                                                                          |
| `trace_id` per turn                                                     | Same (generated server-side at message create)                                                                                                                                                                                                                                  | Telemetry plumbing untouched.                                                                                                                                                               |
| Slash commands (`/init`, `/remember`, `/usage`, `/feedback`, `/ticket`) | Same client behavior; `/remember` becomes a no-op for the sandbox path (core memory is dropped — see `TODO.md`) or routes to an MCP tool if/when one exists                                                                                                                     | See `02_CORE.md` § 7.                                                                                                                                                                       |
| Conversation history (`GET /conversations/`)                            | Same endpoint, same shape, optionally filtered by `agent_runtime`                                                                                                                                                                                                               | Sandbox runs surface in the same list.                                                                                                                                                      |
| `core_memory` / `ManageMemoriesTool`                                    | **Dropped.**                                                                                                                                                                                                                                                                    | See `TODO.md` for backfill.                                                                                                                                                                 |
| `maxBillingContextLogic` / billing in systemPrompt                      | **Dropped.**                                                                                                                                                                                                                                                                    | See `TODO.md` for backfill (likely a billing MCP tool).                                                                                                                                     |

---

## 4. What stays on the frontend (i.e., does **not** change)

Everything in `frontend/src/scenes/max/` that isn't explicitly called out below.

Concretely:

| Surface                          | File(s)                                                                                                                                                                                                                                                                                         | Why preserved                                                                                                                                                                                                                                                                      |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Scene shell                      | `Max.tsx`, `Intro.tsx`, `MaxChangelog.tsx`, `floatingMaxPositionLogic.tsx`                                                                                                                                                                                                                      | Pure shell — agnostic to runtime                                                                                                                                                                                                                                                   |
| Conversation list + thread state | `maxLogic.tsx`, `maxThreadLogic.tsx`, `maxGlobalLogic.tsx`                                                                                                                                                                                                                                      | EventSource SSE consumer keeps working; we just add a few new event-name cases (see `02_CORE.md` § 4)                                                                                                                                                                              |
| Thread + message dispatch        | `Thread.tsx`, `MarkdownMessage.tsx`, `messages/MessageTemplate.tsx`                                                                                                                                                                                                                             | New dispatch path for MCP tool calls layered on top — see `03_RICH_UI.md` § 2                                                                                                                                                                                                      |
| Tool-output renderers            | `messages/VisualizationArtifactAnswer.tsx`, `NotebookArtifactAnswer.tsx`, `UIPayloadAnswer.tsx`, `ErrorTrackingIssueCard.tsx`, `ErrorTrackingFiltersSummary.tsx`, `MultiQuestionForm.tsx`, `RecordingsFiltersSummary.tsx`, `SessionSummarizationProgress.tsx`, `maxErrorTrackingWidgetLogic.ts` | Reused behind ~5–15-line adapters that pull props from raw MCP `rawInput`/output — see `03_RICH_UI.md` § 3                                                                                                                                                                         |
| Approval flow                    | `DangerousOperationApprovalCard.tsx`, `approvalOperationUtils.ts`                                                                                                                                                                                                                               | Wired to ACP `permission_request` (surfaced by the existing `products/tasks` stream as `data.type === 'permission_request'`; ingested by `sandboxStreamLogic`; replied via `POST /runs/{id}/command/` `method=permission_response`) — see `02_CORE.md` § 5 and `03_RICH_UI.md` § 5 |
| Feedback + ticketing             | `FeedbackPrompt.tsx`, `useFeedback.ts`, `TicketPrompt.tsx`, `ticketUtils.ts`                                                                                                                                                                                                                    | Orthogonal to runtime                                                                                                                                                                                                                                                              |
| Input area + slash commands      | `components/InputFormArea.tsx`, `QuestionInput.tsx`, `SidebarQuestionInput.tsx`, `components/SlashCommandAutocomplete.tsx`, `slash-commands.tsx`                                                                                                                                                | UI unchanged; `/remember` becomes a no-op for sandbox runs (see `02_CORE.md` § 7)                                                                                                                                                                                                  |
| Thinking messages                | `utils/thinkingMessages.ts`                                                                                                                                                                                                                                                                     | Driven by ACP `_posthog/progress` notifications — see `03_RICH_UI.md` § 6                                                                                                                                                                                                          |
| Type shapes (entity contexts)    | `maxTypes.ts`                                                                                                                                                                                                                                                                                   | Slimmed to `AttachedContext` shape — see `01_CONTEXT.md` § 1                                                                                                                                                                                                                       |
| Tab-aware scene integration      | `Max.tsx` + `tabAwareScene` plumbing                                                                                                                                                                                                                                                            | Unchanged                                                                                                                                                                                                                                                                          |

---

## 5. What changes on the frontend (additive, mostly small)

| Change                                                                                                                                                    | Where                                                                                                                                                                                    | Spec                  |
| --------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------- |
| Add new `data.type` handlers on the default `event: message` stream (`notification`, `permission_request`, `task_run_state`) plus the named `error` event | `maxThreadLogic.tsx` SSE event-handler section. `notification` frames delegate to `sandboxStreamLogic.ingestAcpFrame`; the others reuse existing handlers with sandbox-runtime branches. | `02_CORE.md` § 7      |
| New ACP stream processor — parses raw `StoredLogEntry` frames into `ToolInvocation` / `ThreadItem` state for the renderer                                 | New file: `frontend/src/scenes/max/sandboxStreamLogic.ts`                                                                                                                                | `02_CORE.md` § 6      |
| Tool-name → renderer registry                                                                                                                             | New file: `frontend/src/scenes/max/mcpToolRegistry.tsx`                                                                                                                                  | `03_RICH_UI.md` § 3   |
| Thread.tsx dispatch on MCP tool call messages (registry lookup, fallback for unknown tools)                                                               | `Thread.tsx` (single new switch case)                                                                                                                                                    | `03_RICH_UI.md` § 2   |
| Renderer adapters per existing `messages/*.tsx` (turn raw `rawInput`/output into the props the component expects)                                         | `frontend/src/scenes/max/messages/adapters/` (new directory)                                                                                                                             | `03_RICH_UI.md` § 3   |
| `AttachedContext` collection (replaces `MaxContextInput` compilation)                                                                                     | `maxContextLogic.ts` simplification — drop helpers, drop nested data, return flat list                                                                                                   | `01_CONTEXT.md` § 3   |
| Send `attached_context: AttachedContext[]` field on conversation create/message endpoints                                                                 | `maxThreadLogic.tsx` request body                                                                                                                                                        | `01_CONTEXT.md` § 3.5 |

## 6. What gets deleted on the frontend

| Surface                                                                        | File(s)                                                                                                                                                                                      |
| ------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Dynamic tool registration (no longer applicable — only static MCP tools exist) | `MaxTool.tsx` (already `@deprecated`), `useMaxTool.ts`, `maxGlobalLogic.toolMap` reducer, `max-constants.tsx` `TOOL_DEFINITIONS` / `ToolDefinition` / `ToolRegistration` types               |
| All `useMaxTool(…)` call sites across the codebase                             | Various scenes (grep for `useMaxTool`) — replaced with read-only thread-state subscriptions where they actually need something                                                               |
| Billing context resolution on the frontend                                     | `maxBillingContextLogic.tsx` + `*Type.ts` companion                                                                                                                                          |
| Pre-interpolated context payloads                                              | `MaxUIContext`, `compiledContext` selector, `createMaxContextHelpers` (helpers serialize nested entity data — no longer needed); the lightweight `MaxContextItem` types stay for the chip UI |

For now these stay co-located with `scenes/max/` for ease of rollback during the soak. They're flagged for deletion in the cleanup PR after the sandbox path defaults on.

---

## 7. What changes on the backend (the bulk of the work)

| Change                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | Where                                                                               | Spec                                    |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- | --------------------------------------- |
| `Conversation.agent_runtime: 'langgraph' \| 'sandbox'` + nullable `Conversation.task` FK (legacy `sandbox_task_id` / `sandbox_run_id` deprecated, not dropped)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | Conversation model + migration                                                      | `02_CORE.md` § 2                        |
| New sandbox-only routing endpoint `POST /conversations/{id}/sandbox/` (non-streaming); history reuses the existing `products/tasks` `GET /runs/{id}/logs/`; LangGraph `POST /stream/` unchanged                                                                                                                                                                                                                                                                                                                                                                                                                                                            | `ee/api/conversation.py` sandbox branch delegates to `products/posthog_ai/backend/` | `02_CORE.md` §§ 3–4                     |
| New message-routing handler (`handle_sandbox_message(...)`): wraps + dedupes attached context; builds `systemPrompt`; then calls `products/tasks` in-process — `Task.create_and_run` (`products/tasks/backend/models.py:279`) on first message, `signal_task_followup_message` (`products/tasks/backend/temporal/client.py:314`) on in-progress follow-up, `task.create_run` (`products/tasks/backend/models.py:230`) on terminal resume; returns `{task_id, run_id, trace_id, run_status, just_created_run}` JSON. No HTTP-to-self, no Django SSE relay — the frontend opens SSE directly against the existing `products/tasks` `GET /runs/{id}/stream/`. | `products/posthog_ai/backend/message_routing.py` (new)                              | `02_CORE.md` §§ 3–5                     |
| `<posthog_context>` wrapper builder (`wrap_user_message` + `prune_repeated_entity_refs`)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | `products/posthog_ai/backend/context_wrapper.py` (new)                              | `01_CONTEXT.md` § 4                     |
| `build_posthog_ai_system_prompt(...)` — composes the sandbox `systemPrompt` from the migrated chat_agent prompts                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | `products/posthog_ai/backend/system_prompt.py` (new)                                | `04_PROMPTS.md` § 6                     |
| MCP tools exposed via the existing `services/mcp/` single-exec `posthog` server — one outer `exec` tool, inner tools enabled per yaml `enabled: true` and filtered at runtime by scopes + feature flags + version. PostHog AI reuses the agent-server MCP injection pipeline (`get_sandbox_ph_mcp_configs()` in `start_agent_server`, `products/tasks/backend/temporal/process_task/activities/start_agent_server.py:156`); it adds a `POSTHOG_AI_CONSUMER = posthog-ai` and sends `x-posthog-mcp-consumer: posthog-ai`. No new MCP server per domain — PostHog Code uses the same server with `x-posthog-mcp-consumer: posthog-code`.                     | `services/mcp/definitions/*.yaml` + existing server code                            | `04_PROMPTS.md` § 5                     |
| Conversation rollover: when a Run goes terminal, a follow-up message creates a new Run with `resume_from_run_id` via in-process `task.create_run`; conversation gets re-pointed to the latest run (derived from `task.runs`)                                                                                                                                                                                                                                                                                                                                                                                                                               | `products/posthog_ai/backend/message_routing.py`                                    | `02_CORE.md` § 6                        |
| Feature flag `phai-sandbox-mode` (`has_sandbox_mode_feature_flag`, `ee/hogai/utils/feature_flags.py:96`) chooses `agent_runtime` at Conversation create                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | Conversation create view                                                            | `02_CORE.md` § 2 + `00_OVERVIEW.md` § 9 |

---

## 8. Spec dependencies and reading order

```text
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

Suggested phasing (each phase ships behind the `phai-sandbox-mode` flag):

1. **Phase 0 — Prompts** (`04_PROMPTS.md`): `build_posthog_ai_system_prompt()` + enabling the first inner MCP tools (just enough to return tool descriptions). Verified by snapshot tests of the produced prompt.

2. **Phase 1 — Routing happy path** (`02_CORE.md`): the `products/posthog_ai/backend/` handler creates a Task + Run in-process via `Task.create_and_run`; the frontend opens the existing `products/tasks` SSE endpoint and `sandboxStreamLogic` parses the `StoredLogEntry` frames. End-to-end: user says "hello", agent responds. No tools yet beyond a baseline inner tool.

3. **Phase 2 — Context** (`01_CONTEXT.md`): `<posthog_context>` wrapping in the `products/posthog_ai/backend/` handler; `attached_context` field on the conversation request shape; new sandbox context logic on the frontend.

4. **Phase 3 — Tools** (`04_PROMPTS.md` § 5 + `03_RICH_UI.md`): enable inner MCP tools one at a time, each with a frontend renderer adapter behind a sub-flag (`phai-sandbox-tool-{slug}`). Tools roll out individually to bound risk.

5. **Phase 4 — Approval flow** (`02_CORE.md` § 5, `03_RICH_UI.md` § 5): `permission_request` ↔ `DangerousOperationApprovalCard` rewiring.

6. **Phase 5 — Default on** for internal users → dogfood window → external rollout.

7. **Phase 6 — Cleanup**: delete `useMaxTool` / `MaxTool.tsx` / `maxBillingContextLogic`, prune `MaxUIContext` shapes, decommission the LangGraph stack.

---

## 9. Feature-flagging strategy

- Single boolean flag: `phai-sandbox-mode` (default `false`) — the existing flag resolved by `has_sandbox_mode_feature_flag` (`ee/hogai/utils/feature_flags.py:96`).
- Read at conversation-create time. The chosen runtime is stamped onto `Conversation.agent_runtime` and stays for the lifetime of the conversation (avoids mid-conversation engine swaps).
- Per-tool sub-flags `phai-sandbox-tool-{slug}` gate individual inner MCP tools during Phase 3 rollout.
- Per-user resolution lets internal users flip ahead of customers.

---

## 10. PR-to-spec index (implementation guide)

When implementing a PR, read **only the rows of this table for that PR** plus its hard-depends rows. Spec sections are pinned per row — opening a single file end-to-end is wasted work; opening only the listed § range is the design.

| PR # | What it builds                                                                                                                                                                                                                                       | Spec sections to read                                                                                                      | Hard depends on        | Owner lane         |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- | ---------------------- | ------------------ |
| I1.1 | Conversation model migration (`agent_runtime` + `task` FK; deprecate legacy UUIDs, no drop)                                                                                                                                                          | `02_CORE.md` § 2                                                                                                           | —                      | Backend            |
| I1.2 | Backend sandbox foundations bundle (`products/posthog_ai/backend/{context_wrapper.py, system_prompt.py, message_routing.py}` first-message in-process `Task.create_and_run` + rewire `ee/api/conversation.py` sandbox branch to delegate in-process) | `02_CORE.md` §§ 3, 4 (first-message), 4.5, 5.1; `01_CONTEXT.md` § 4; `04_PROMPTS.md` § 6; `cloud_implementation.md` §§ 2–5 | I1.1                   | Backend            |
| I1.3 | Frontend sandbox foundations bundle (`posthogAiContextLogic.ts` + `sandboxStreamLogic.ts` skeleton + `mcpToolRegistry.tsx` + fallback renderer + `Context.tsx`/`Thread.tsx`/`maxThreadLogic` runtime branches)                                       | `02_CORE.md` §§ 6, 7; `01_CONTEXT.md` § 3; `03_RICH_UI.md` §§ 2, 3.1–3.4                                                   | — (parallel with I1.2) | Frontend           |
| I2.4 | Multi-Run history — reuse the existing `products/tasks` `GET /runs/{id}/logs/` (`products/tasks/backend/api.py:2173`, already concatenates the entire resume chain from S3); no `log_assembler.py`, no custom multi-run walker                       | `02_CORE.md` §§ 4.6, 4.7                                                                                                   | I1.2                   | Backend            |
| I2.5 | Backend follow-up routing (in-progress + terminal-then-resume + cancel)                                                                                                                                                                              | `02_CORE.md` §§ 4 (follow-up), 5.2, 5.3, 5.4                                                                               | I1.2                   | Backend            |
| I2.6 | Frontend SSE resilience (reconnect/backoff/dedup + error mapping + terminal-status)                                                                                                                                                                  | `02_CORE.md` §§ 4.3, 4.4, 6; `Twig/apps/code/src/main/services/cloud-task/service.ts:440-690` (port directly)              | I1.3                   | Frontend           |
| I2.7 | History-load + telemetry parity                                                                                                                                                                                                                      | `02_CORE.md` §§ 4.7, 10                                                                                                    | I2.4, I2.6             | Frontend + Backend |
| I3.8 | Approvals + race-handling bundle (`permission_request` ingest + reply via existing `products/tasks` `POST /runs/{id}/command/` `method=permission_response` + card variant + `SELECT FOR UPDATE`)                                                    | `02_CORE.md` §§ 5.5, 6; `03_RICH_UI.md` § 5                                                                                | I2.6                   | Backend + Frontend |
| I3.9 | UX polish (slash command filter + pre-warming)                                                                                                                                                                                                       | `02_CORE.md` § 8; `05_SANDBOX.md` § 8                                                                                      | I2.7                   | Frontend + Backend |
| UI-A | Data-tool renderer adapters bundle (insight + dashboard + recording + error tracking)                                                                                                                                                                | `03_RICH_UI.md` §§ 3.3, 4 (data rows); `MCP_TOOLS.md` for shapes                                                           | I1.3                   | Frontend           |
| UI-B | Notebook renderer adapter (`notebooks-create`)                                                                                                                                                                                                       | `03_RICH_UI.md` §§ 3.3, 4 (notebook row); `MCP_TOOLS.md`                                                                   | I1.3                   | Frontend           |
| UI-C | Approval card variant + special UI (mode badge, `_posthog/progress`)                                                                                                                                                                                 | `03_RICH_UI.md` §§ 5, 6                                                                                                    | I3.8                   | Frontend           |

Total: ~14 PRs to default-on. Backend and frontend lanes run in parallel from Day 1. Enabling individual MCP inner tools is a one-line yaml flip (`services/mcp/definitions/*.yaml` `enabled: true` per-tool, behind `phai-sandbox-tool-{slug}`) — bundled into the PRs that actually consume them, not tracked as its own lane.

---

## 11. Open questions for the team

Spec-specific opens are at the bottom of each spec. Cross-spec:

1. **Conversation ↔ Task lifecycle.** A conversation can outlive multiple Runs (resume after terminal). Where should the _Task_ reset boundary be? Two options: (a) one Task per conversation, many Runs; (b) one Task per Run cluster, multiple Tasks per conversation. (a) is cleaner. _Owner: backend._ See `02_CORE.md` § 2.
2. **Permission mode default.** `bypassPermissions` (no friction) or `acceptEdits` (require user OK on data writes like notebook creation)? Today's `DangerousOperationApprovalCard` implies the latter for some ops. _Owner: AI._ See `02_CORE.md` § 5.
3. **Mode replacement.** What happens to "plan mode" specifically? Three candidates in `04_PROMPTS.md` § 4. Recommendation: ACP `permission_mode: 'plan'`. _Owner: AI._
4. **Slash command `/remember`.** Core memory is dropped. Does `/remember` become a no-op with a tooltip, or do we keep a degenerate path until a memory MCP server lands? _Owner: AI._ See `02_CORE.md` § 7.
5. **Per-tool sub-flag granularity.** Per MCP server, or per tool inside a server? Per server is simpler; per tool gives finer rollout control. _Owner: AI._
6. **Telemetry continuity.** All existing LLM Analytics dashboards filter on conversation/event shapes that the LangGraph path emits. Confirm parity from the `products/posthog_ai/backend/` routing side and the `products/tasks` stream. _Owner: AI + LLM Analytics._
7. **Backfills.** See [`TODO.md`](./TODO.md) — billing context, anything else discovered during build.

---

## 12. Glossary

| Term                                               | Definition                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| -------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **ACP**                                            | Agent Connection Protocol. NDJSON-framed JSON-RPC between the agent-server and the underlying coding agent (Claude Code, Codex). The wire format the agent-server taps and broadcasts as cloud-agent SSE.                                                                                                                                                                                                                                                                                                                                                                                |
| **Sandbox message-routing handler** (in this spec) | `products/posthog_ai/backend/message_routing.py` — the `handle_sandbox_message(...)` logic behind the new public endpoint `POST /conversations/{id}/sandbox/`. Owns conversation routing, context wrapping + dedupe, system-prompt build, and Task/Run create-or-continue by calling `products/tasks` **in-process** (`Task.create_and_run` / `signal_task_followup_message` / `task.create_run`). Non-streaming; stateless across requests; no HTTP-to-self. The SSE stream bypasses this handler entirely — the frontend opens the existing `products/tasks` stream endpoint directly. |
| **`products/tasks`**                               | The in-monorepo cloud-agent backend (Temporal workflows, sandbox provisioning, REST + SSE + command endpoints, S3 log persistence) that PostHog AI reuses in-process. Powers PostHog Code today; PostHog AI adds a new `Task.OriginProduct.POSTHOG_AI` and reuses the same entry points (`products/tasks/backend/api.py`, `models.py`, `temporal/`).                                                                                                                                                                                                                                     |
| **Sandbox**                                        | Ephemeral container running `@posthog/agent` + the underlying model. Provisioned per Task/Run by `products/tasks`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **agent-server**                                   | HTTP server (`../code/Twig packages/agent`) launched inside the sandbox by `products/tasks` `start_agent_server` (`products/tasks/backend/temporal/process_task/activities/start_agent_server.py:156`) — shared by PostHog Code and PostHog AI. Frontend and Django reach it only through `products/tasks`' REST+SSE endpoints, never directly.                                                                                                                                                                                                                                          |
| **MCP**                                            | Model Context Protocol. Tools exposed to the agent via the single-exec `posthog` server (`services/mcp/`): one outer `exec` tool, inner tools enabled per yaml and filtered at runtime by scopes + feature flags + version.                                                                                                                                                                                                                                                                                                                                                              |
| **Task**                                           | Unit of work in `products/tasks` (cloud spec § 2.3). For PostHog AI, one Task per conversation.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **Run**                                            | A single execution of a Task. New Run = new sandbox session. Resume-after-terminal creates a new Run with `state.resume_from_run_id`.                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **`StoredLogEntry`**                               | Wire envelope around a single ACP notification: `{ type: 'notification', timestamp?, notification: { method?, params?, result?, error? } }`. The `products/tasks` stream emits these as the bulk of `data.type === 'notification'` traffic — see `02_CORE.md` § 4.1.                                                                                                                                                                                                                                                                                                                     |
| **`session/update`**                               | ACP notification carrying agent message chunks, tool calls, mode changes. Frontend dispatches off its `params.update.sessionUpdate` discriminator.                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **`_posthog/*` notification**                      | Custom ACP notification namespace from the agent-server. Examples: `_posthog/run_started`, `_posthog/turn_complete`, `_posthog/progress`. Cloud spec § 10.8.                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **systemPrompt**                                   | The composed string passed via `clientConnection.newSession({ _meta: { systemPrompt } })`. Built by `products/posthog_ai/backend/system_prompt.py` from `ee/hogai/chat_agent/prompts/` content and carried in the initial Run state.                                                                                                                                                                                                                                                                                                                                                     |

---

## 13. Out of scope

- **Local↔cloud handoff** (Twig spec § 11). PostHog AI doesn't have a local mode.
- **GitHub integration / PR creation.** The `products/posthog_ai/backend/` handler creates Tasks with `repository=None` and `create_pr=False`; agent-server runs in "No Repository Mode".
- **Sandbox environment CRUD UI.** Use the default sandbox environment for all PostHog AI runs.
- **Conversation export / sharing.** Not part of this migration.
- **A separate `scenes/posthog-ai/` directory.** We're not creating one — existing `scenes/max/` carries the new behavior behind the runtime flag.
