# Backward compatibility audit

The migration ships behind a per-user feature flag (`posthog-ai-sandbox`). Users without the flag must see the existing Max experience **exactly as today** — no behavior change, no missing UI, no regressed scenes. This document enumerates every touchpoint where the new sandbox runtime risks bleeding into the LangGraph runtime and pins the disposition for each.

The guiding principle: **strict additive, never replacement**. New code paths live alongside existing ones, gated by the runtime decision stamped on each conversation. Cleanup (deletions, in-place simplifications) is deferred to a follow-up phase after the flag flips to default-on for everyone.

> This supersedes the deletion / in-place-simplification language in `01_CONTEXT.md`, `03_RICH_UI.md`, and `04_PROMPTS.md` for the rollout window. Those specs describe the *end state* after cleanup; this document describes the *coexistence state* during the soak.

---

## The runtime boundary

```
Conversation.agent_runtime: 'langgraph' | 'sandbox'   ← stamped at conversation create from feature flag
                                                       never re-read on a row that already exists
```

Every place that branches on runtime takes this as input. Once a conversation is created on one runtime, it stays on that runtime for its entire life. Flipping the flag does not migrate existing conversations.

This guarantees: a user on the LangGraph runtime never crosses a code path the sandbox runtime touches, and vice versa.

---

## Touchpoint audit

Each row classifies the touchpoint by risk and pins the coexistence disposition.

| # | Surface | Risk if shared | Disposition |
|---|---|---|---|
| 1 | `frontend/src/scenes/max/maxContextLogic.ts` | High — used by every Max user today; `compiledContext` feeds `ui_context` for LangGraph | **Keep untouched.** Continues to produce `MaxUIContext` for LangGraph runtime. |
| 2 | Sandbox context storage | New | **New file** `posthogAIContextLogic.ts` (sibling). Owns `AttachedContext[]` for the sandbox runtime only. |
| 3 | Scene `maxContext` selectors (3 scenes) — dashboard, insight, project-homepage | Medium — return `MaxContextInput[]` today; LangGraph depends on rich shape | **Keep untouched.** Sandbox logic reads the same selectors and projects the rich items down to flat `AttachedContext[]` at consumption time. Zero scene-side edits. |
| 4 | `maxTypes.ts` (`MaxContextInput`, `MaxUIContext`, `createMaxContextHelpers`) | High — heavily imported | **Keep untouched.** Add `AttachedContext` as a new type alongside. |
| 5 | `Context.tsx` chip UI | Medium — shared component | **Branch on runtime.** Render existing chip UI for LangGraph; render new sandbox chips when `agent_runtime === 'sandbox'`. Both branches coexist in the same component. |
| 6 | `frontend/src/scenes/max/MaxTool.tsx` + `useMaxTool.ts` | High — 38 call sites across 17 files including survey, experiments, web analytics, layout chrome | **Keep untouched.** Hook remains functional for LangGraph contextual tools. Sandbox runtime ignores the registered tools (it has only static MCP tools). No call-site edits anywhere. |
| 7 | `maxGlobalLogic.toolMap` reducer | High — feeds LangGraph's `contextual_tools` | **Keep untouched.** Sandbox path doesn't read it. |
| 8 | `max-constants.tsx` `TOOL_DEFINITIONS` / `ToolDefinition` / `ToolRegistration` | Medium — consumed by `MaxTool.tsx` + display formatters | **Keep untouched.** |
| 9 | `maxBillingContextLogic.tsx` | Medium — feeds `billing_context` request field for LangGraph | **Keep untouched.** Sandbox runtime does not call this logic. Backfill plan for billing-aware sandbox behavior is in [`TODO.md`](./TODO.md). |
| 10 | `maxThreadLogic.tsx` request body (`ui_context`, `billing_context`, `contextual_tools`) | High — every LangGraph conversation sends them today | **Send conditionally.** When `agent_runtime === 'sandbox'`, send `attached_context` instead and omit `ui_context` / `billing_context` / `contextual_tools`. When LangGraph, send the same payload as today. Branch is a single `if` in `streamConversation`. |
| 11 | `maxThreadLogic.tsx` SSE event handlers | High — the existing `AssistantEventType.SANDBOX` handler already merges `sandbox-` prefixed messages into the thread (see `maxThreadLogic.tsx:67, 2130, 2145, 2155`) | **Mostly already there.** The sandbox path piggybacks the existing `sandbox` event for ACP frames. Only `permission_request`, terminal `task_run_state`, and explicit `error` need new handlers — they're additive cases in the same event loop. |
| 12 | `Thread.tsx` message dispatch | High — renders the thread for everyone | **Branch on runtime + message origin.** Existing message variants (`AssistantToolCallMessage` with `ui_payload`, etc.) keep rendering as today for LangGraph. For sandbox conversations, an additional dispatch branch consults `mcpToolRegistry` to render MCP tool-call placeholders. Both branches coexist; no existing renderer is touched. |
| 13 | `messages/*.tsx` renderers (`VisualizationArtifactAnswer`, `NotebookArtifactAnswer`, `UIPayloadAnswer`, etc.) | Medium — heavily used by LangGraph today | **Keep untouched.** New thin adapter wrappers live in `messages/adapters/` (new directory) and *call* the existing renderers with props extracted from MCP `rawInput`/output. The originals are reused, not modified. |
| 14 | `UIPayloadAnswer.tsx` | High — current dispatcher for LangGraph `ui_payload.kind` | **Keep its existing dispatch.** Sandbox runtime never goes through `UIPayloadAnswer`; it goes through the new registry path in `Thread.tsx`. No edits to the existing file. |
| 15 | `DangerousOperationApprovalCard.tsx` | High — shared component | **Extend, don't replace.** Accept an optional `variant` prop (`'langgraph' \| 'sandbox-permission' \| 'sandbox-plan'`) that defaults to `'langgraph'` (existing behavior). New variants handle the ACP `permission_request` option-kind enums (`allow_once` / `allow_always` / `reject` / `reject_with_feedback`) and plan-mode approvals. Existing call sites pass nothing → unchanged behavior. |
| 16 | Slash commands (`/init`, `/remember`, `/usage`, `/feedback`, `/ticket`) | Low–Medium — `/init` and `/remember` write to core memory; only meaningful for LangGraph | **Runtime-aware dispatch.** Slash command handler reads `agent_runtime`. For LangGraph: unchanged. For sandbox: `/init` and `/remember` show "Not available in sandbox AI yet" with a link to [`TODO.md`](./TODO.md); `/usage`, `/feedback`, `/ticket` work in both. |
| 17 | Conversation history (`GET /conversations/`) + `ConversationHistory.tsx` | Low — list-of-conversations shape identical; per-conversation message loading diverges by runtime | **Mostly no change** for the conversation-*list* response. The per-conversation *detail* endpoint changes shape per `02_CORE.md` § 4.7: `messages` populated for `langgraph`, empty for `sandbox`. Sandbox conversation history loads via the new `GET /conversations/{id}/log/` endpoint (`02_CORE.md` § 4.6). `maxLogic`'s history-load branch on `agent_runtime` is the only frontend change. |
| 18 | `feedbackPromptLogic` / `FeedbackPrompt.tsx` | Low | **No change.** Orthogonal to runtime. |
| 19 | `TicketPrompt.tsx` / `ticketUtils.ts` | Low | **No change.** |
| 20 | `Intro.tsx`, `MaxChangelog.tsx`, `floatingMaxPositionLogic.tsx` | Low | **No change.** |
| 21 | Tab-aware scene state (`tabAwareScene`) | Medium — per-tab Kea state | **No change.** Both runtimes use the same scene plumbing. |
| 22 | Stories / Storybook (`Max.stories.tsx`) | Low | **No change for LangGraph stories.** Add new stories for sandbox renderers as part of `03_RICH_UI.md` work. |
| 23 | Unit tests (`*.test.ts(x)`) | High — CI gate | **No existing test modified.** New tests added alongside for sandbox-specific logics + adapters. |

---

## Backend touchpoints

| # | Surface | Risk | Disposition |
|---|---|---|---|
| 24 | `Conversation` model schema | Medium — new columns | **Strictly additive.** `agent_runtime` (string, default `'langgraph'`, NOT NULL) and `task_run_id` (nullable UUID FK) added via Django migration. Existing rows automatically default to `langgraph`. No code path that reads `Conversation` today fails on the new columns. |
| 25 | `Conversation.sandbox_task_id` / `Conversation.sandbox_run_id` columns | Medium — already exist as UUIDFields, used by current `executor.py` Redis flow | **`sandbox_task_id` → `sandbox_task` FK (`tasks.Task`, `SET_NULL`); `sandbox_run_id` dropped outright** (current Run is derived, not stored). If `sandbox_task_id` is unused: rename + `SeparateDatabaseAndState` to swap type with the same `db_column`. If still used: add new FK alongside, backfill, drop after soak. See `02_CORE.md` § 2.2. |
| 26 | `POST /api/.../conversations/stream/` endpoint | Critical — every Max user hits this | **Branch on `Conversation.agent_runtime`.** Existing branch (LangGraph) is unchanged. New `'sandbox'` branch invokes the SSE relay. The view-level Python file is touched, but its existing code path is preserved verbatim — only an `if conversation.agent_runtime == 'sandbox': ...` early-return is added near the top. |
| 27 | `POST /api/.../conversations/{id}/queue/` endpoint | Low — LangGraph-only feature today | **Keep working for LangGraph.** Sandbox runtime never calls it. No deprecation during the soak. |
| 28 | LangGraph stack under `ee/hogai/chat_agent/` | Critical — production code path | **Completely untouched.** New SSE relay lives in `ee/hogai/sandbox/` (sibling). No imports across the boundary. |
| 29 | Existing `ee/hogai/sandbox/executor.py` Redis relay | Medium — already in code | **Decision needed.** If unused in prod, replace its internals with the new direct upstream-SSE relay. If used, leave alone and add new `sse_relay.py` next to it. Confirm by grep + flag check before proceeding. |
| 30 | `ui_context` / `billing_context` / `contextual_tools` request fields | Critical — every existing request sends them | **Adapter ignores them.** The fields stay in the request schema; the LangGraph branch reads them; the sandbox branch silently ignores them. Frontend sends them or not based on runtime (see #10). |
| 31 | `core_memory` reads (LangGraph) | Medium — feeds the existing AGENT_CORE_MEMORY_PROMPT | **Keep working for LangGraph.** The sandbox `build_posthog_ai_system_prompt` doesn't call them. |
| 32 | `posthog_corememory` model + `/remember` write path | Low — separate concern | **Keep functional.** `/remember` writes still land in `posthog_corememory` for LangGraph users. Sandbox users see a "not available" message (#16). |
| 33 | Telemetry / LLM Analytics event shapes | High — dashboards filter on event types and `trace_id` | **Mirror existing shapes from the SSE relay where possible.** The sandbox path emits the same `PROMPT_SENT`, `TASK_RUN_CANCELLED`, `PERMISSION_RESPONDED` analytics events the LangGraph path emits, with `execution_type: 'sandbox'` added as a new property (no breaking change to existing filters). |
| 34 | MCP servers (`services/mcp/`) | Low — additive | **Add `posthog-data`, `posthog-notebook` MCP servers alongside existing services.** No existing MCP server modified. |
| 35 | Generated OpenAPI types / `frontend/src/generated/core/` | Medium — auto-generated | **Re-run `hogli build:openapi`** after Conversation model migration. Type additions only; no existing types removed during soak. |
| 36 | DRF serializers for Conversation | Medium — adding nullable fields | **Add `agent_runtime` and `task_run_id` to the response serializer.** Existing fields stay; new ones are optional/nullable on read so old clients ignore them gracefully. |
| 37 | `Conversation` SDK methods (`api.conversations.*` in `lib/api.ts`) | Medium — frontend uses them | **Optional `attached_context` field added to request types.** Existing callers ignore it. |
| 38 | LLM Analytics trace correlation | Medium — `trace_id` per turn | **Generate `trace_id` from the SSE relay** the same way the LangGraph view does today. Same dashboards. |
| 39 | Permission system / IDOR coverage | Low — Conversation already team-scoped | **No new model, no IDOR risk.** Both runtimes operate over the same `Conversation` row. |
| 40 | Activity logging | Low | **No change.** LangGraph events still log; sandbox events log additively with `execution_type: 'sandbox'`. |

---

## Code layout (additive, no in-place edits)

```
posthog/
  ee/hogai/
    chat_agent/                       ← UNTOUCHED (LangGraph runtime)
      prompts/
      toolkit.py
      ...
    sandbox/                          ← NEW or LIGHTLY-USED (sandbox runtime)
      __init__.py                       (existing)
      context_wrapper.py                ← NEW (per 01_CONTEXT.md § 4)
      system_prompt.py                  ← NEW (per 04_PROMPTS.md § 6)
      sse_relay.py                      ← NEW (UpstreamSseRelay — ACP passthrough)
      posthog_api.py                    ← NEW (typed HTTP client for /api/projects/.../tasks/*)
      bootstrap.py                      ← NEW (REST + SSE merge + content-dedup)
      executor.py                       ← CONFIRM usage, then either repurpose or leave alone
      mapping.py                        ← existing
      types.py                          ← existing — additive types only

  services/mcp/                       ← UNTOUCHED for existing tools
    servers/
      posthog-data/                   ← NEW (per 04_PROMPTS.md § 5)
      posthog-notebook/               ← NEW

  frontend/src/scenes/max/            ← MOSTLY UNTOUCHED
    maxLogic.tsx                        unchanged
    maxThreadLogic.tsx                  branch on runtime in 2 places (request body, +4 SSE event handlers — all additive)
    maxGlobalLogic.tsx                  unchanged
    maxContextLogic.ts                  UNCHANGED
    maxBillingContextLogic.tsx          UNCHANGED
    maxTypes.ts                         AttachedContext appended; existing types kept
    MaxTool.tsx                         UNCHANGED
    useMaxTool.ts                       UNCHANGED
    max-constants.tsx                   UNCHANGED
    Thread.tsx                          one additional dispatch branch (additive)
    Context.tsx                         branch on runtime to render either chip set (additive)
    DangerousOperationApprovalCard.tsx  optional `variant` prop (additive, defaults preserved)
    slash-commands.tsx                  runtime-aware disposition for /init, /remember (additive)
    messages/                           UNCHANGED renderers
      adapters/                         ← NEW directory — thin wrappers around existing renderers
    posthogAIContextLogic.ts           ← NEW
    posthogAIContextLogicType.ts       ← generated
    sandboxStreamLogic.ts               ← NEW (ACP frame parser → ToolInvocation / ThreadItem)
    sandboxStreamLogicType.ts           ← generated
    mcpToolRegistry.tsx                 ← NEW

  frontend/src/scenes/dashboard/      ← UNTOUCHED (existing maxContext selector reused)
  frontend/src/scenes/insights/       ← UNTOUCHED
  frontend/src/scenes/project-homepage/ ← UNTOUCHED
```

---

## Test guardrails

CI gates the soak in three places:

1. **All existing `scenes/max/` tests must keep passing.** A single failing assertion in `maxContextLogic.test.ts`, `maxLogic.test.ts`, etc. blocks the PR. Do not modify existing tests.
2. **A new lint rule** (or convention check) flags any deletion or in-place modification of files in `frontend/src/scenes/max/` not on the explicit allow-list above. Catches drive-by simplifications.
3. **Storybook visual review** must show no diff for stories rendering LangGraph conversations.

---

## What is explicitly *not* deferred

Some things still need to land during the migration, even if technically modifications to shared code:

- **Conversation model migration** (#24). Adding the column is non-negotiable. Default value preserves existing behavior.
- **`maxThreadLogic.tsx` request body branch** (#10). One `if` statement, mechanically safe.
- **`maxThreadLogic.tsx` SSE handlers for `permission_request` / terminal status / errors** (#11). Additive cases in the existing event loop.
- **`Thread.tsx` dispatch branch** (#12). One additional case at the top of the renderer switch.
- **`Context.tsx` runtime branch** (#5). Adds a sibling chip-render path; existing rendering unchanged.
- **`DangerousOperationApprovalCard.tsx` optional `variant` prop** (#15). Default value preserves current behavior.
- **`slash-commands.tsx` runtime check** (#16). Adds a runtime-conditional message for `/init` and `/remember`.

Each of these has a default-preserving fallback so users without the flag see no behavior change.

---

## Cleanup roadmap (deferred until after default-on)

Once the `posthog-ai-sandbox` flag flips to default-on for everyone *and* a soak period has confirmed parity, a follow-up phase can:

- Delete `maxBillingContextLogic.tsx` if the billing backfill (per `TODO.md`) lands as an MCP tool.
- Delete `MaxTool.tsx` / `useMaxTool.ts` and migrate the 38 call sites.
- Collapse the two context logics into one.
- Drop `MaxContextInput` / `MaxUIContext` / `createMaxContextHelpers` from `maxTypes.ts`.
- Remove the LangGraph branch from `/conversations/stream/`, delete `ee/hogai/chat_agent/`.
- Delete the LangGraph-only request-body fields (`ui_context`, `billing_context`, `contextual_tools`) from the schema.

These are tracked separately and **not in scope for this migration**.

---

## Open questions

1. **`ee/hogai/sandbox/executor.py` repurpose vs leave.** Need a grep + git log read of how `executor.py` is invoked today. If it's behind an already-shipped flag with active users, we add `sse_relay.py` next to it rather than replace.
2. **Are `Conversation.sandbox_task_id` / `sandbox_run_id` columns already in use?** Determines whether the FK conversion is in-place (rename + `SeparateDatabaseAndState`) or alongside (add new columns + backfill + drop). Same investigation as #1.
3. **Runtime badge in `ConversationHistory.tsx`.** Optional UI cue ("Sandbox" pill on sandbox conversations). Decide whether internal-only or shippable to all users.
4. **`/remember` no-op messaging.** Should we hide the command entirely from the autocomplete for sandbox users, or show it with a disabled state and explanation tooltip? Bias toward the latter — discoverability.
5. **Migration assumption.** The migration only touches `Conversation` (additive columns). Confirm no downstream warehouse export or analytics pipeline breaks on the new columns being present.
