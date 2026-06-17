# Sandbox conversation API → tasks-API migration (resolve-then-drive)

> **Source:** sandbox-API design thread (conversation-optional / demote-Conversation) · **Locus:** backend — conversation viewset + products/tasks relay; frontend — `sandboxStreamLogic`
> **Effort:** L · **Priority:** Medium-high (lets the PostHog AI renderer drive any product's task/run; precondition for retiring the LangGraph runtime cleanly) · **Blocks rollout:** No
> **Joins:** Consumes [G10](./G10-prewarming-on-tasks-api.md)'s `warm` action as the conversation prewarm backend. Preserves and relocates [G4](./G4-legacy-history-conversion.md)'s LangGraph→sandbox conversion. Leaves [G8](./G8-refresh-session-relay-allowlist.md)'s `refresh_mcp` at the conversation layer. Builds on [G3](./G3-conversation-serializer-query-cost.md)'s `latest_run` subquery.

> Line refs reflect the codebase as researched on 2026-06-17. Refs in `ee/api/conversation.py` and `frontend/src/scenes/max/sandboxStreamLogic.ts` were opened in place; refs marked `(mapping)` come from a cross-file survey and should be re-verified on implementation.

## Problem

The PostHog AI sandbox renderer — `sandboxStreamLogic` plus the tool cards, permission cards, ACP-frame parsing, and reconnect resilience — is the genuinely reusable asset of the sandbox work. But it is keyed to a **Conversation**, and three forces now pull against that coupling:

1. **Tasks and runs are created by other products** (PostHog Code, Signals, Slack) that never mint a Conversation. To render their runs with the PostHog AI frontend, the renderer must be drivable by `(task, run)` alone.
2. **Conversation is a LangGraph-era artifact on its way out.** The plan is to keep both runtimes (LangGraph + sandbox) during a transition and then migrate fully to sandboxes. For the sandbox runtime, the Conversation row is already nearly vestigial — almost every live field is duplicated on `Task`/`TaskRun` or exists only for LangGraph (see the disposition table below).
3. **The write path is asymmetric.** Reads already go straight to the tasks API (`runs/{run}/stream/`, `runs/{run}/logs/`); only writes detour through `/conversations`, which accretes sandbox knowledge onto a viewset that also serves LangGraph.

Goal: make the renderer drive `(task, run)` generically, move the operational control plane onto the generic tasks API, and shrink the conversations API to the **irreducible** conversation responsibilities — identity, first-run Task creation, and the **legacy LangGraph→sandbox conversion** — without breaking runtime coexistence. The end state is a renderer that never moves when LangGraph is finally deleted, and a Conversation that has been **demoted** to a removable shim, not abstracted into a durable layer.

## Current behavior (verified)

### Two write paths reach the sandbox

**Path A — the generic tasks relay** (`products/tasks/backend/api.py`): `POST /api/.../tasks/{task}/runs/{run}/command/` (`:2322`). A JSON-RPC pass-through gated by `TaskRunCommandRequestSerializer.ALLOWED_METHODS = ["user_message", "cancel", "close", "permission_response", "set_config_option"]` (`products/tasks/backend/serializers.py:1400`, _per G8_), scope `task:write`. `user_message` is special-cased to signal Temporal (`signal_task_followup_message`, returns `{queued: true}`); the rest are proxied verbatim to the sandbox with a minted RS256 connection JWT + SSRF check. **PostHog Code already drives the sandbox entirely through Path A.**

**Path B — the conversation layer** (`ee/api/conversation.py`): the sandbox-runtime actions delegate in-process (no HTTP-to-self) to the products/tasks services:

- `create` (`:429`) — unified endpoint; sandbox branch at `:542-551` calls `_route_sandbox_message` (`:739`) → `MessageRoutingService(conversation, user).handle(...)` (`:748`, _mapping_).
- `sandbox` (`:724`) — non-streaming follow-up routing → `_route_sandbox_message`.
- `cancel` (`:819`) — sandbox branch (`:823-845`) → `MessageRoutingService.cancel()`; LangGraph branch (`:850-863`) → `AgentExecutor.cancel_workflow()`.
- `permission` (`:874`) — resolves `conversation.current_run` (`:890`), mints a connection token (`:908`), → `send_permission_response(...)` (`agent_command.py:271`, _mapping_).
- `prewarm` (`:782`) — POST/DELETE → `MessageRoutingService.prewarm()` / `prewarm_release()`.

### Reads already bypass both paths

`frontend/src/scenes/max/sandboxStreamLogic.ts` opens its `EventSource` directly against `/api/projects/${projectId}/tasks/${taskId}/runs/${runId}/stream/` (`:856`) and replays history via `api.tasks.runs.getLogEntries` → the `logs/` endpoint (`:805`). The conversation viewset is never in the read path.

### The three conversation couplings in the renderer

Everything else in `sandboxStreamLogic` already runs on `(taskId, runId)` (`cache.activeRun`, `bootstrapRun` at `:783`, `openSseForRun` at `:836`). The only ties to a conversation are:

1. **The logic key** — `key((props) => props.conversationId)` (`:394`).
2. **The permission write** — `api.conversations.permission(...)` in `autoApprovePermissionRequest` (`:1018`) and `respondToPermission` (`:1056`). The _only_ mutation this logic issues. Message-send / prewarm / cancel live in the parent `maxThreadLogic`, not here.
3. **Telemetry** — `conversation_id: props.conversationId` on every capture (`:1008`, `:1039`, `:1102`, `:1120`, `:1186`, `:1418`); each already also carries `run_id`/`task_id`.

### The legacy conversion

A reopened LangGraph thread converts to sandbox on its first new message (`ee/api/conversation.py:497-524`):

- `convert_to_acp` is computed (`:498-505`): not new, `agent_runtime == LANGGRAPH`, `task_id is None`, idle, has message, behind the `phai-sandbox-mode` flag.
- `resumed_context = ContextService().abuild_resumed_legacy_context(conversation, team, user)` (`:508`) reads the current LangGraph window into a one-time resumed-context block; failure → `None`, never blocks (`:511-515`).
- The message routes through the sandbox path with `convert_to_acp=True` (`:549-551`), which flips `agent_runtime` to `SANDBOX` and links the Task atomically inside `MessageRoutingService.handle`.

### History retrieval is already conversation-free

`Conversation.messages_json` is **not** written or read on the sandbox path. `ConversationSerializer.get_messages` (`ee/hogai/api/serializers.py:181`, _mapping_) returns `[]` for born-sandbox runtime; the `agent_runtime` field (`:165`) tells the client which history source to use; `ConversationTaskSerializer` exposes `task.id` + `latest_run` (`:122`, the G3 subquery). The frontend reads history from `runs/{run}/logs/` (`api.py:2252`), which walks the resume chain server-side via `TaskRun.get_resume_chain()` (`models.py:808`).

### The frontend API surface

`api.conversations.*` and `api.tasks.runs.*` are **handwritten** wrappers over `ApiRequest` (`frontend/src/lib/api.ts:6636-6793` and `:5077-5145`). There is **no `runs.command` wrapper yet**. A generated Orval tasks client exists at `products/tasks/frontend/generated/api.ts` but `api.ts` does not consume it.

### For the sandbox runtime, Conversation is nearly vestigial

| Conversation responsibility (sandbox runtime)                              | Disposition                                                                   |
| -------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| Run/resume chain, logs, status, state                                      | Already on `Task`/`TaskRun` — the primitive                                   |
| `title`                                                                    | `Task.title` exists — move there                                              |
| `user` / `team`                                                            | `Task.created_by` / `team_id`                                                 |
| `type`, origin                                                             | `Task.origin_product` (needs `POSTHOG_AI`, see G1/G10)                        |
| `agent_runtime` flag                                                       | Pure coexistence artifact — dies with LangGraph                               |
| `messages_json`, `approval_decisions`, `sandbox_task_id`, `sandbox_run_id` | Already dead/legacy on the sandbox path — delete with LangGraph               |
| Attached-context wrapping, prewarm, `refresh_mcp`                          | Sandbox lifecycle — belongs on the Task/run control plane                     |
| First-message Task creation, Max listing/title, **legacy conversion**      | The only genuinely conversation-flavored glue worth keeping during transition |

## Approach

**Resolve-then-drive.** The conversations API for sandboxes becomes a _session opener_ that returns a `(task, run)` handle and owns only what the tasks API structurally cannot — identity, first-run creation, and legacy conversion. Everything operational moves onto the generic tasks `(task, run)` spine the renderer already reads from.

### 1. One smart conversation endpoint: `open`

Collapse `create`'s sandbox branch + `sandbox` + `prewarm` into a single idempotent endpoint backed by a `SandboxSession` service (a formalization of today's `MessageRoutingService`, which already extends `BaseSandboxService`):

```text
POST /api/.../conversations/{id}/open
body: { content?: string | null, trace_id, attached_context? }
   content present  → first-message / follow-up (process the turn)
   content null     → warm (boot + idle; delegates to G10's warm_run)
→ { task_id, run_id, run_status, agent_runtime: 'sandbox', just_created_run, converted }

SandboxSession(conversation, user).open(content, attached_context):
  1. ensure conversation row (create on first id; stamp title from first message → also set Task.title)
  2. classify runtime:
       CONVERT ⟸ runtime==LANGGRAPH ∧ task_id is None ∧ idle ∧ has_content ∧ flag
                 resumed_context = ContextService.abuild_resumed_legacy_context(conv, team, user)
  3. route via tasks SERVICES in-process (no HTTP-to-self):
       task_id is None           → Task.create_and_run(origin_product=POSTHOG_AI,
                                       extra_state={initial_context: resumed_context, ...})
                                    ∧ conversation.agent_runtime = SANDBOX ∧ link task   ← conversion completes atomically
       content is null           → warm_run(task, user=...)                              ← G10 (idempotent, quota, caps)
       current_run in {queued,in_progress} → signal_task_followup_message(run, wrap(content, attached_context))
       current_run terminal      → task.create_run(extra_state={resume_from_run_id: current_run.id, ...})
                                    + execute_task_processing_workflow(...)
  4. return handle
```

**The conversion is preserved exactly** — it is the `CONVERT` branch feeding `resumed_context` into the `task_id is None` create path, where the runtime flip + Task link already happen atomically (today's `conversation.py:497-551` → `MessageRoutingService.handle`). It **cannot** move to the tasks API: it reads the LangGraph checkpoint and mutates `conversation.agent_runtime`, both conversation/LangGraph-internal. This is the irreducible conversation responsibility.

### 2. Operational control plane → generic tasks relay

The three opaque control verbs are already relay-legal pass-throughs; move them off the conversation viewset:

```text
cancel / permission_response / close → POST /api/.../tasks/{task}/runs/{run}/command/ { method, params }
```

Reads (`stream/`, `logs/`) are already there. So the sandbox operational surface becomes entirely generic tasks API; the conversation keeps only `open`, `refresh_mcp` (G8), and identity CRUD.

### 3. Renderer keyed on the task, command transport injected

`sandboxStreamLogic` keys on `taskId` and takes `conversationId` as an optional telemetry tag. Its one write — the permission POST — swaps for an injected **command transport**:

- **Generic relay transport** → `runs/{run}/command/`. Works with zero conversation; this is what other products use.
- **Conversation transport** → kept only if the server-side current-run retargeting is required (see decision 1). Otherwise the relay transport serves PostHog AI too.

`maxThreadLogic` supplies the transport and the `{taskId, runId}` (from `open`'s response). A generic task viewer (other products) supplies the relay transport and `{taskId, runId}` resolved from the tasks API (`Task.latest_run` / `runs.list`), with no conversation at all.

### 4. What stays, frozen: the LangGraph path

`create`'s streaming SSE branch, `cancel`'s LangGraph branch, `append_message`, and the message queue stay exactly as-is — frozen legacy. When LangGraph retires, deleting them + the `CONVERT` pre-step + `agent_runtime` collapses `open` to "create-or-resume a Task," and the Conversation row becomes a pure listing view (or is backfilled into `Task` and dropped).

### Why not a runtime-agnostic abstraction over both runtimes

Rejected. LangGraph is being deleted; unifying it with the sandbox runtime spends effort on a layer with a deletion date. Quarantine LangGraph behind the existing conversation `create`/`stream` path instead, and build the sandbox path on the generic `(task, run)` spine. The Conversation is a **seam for deletion**, not a durable abstraction.

## Implementation steps

1. **Backend — `SandboxSession.open()`** (`products/posthog_ai/backend/message_routing.py`): rename/extend `MessageRoutingService` into the `open(content, attached_context)` state machine above, subsuming `handle`, `prewarm` (→ `warm_run`, G10), and the conversion pre-step. Keep the `SELECT FOR UPDATE` serialization on the Conversation row. `content=null` delegates to G10's `warm_run`.

2. **Backend — conversation viewset slim-down** (`ee/api/conversation.py`):
   - Add `open` action (or repurpose `sandbox`); `create`'s sandbox branch (`:542-551`) delegates to it (no duplicated routing). Return the handle including `converted` and `agent_runtime`.
   - **Remove the sandbox branch from `cancel`** (`:823-845`) and **remove `permission`** (`:874`) once the frontend uses the relay — _or_ keep `permission` as a thin current-run-resolving proxy per decision 1. The LangGraph `cancel` branch stays.
   - `prewarm` POST/DELETE: either fold into `open(content=null)` + relay `cancel` for release, or keep `prewarm` as a thin caller of `warm_run`. Decide with G10 decision 6.
   - Keep `refresh_mcp` (G8), `list`/`retrieve`/`destroy`, the LangGraph `create`/`append_message`/`queue`.
   - Move the `report_user_action` / `permission_responded` captures (`:751-766`, `:918-934`) to where the verbs now live (see decision 2).

3. **Backend — telemetry relocation** (`products/tasks/backend/services/agent_command.py` or the relay action): emit `task_run_cancelled` / `permission_responded` keyed on `task.origin_product == POSTHOG_AI`, so the generic relay stays product-agnostic but PostHog AI's funnels do not lose events. Keep `conversation_id` nullable; add a `surface`/`origin_product` discriminator.

4. **Frontend — renderer decoupling** (`frontend/src/scenes/max/sandboxStreamLogic.ts`):
   - Re-key from `props.conversationId` (`:394`) to `props.taskId`; make `conversationId` an optional prop used only for telemetry tags.
   - Replace the two `api.conversations.permission` calls (`:1018`, `:1056`) with `commandTransport.respondPermission(...)`; define the transport interface `{ respondPermission, cancel, sendMessage? }` (capability-typed — a read-only viewer provides none).
   - Make `conversation_id` optional in every capture; always include `run_id`/`task_id`.

5. **Frontend — generic command wrapper + adopt generated client** (`frontend/src/lib/api.ts`): add the `command` call against `runs/{run}/command/`. Prefer the generated Orval tasks client (`products/tasks/frontend/generated/api.ts`) per `/adopting-generated-api-types` over a new handwritten wrapper; backfill the `runs.command` surface there via `hogli build:openapi`. Wire the relay transport in `maxThreadLogic`; provide a conversation transport only if decision 1 keeps `permission` server-side.

6. **Frontend — generic task viewer entry point** (other products): a thin mount of the renderer with `{taskId, runId}` resolved from the tasks API and the relay transport — no conversation. (Scope this to the first consuming product; the renderer change in step 4 is the prerequisite.)

7. **Generated types:** `hogli build:openapi` after any serializer change; assert no uncommitted generated diff.

## Files to change

| Path                                                                                     | Change                                                                                                                                                    |
| ---------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `products/posthog_ai/backend/message_routing.py`                                         | `MessageRoutingService` → `SandboxSession.open()` state machine; subsume `handle`/`prewarm`/conversion                                                    |
| `ee/api/conversation.py`                                                                 | Add `open`; `create` sandbox branch delegates; remove/slim `cancel` sandbox branch + `permission`; relocate captures; keep LangGraph path + `refresh_mcp` |
| `products/tasks/backend/services/agent_command.py` (or relay action)                     | Per-`origin_product` `task_run_cancelled` / `permission_responded` telemetry                                                                              |
| `frontend/src/scenes/max/sandboxStreamLogic.ts`                                          | Re-key on `taskId`; optional `conversationId`; inject command transport; nullable `conversation_id` in captures                                           |
| `frontend/src/scenes/max/maxThreadLogic.ts` (_mapping_)                                  | Provide `{taskId, runId}` + the command transport; route control verbs to the relay                                                                       |
| `frontend/src/lib/api.ts` / `products/tasks/frontend/generated/*`                        | `runs.command` via the generated tasks client; retire handwritten conversation control wrappers as they are replaced                                      |
| Generated types (`frontend/src/generated/core/*`, `products/tasks/frontend/generated/*`) | Regenerated by `hogli build:openapi`                                                                                                                      |

## Decisions & open questions

1. **Permission/cancel retargeting — relay (client picks the run) vs. conversation (server resolves `current_run`).**
   The conversation `permission` endpoint targets `conversation.current_run` (`:890`) because sandboxes are persistent and a follow-up reply belongs on the successor run after the old one dies. On the relay, the client posts the run it is streaming. **Recommendation: relay transport with a "command the latest run" rule** — the renderer already tracks `cache.activeRun` and re-resolves on SSE drops, so the common case is covered; the reply-arrives-as-sandbox-dies race exists either way. If a server-side guarantee is wanted, keep `permission` as a thin conversation action that resolves `current_run` then calls `send_permission_response` (a middle option). **This is the load-bearing decision** — it determines whether the conversation transport survives at all.

2. **Telemetry — service-layer (keyed on `origin_product`) vs. client-side.**
   **Recommendation: emit from the `agent_command` service layer** for the relayed verbs, keyed on `origin_product`, so the generic relay stays clean and PostHog AI funnels are preserved. Keep `conversation_id` nullable and add a `surface` discriminator so generic-task usage does not pollute PostHog AI funnels.

3. **Auth equivalence.** The conversation actions check `conversation.user == request.user`; the relay checks `task:write` + run ownership. For a 1:1 conversation↔task these are equivalent — **verify** no path lets `task:write` alone reach another user's conversation-backed run before removing the conversation-layer checks.

4. **Logic key migration — `conversationId` → `taskId`.** A Conversation is 1:1 with a Task and the Task spans the resume chain this logic already follows, so `taskId` is the correct stable key. **Confirm** no consumer keys `sandboxStreamLogic` by `conversationId` in a way that a generic viewer (no conversation) cannot satisfy.

5. **Keep minting Conversation rows during coexistence?**
   **Decided (user): yes.** The row unifies Max's listing across both runtimes and avoids a dual-listing UI. Treat it as write-only PostHog AI chrome over a Task, never as a renderer dependency. Deletion later is a backfill (`Conversation.title → Task.title`) + dropping the model.

6. **`open(content=null)` warm vs. a surviving `prewarm` action.** Deferred to [G10](./G10-prewarming-on-tasks-api.md) decision 6.

## Dependencies & sequencing

- **Consumes [G10](./G10-prewarming-on-tasks-api.md):** `open(content=null)` delegates to `warm_run`. G10 can land first and be exercised by today's conversation prewarm; G11 then repoints `open` at it.
- **Preserves [G4](./G4-legacy-history-conversion.md):** the conversion is relocated into `open`, not changed. If G4 chose coexistence (Option A), the conversion path already exists and G11 only moves it.
- **Leaves [G8](./G8-refresh-session-relay-allowlist.md) intact:** `refresh_mcp` stays a conversation action (trust-bearing payload); it does not move to the relay.
- **Builds on [G3](./G3-conversation-serializer-query-cost.md):** the `task` + `latest_run` the renderer bootstraps from is already the prefetch-aware subquery.
- **Internal order:** backend `SandboxSession.open` + viewset slim-down (steps 1–3) are independently shippable and testable behind the existing flag. Frontend decoupling (steps 4–5) follows. The generic viewer (step 6) lands with its first consuming product.

## Testing

- **`SandboxSession.open` (unit):** parameterized over the state machine — first message (Task created, `origin_product=POSTHOG_AI`); in-progress follow-up (signal, no new run); terminal resume (new run with `resume_from_run_id`); `content=null` (delegates to `warm_run`, idempotent); **conversion** (LangGraph + idle + flag → `resumed_context` built, runtime flipped to SANDBOX, Task linked atomically, `converted=true` in the handle); conversion read failure → continues with `resumed_context=None`, never blocks.
- **Viewset (API test):** `open` happy paths + the conversion path return the expected handle; another user's conversation → 403/404; LangGraph `create`/`cancel` paths unchanged (regression lock).
- **Relay control verbs (API test):** `cancel`/`permission_response`/`close` via `runs/{run}/command/` succeed for a PostHog AI run with no conversation involvement; per-`origin_product` telemetry fires; ownership enforced.
- **Frontend (jest):** `sandboxStreamLogic` keyed on `taskId` bootstraps + streams with `conversationId` undefined (the generic-viewer case); the injected transport's `respondPermission` is called (not `api.conversations.permission`); captures omit `conversation_id` cleanly when absent and always carry `run_id`/`task_id`.
- **Coexistence:** a LangGraph conversation still streams via `create`; a converted conversation renders its legacy `messages` thread above the divider _and_ replays sandbox `logs/` (no double-render of human turns — the existing `bootstrapReplay` guard).
- **Type drift:** post-`hogli build:openapi`, no uncommitted generated diff.

## Rollout / flagging

- Reuse the existing PostHog AI sandbox rollout flag for the PostHog AI-facing renderer change; the backend `open` repoint is internal (identical external behavior) and unflagged.
- Gate the **generic task viewer** (step 6) behind its first consuming product's flag.
- Roll the control-verb relay move out behind the sandbox flag; watch the `permission`/`cancel` success and the disconnect rates against the pre-migration baseline (the renderer already captures `sandbox_stream_disconnected`).
- **Telemetry to watch:** permission-reply success rate (relay vs. old conversation path), cancel success, and that PostHog AI funnels are intact after the telemetry relocation (decision 2).

## Effort & risk

**Effort: L.** Backend `open` consolidation + viewset slim-down is M; the frontend transport/key decoupling is M; the generic viewer is S–M but depends on a consuming product. The conversion is relocated, not rewritten, which keeps the riskiest legacy logic stable.

**Risks:**

- **Permission retargeting regression** (decision 1) — the highest-risk behavioral change; mitigate with the "command the latest run" rule + the retargeting test, or keep `permission` server-side.
- **Telemetry gaps** during the relocation — mitigate by landing the service-layer captures (step 3) in the same PR as the verb move, with the funnel-intact test.
- **Coexistence breakage** — a converted thread mis-rendering; mitigate with the coexistence regression tests and by leaving the LangGraph path strictly untouched.
- **Auth divergence** (decision 3) — verify relay ownership ≡ conversation ownership before removing the conversation-layer checks.
