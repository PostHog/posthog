# PostHog AI → Sandbox Agent Migration — Overview

Migration of `frontend/src/scenes/max/` (PostHog AI, "Max") onto the cloud-agent / sandbox architecture documented in [`CLOUD_AGENTS_FRONTEND_SPEC.md`](../CLOUD_AGENTS_FRONTEND_SPEC.md). The new UI will live in `frontend/src/scenes/posthog-ai/` and speak REST + SSE directly to PostHog cloud, which relays to an in-sandbox `@posthog/agent` server.

This document is the integration layer. Each numbered topic has a dedicated spec; read this first to understand the target architecture, what's invariant across all four areas, and the phasing order.

| # | Topic | Spec |
|---|---|---|
| 1 | Context (passing context to the agent) | [`01_CONTEXT.md`](./01_CONTEXT.md) |
| 2 | Core functionality (chat, streaming, history, queue) | [`02_CORE.md`](./02_CORE.md) |
| 3 | Rich UI (MCP tool intercepts → existing renderers) | [`03_RICH_UI.md`](./03_RICH_UI.md) |
| 4 | Prompts (`ee/hogai/chat_agent/prompts/` → `@posthog/agent`) | [`04_PROMPTS.md`](./04_PROMPTS.md) |

---

## 1. Why migrate

Today's stack:

- Django backend `ee/hogai/` orchestrates a LangGraph agent with custom tools (`ReadTaxonomyTool`, `ReadDataTool`, `SearchTool`, `CreateNotebookTool`, …).
- The frontend hits `POST /api/environments/{team_id}/conversations/stream/` and consumes a custom SSE protocol that carries assistant messages, tool calls with `ui_payload`s, planning steps, generation status, approvals.
- All agent state (conversation, messages, approvals, tools) is owned by `posthog`.

Target stack:

- The agent is `@posthog/agent` (the same package powering PostHog Code in the Twig repo), running inside a sandbox. It speaks ACP to a tapped read/write stream which the agent-server fans out as PostHog cloud SSE.
- PostHog data tools (`read_taxonomy`, `read_data`, `search`, `create_notebook`, …) become MCP servers the sandbox connects to. The agent talks to them via ACP `tool_call` events; the frontend intercepts those events and renders rich PostHog UI inline.
- The chat surface (history, threading, streaming) is replaced by the Task / TaskRun model: each "conversation" becomes a Task; each user turn streams as a Run (or follow-up `POST /command/` `user_message`).
- The frontend speaks REST + SSE directly. There is no Electron `main`/tRPC layer between the browser and PostHog cloud — the desktop's `CloudTaskService` becomes a Kea logic in the browser (see `02_CORE.md`).

Wins:

- **Single agent runtime.** PostHog AI and PostHog Code share `@posthog/agent`. Bug-fixes, model upgrades, ACP improvements land in one place.
- **MCP-first tool model.** Internal tools become MCP servers, externally extensible. Customer-installed MCPs become first-class citizens for PostHog AI without per-tool plumbing.
- **Long-running, resumable conversations.** The Task/Run + SSE backfill model handles disconnects, multi-turn queueing, terminal-then-resume, and history rehydration in one place.
- **Permission modes / sandboxing.** Dangerous-operation approvals reuse the sandbox's `permission_request` channel instead of a parallel approval reducer in `maxThreadLogic`.

---

## 2. Architecture target

```
┌────────────────────────────────────────┐
│ scenes/posthog-ai (browser)            │
│  - posthogAiLogic (top-level + history)│
│  - posthogAiThreadLogic (per-Task)     │
│  - sseWatcherLogic (per-Run)           │
│  - posthogAiContextLogic (scene ctx)   │
└──────────────┬─────────────────────────┘
               │ REST + SSE + POST /command/
               ▼
┌────────────────────────────────────────┐
│ PostHog cloud (Django)                 │
│  - /api/projects/{tid}/tasks/...       │   ← new: task model wrapping PostHog AI runs
│  - relay: SSE ↔ in-sandbox agent       │
│  - persisted log (S3 NDJSON)           │
│  - command channel (JSON-RPC)          │
└──────────────┬─────────────────────────┘
               │ ACP (via JWT)
               ▼
┌────────────────────────────────────────┐
│ Sandbox: @posthog/agent + Claude/Codex │
│  - systemPrompt: ported from chat_agent│
│  - MCP servers:                        │
│    - posthog-data (taxonomy, hogql, …) │
│    - posthog-search                    │
│    - posthog-notebook                  │
│    - posthog-tasks (todo)              │
│    - user-installed MCPs               │
└────────────────────────────────────────┘
```

The browser never talks to the sandbox directly. Everything flows through the cloud's REST + SSE proxy. Authentication is `Authorization: Bearer <token>` (project-scoped personal API key or OAuth token).

---

## 3. Concept mapping — PostHog AI today ↔ cloud agents tomorrow

| PostHog AI today | Cloud agent equivalent | Notes |
|---|---|---|
| `Conversation` | `Task` | One Task per chat. `task.title` = chat title. |
| Single conversation thread | One or more `TaskRun`s | Each "turn-after-terminal" becomes a new Run with `resume_from_run_id` (§ 4.3). For in-progress turns the same Run accepts multiple `user_message` commands. |
| `POST /conversations/stream/` | `POST /tasks/` + `POST /tasks/{id}/run/` for first message; `POST /command/` `user_message` for subsequent messages | See `02_CORE.md` § 2. |
| `ui_context: MaxUIContext` in stream body | Pre-interpolated into `systemPrompt`, OR injected as ACP `resource_link` blocks in the initial prompt, OR served via a `posthog-context` MCP server | See `01_CONTEXT.md` for the decision; recommended: hybrid (static slices in prompt + live MCP). |
| `contextual_tools` (from `useMaxTool`) | MCP servers passed to `--mcpServers` at sandbox start, or hot-loaded via `_posthog/refresh_session` | See `02_CORE.md` § 7 and `03_RICH_UI.md` § 4. |
| Tool result `ui_payload` | ACP `tool_call` / `tool_call_update` content blocks parsed in browser | `03_RICH_UI.md` defines the dispatcher. |
| Approval (`DangerousOperationApprovalCard`) | `permission_request` event + `permission_response` command | Same UI component, different wiring. `02_CORE.md` § 6. |
| `agent_mode` (`plan`, `sql`, `product_analytics`, …) | Either (a) collapsed into one general agent with a system-prompt section, (b) different `--claudeCodeConfig` presets per mode, or (c) modeled as a `permission_mode` toggle | See `04_PROMPTS.md` § 4. |
| `is_sandbox` flag | Always true | The new architecture *is* sandboxed. |
| `trace_id` per turn | Reuse `runId` + ACP `sessionId`; emit `trace_id` on `_posthog/run_started` for parity | Telemetry layer is unchanged. |
| Slash commands (`/init`, `/remember`, `/usage`, `/feedback`, `/ticket`) | Half stay in the browser, half become MCP tool invocations or backend pre-processing of `user_message` content | See `02_CORE.md` § 8 and `04_PROMPTS.md` § 3. |
| Conversation history (`GET /conversations/`) | `GET /tasks/?origin_product=posthog_ai` filtered + sorted | `02_CORE.md` § 3. |
| `core_memory`, `billing_context`, `groups_prompt` | Resolved server-side, pre-interpolated into `systemPrompt` per Run | `04_PROMPTS.md` § 2. |

Two things have **no equivalent** in the cloud model and need explicit decisions:

1. **No repository.** PostHog AI Tasks don't have a `repository`. Either (a) extend the Task model to allow `repository: null` and `github_integration: null` (cheap), or (b) introduce a `origin_product: "posthog_ai"` discriminator that the backend treats as a no-repo Task (cleaner). The Twig spec mentions `origin_product` in `Task` already (§ 2.3) — use it.
2. **No PR creation, no git.** The agent-server's session prompt currently mandates branch creation + draft PR (`agent-server.ts:1572-1726`). For PostHog AI we want `--createPr=false` and "No Repository Mode" (`agent-server.ts:1529-1726`, the branch documented in `04_PROMPTS.md` § 5).

---

## 4. Surfaces preserved as-is

These survive the migration unchanged or with cosmetic updates:

| Surface | File(s) | Why preserved |
|---|---|---|
| Markdown rendering | `MarkdownMessage.tsx`, `utils/markdownToTiptap.ts` | Render layer agnostic to transport. |
| Approval UI | `DangerousOperationApprovalCard.tsx`, `approvalOperationUtils.ts` | Same visual; rewired to `permission_request` (`03_RICH_UI.md` § 5). |
| Feedback / ticketing | `FeedbackPrompt.tsx`, `useFeedback.ts`, `TicketPrompt.tsx`, `ticketUtils.ts` | Orthogonal to chat transport. Stay as-is. |
| AI liability notice | `components/AILiabilityNotice.tsx` | Static. |
| Hedgehog intro | `Intro.tsx`, `MaxChangelog.tsx`, `maxChangelogLogic.ts` | Move verbatim. |
| Floating position | `floatingMaxPositionLogic.tsx` | Move verbatim. |
| Slash command autocomplete | `components/SlashCommandAutocomplete.tsx`, `slash-commands.tsx` | Same registry; some commands re-route to MCP tools (`02_CORE.md` § 8). |
| Tool-render components | `messages/VisualizationArtifactAnswer.tsx`, `NotebookArtifactAnswer.tsx`, `UIPayloadAnswer.tsx`, `ErrorTrackingIssueCard.tsx`, `MultiQuestionForm.tsx`, `SessionSummarizationProgress.tsx`, `RecordingsFiltersSummary.tsx`, `ErrorTrackingFiltersSummary.tsx`, `MessageTemplate.tsx` | These are the "rich UI" payoff. The MCP tool intercept layer in `03_RICH_UI.md` feeds them. |
| Thinking messages | `utils/thinkingMessages.ts` | Drive the same "Pondering…" / "Hobsnobbing…" loading copy from ACP `_posthog/progress` notifications. |
| Type shapes | `maxTypes.ts` (entity types: `MaxInsightContext`, `MaxDashboardContext`, …) | Re-export from `posthog-ai/types.ts`; the *helpers* (`createMaxContextHelpers`) remain unchanged. `01_CONTEXT.md` § 2. |

---

## 5. Surfaces that get a complete rewrite

| Surface | Replaced by | Spec |
|---|---|---|
| `maxLogic.tsx` (conversation list + UI shell) | `posthogAiLogic.ts` | `02_CORE.md` § 4 |
| `maxThreadLogic.tsx` (streaming, message state, approvals, queue) | `posthogAiThreadLogic.ts` + `runWatcherLogic.ts` (the SSE watcher, ported from `cloud-task/service.ts`) | `02_CORE.md` § 5–6 |
| `maxGlobalLogic.tsx` (tool registry, conversation cache) | `posthogAiGlobalLogic.ts` (tool registry stays; conversation cache becomes a Task cache) | `02_CORE.md` § 4 |
| `Thread.tsx` (message dispatch) | `Thread.tsx` in `scenes/posthog-ai/` — rebuilt around ACP `session/update` + intercepted `tool_call` events | `03_RICH_UI.md` § 2 |
| `Max.tsx` (scene shell) | `PostHogAi.tsx` (new scene export, tab-aware) | `02_CORE.md` § 4 |
| EventSource parser in `maxThreadLogic` (lines 661–673) | Reuse `Twig/apps/code/src/main/services/cloud-task/sse-parser.ts` logic (port to Kea listeners) | `02_CORE.md` § 5 |
| `maxContextLogic.ts` (compilation + scene-context auto-detection) | `posthogAiContextLogic.ts` — same compilation semantics, different output (see § 3 above) | `01_CONTEXT.md` § 3 |
| `useMaxTool.ts` (tool registration) | `usePostHogAiTool.ts` (registers MCP-style tools — see `03_RICH_UI.md` § 4) | `03_RICH_UI.md` |
| `maxBillingContextLogic.tsx` | Backend-side resolution (server pre-interpolates into systemPrompt). The logic disappears from the frontend. | `04_PROMPTS.md` § 2 |

`MaxTool.tsx` is already `@deprecated` (line 25-110); do not port — emit a deprecation removal task instead.

---

## 6. Surfaces removed entirely

- **Conversation queue endpoint** `GET /conversations/{id}/queue/`. The Task model already has SSE + `_posthog/turn_complete` for ordering. Multi-message queueing (combine pending follow-ups while a turn is running) becomes a client-side concern, matching the desktop's `combineQueuedCloudPrompts` (Twig § 13.11). Spec'd in `02_CORE.md` § 6.
- **`is_sandbox` flag.** Always true.
- **`agent_mode` round-tripping.** See `04_PROMPTS.md` § 4 for what replaces it.
- **`MaxTool.tsx` and call sites.** Delete; replace with `usePostHogAiTool.ts` (`03_RICH_UI.md` § 4).

---

## 7. Spec dependencies

```
00_OVERVIEW (this doc)
        │
        ├── 04_PROMPTS  ◀── leaf, can start immediately (backend pre-interpolation work)
        │
        ├── 01_CONTEXT  ◀── depends on 04 (some context is best baked into systemPrompt)
        │
        ├── 02_CORE     ◀── depends on 01 (knows what context payload to pass)
        │                   depends on 04 (knows what systemPrompt shape is)
        │
        └── 03_RICH_UI  ◀── depends on 02 (tool_call events come through the SSE watcher)
                            depends on 04 (knows which MCP tools exist)
```

Suggested **phasing** (each phase ships behind a feature flag):

1. **Phase 0 — Prompts** (`04_PROMPTS.md`): build the server-side `build_posthog_ai_system_prompt(team, user)` function. No UI changes. Verified by snapshot tests of the produced prompt against canonical examples.

2. **Phase 1 — Core transport** (`02_CORE.md`): scaffolds `scenes/posthog-ai/` with `posthogAiLogic`, `posthogAiThreadLogic`, `runWatcherLogic`. Hardcoded one tool (a simple echo MCP server) to prove the pipeline. Send/receive a string round-trip. No PostHog data access yet.

3. **Phase 2 — Context** (`01_CONTEXT.md`): port `maxContextLogic` semantics; wire scene `maxContext` selectors into the new prompt-prepend / MCP server.

4. **Phase 3 — Rich UI** (`03_RICH_UI.md`): intercept tool calls in the SSE watcher; map to existing renderers. This unlocks visualization, notebooks, error tracking, etc.

5. **Phase 4 — Tool parity** (`03_RICH_UI.md` § 6): stand up MCP servers for every existing `ee/hogai/chat_agent/toolkit.py` tool. Once all green, flip the feature flag.

6. **Phase 5 — Decommission `scenes/max/`**: delete in a follow-up PR, after a soak period.

---

## 8. Feature-flagging strategy

- Single boolean flag: `posthog-ai-sandbox` (default `false`).
- When on: the navigation route `/max` resolves to `scenes/posthog-ai/`. When off: it resolves to `scenes/max/` (existing behavior).
- Backend respects the same flag to route conversation creation either to the LangGraph stack or the Task/Run cloud-agent stack.
- The flag is per-user, not per-team, to enable internal dogfooding.
- A second flag `posthog-ai-sandbox-tools-{slug}` per MCP server lets us roll tools out one at a time during Phase 4.

---

## 9. Open questions for the team

Each detail spec lists area-specific questions; this section lists ones that span specs.

1. **Task discriminator.** Are we OK extending the existing Task model with `origin_product: "posthog_ai"` + nullable `repository` + nullable `github_integration`, or do we want a separate model (`ChatTask`)? Cheapest path is the former; cleanest is the latter. *Owner: backend.* Blocks: `02_CORE.md` § 3.
2. **Sandbox lifecycle.** PostHog Code spins up a fresh sandbox per Task. Is that the right model for PostHog AI, or do we want a longer-lived sandbox shared across Tasks for a user (cheaper, but state-leakage risk)? *Owner: infra + AI.* Blocks nothing immediately but affects cost projections.
3. **Permission mode default.** Should PostHog AI run in `bypassPermissions` (no friction) or `acceptEdits` (require user OK on data writes — e.g., creating notebooks)? Today's `DangerousOperationApprovalCard` implies the latter for some ops. *Owner: AI.* Blocks: `02_CORE.md` § 6.
4. **Mode replacement.** What happens to "plan mode" (and `agent_mode` more broadly)? Three candidates in `04_PROMPTS.md` § 4 — pick one. *Owner: AI.*
5. **Telemetry.** Today's per-turn `trace_id` is generated client-side. Do we keep that, or use `runId` (with `_posthog/sdk_session` for finer granularity)? Affects every LLM Analytics dashboard that filters by `trace_id`. *Owner: AI + LLM Analytics.*
6. **Streaming render granularity.** `_posthog/agent_message_chunk` arrives every few tokens; `agent_message` arrives coalesced. The desktop renders chunks live. The current Max also streams. Confirm we want token-level streaming in the new UI (it has a perceptible latency benefit). *Owner: AI.*
7. **Mobile / non-Electron clients.** The Twig spec emphasizes the cloud architecture is web-friendly. We don't have a PostHog mobile client today, but: do we want `posthog-ai` to be reachable from non-React contexts (e.g., embedded in product onboarding)? If yes, the logic surface should be more isolated. *Owner: product.*

---

## 10. Glossary

| Term | Definition |
|---|---|
| **ACP** | Agent Connection Protocol. NDJSON-framed JSON-RPC used between the agent-server and the underlying coding agent (Claude Code, Codex). The wire format the agent-server *taps* and broadcasts as PostHog SSE. |
| **Sandbox** | Ephemeral execution environment (container) running `@posthog/agent` + the actual model. Provisioned per Run by PostHog cloud. |
| **agent-server** | The HTTP server (`Twig/packages/agent/src/server/agent-server.ts`) running *inside* the sandbox. Frontend never talks to it directly — only through PostHog cloud's relay. |
| **MCP** | Model Context Protocol. The standard for exposing tools / resources to an agent. We expose PostHog data tools as MCP servers the sandbox connects to. |
| **Task** | A unit of work in cloud agents (Twig spec § 2.3). For PostHog AI, one Task = one chat. |
| **Run** | A single execution of a Task. New Run = new sandbox session. For PostHog AI, "resume after terminal" creates a new Run with `state.resume_from_run_id`. |
| **Permission mode** | `default | acceptEdits | plan | bypassPermissions | auto | read-only | full-access`. Set in `state.initial_permission_mode`; gates `permission_request` flow. |
| **`_posthog/...` notification** | Custom ACP notification namespace used by the agent-server (Twig spec § 10.8). Examples: `_posthog/run_started`, `_posthog/turn_complete`, `_posthog/git_checkpoint`. |
| **systemPrompt** | The composed string passed to the model via `clientConnection.newSession({ _meta: { systemPrompt } })`. For PostHog AI this is the pre-interpolated `ee/hogai/chat_agent/prompts/` content. |

---

## 11. Out of scope (intentional non-goals)

- **Local↔cloud handoff** (Twig spec § 11). PostHog AI doesn't have a "local" mode.
- **GitHub integration / PR creation.** Use `--createPr=false` and "No Repository Mode".
- **Sandbox environment CRUD UI.** Project-level setting at most; not surfaced in PostHog AI chat.
- **Re-implementing `MaxTool.tsx` deprecation.** Just delete it after Phase 5.
- **Conversation export / sharing.** Not part of this migration.
- **Cross-tab session continuation.** The existing `tabAwareScene` integration carries over via the new scene; no transport-level work.

---

## 12. Reading order

If you're an engineer picking up a slice:

- **Backend / Django.** → `04_PROMPTS.md` first, then `01_CONTEXT.md` § 5 (server-side resolution of dynamic context), then `02_CORE.md` § 3 (Task model extension).
- **Frontend transport.** → `02_CORE.md`, then `01_CONTEXT.md`.
- **Frontend UI / message rendering.** → `03_RICH_UI.md`, then `02_CORE.md` § 5 (where the events come from).
- **Prompt engineering / AI side.** → `04_PROMPTS.md`.
