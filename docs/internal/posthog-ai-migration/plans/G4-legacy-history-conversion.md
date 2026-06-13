# Legacy LangGraph conversation history → sandbox conversion (decision gate)

> **Source:** outstanding*items.md § 4 (Item 4) · **Locus:** decision gate + (conditional) converter
> **Effort:** Option A (coexistence) = ~0 (no code) · Option B (convert) = L · **Priority:** Medium-high (decision-gated) · **Blocks rollout:** Depends on the coexistence decision
> **Joins:** Standalone. Nothing else folds in. It is a decision plan first and an implementation plan second — the implementation (Option B) only exists if the decision goes against the recommended Option A. It touches the same `Conversation.agent_runtime` field that the whole sandbox migration hinges on, but no sibling plan reads or writes that field, so there is no shared locus to coordinate. Cross-references to G3 (serializer query cost) and G5/G6 (tool-card / notification rendering) are noted under \_Dependencies* because the converter's output lands in those exact rendering paths — but this plan does not modify them.

## Problem

PostHog AI (Max) is being migrated from the in-process LangGraph runtime to a sandbox runtime (an external agent server in a `products/tasks` sandbox, streaming the ACP wire protocol over SSE). Each `Conversation` is permanently bound to one runtime: `agent_runtime` is stamped once at create time and **never re-evaluated** (`products/posthog_ai/backend/models/assistant.py:130-136`, and the stamping site `ee/api/conversation.py:455-468`).

The two runtimes store conversation history in completely different places:

- **LangGraph** persists turn state as LangGraph checkpoints in Postgres (`ee_conversationcheckpoint*` tables, written by `DjangoCheckpointer`). History is rehydrated by replaying the checkpoint into the graph state and reading `state.messages` — a list of **PostHog schema message objects** (`HumanMessage`, `AssistantMessage`, `AssistantToolCallMessage`, `VisualizationMessage`, …), not raw LangChain messages (see _Current behavior_ for the correction).
- **Sandbox** persists history as an **ACP NDJSON log in S3**, one file per `TaskRun` (`run_<id>.jsonl`). The conversation serializer returns `messages: []` for sandbox conversations and the frontend loads the real history from the `products/tasks` logs endpoint instead.

Because of the one-runtime-for-life binding, **there is no path to move an existing LangGraph thread onto the sandbox runtime without losing its history.** Concretely:

1. A user who has an in-flight LangGraph thread can never continue it on the sandbox runtime. If we flip them to sandbox (e.g. by enabling the `phai-sandbox-mode` flag for them), only _new_ threads become sandbox; old threads keep working on LangGraph.
2. We **cannot retire the LangGraph runtime** while any historical thread a user might reopen still lives only in checkpoints — deleting LangGraph would orphan that history.

There is **no converter** today that reads a LangGraph thread's message history and rehydrates it as a sandbox conversation (a new `Task` + `TaskRun` + a seeded S3 ACP log, with `agent_runtime` flipped to `sandbox`). Whether we need to build one is a **product decision**, not a foregone conclusion — and that decision is the entire point of this plan.

## Current behavior (verified)

All line numbers below were opened and confirmed on 2026-06-13. Corrections vs. the source doc are called out inline.

### Runtime binding

- `Conversation.agent_runtime` field — `products/posthog_ai/backend/models/assistant.py:130-136` (CharField, choices `langgraph`/`sandbox`, default `langgraph`, `db_index=True`). Help text: _"Stamped at create time from the phai-sandbox-mode flag; never re-evaluated."_ **Cited at ~:130-136 — exact.**
- `Conversation.task` FK → `tasks.Task` — `assistant.py:137-145` (`on_delete=SET_NULL`, `related_name="+"`). One Task per sandbox conversation for its whole life.
- `Conversation.current_run` property — `assistant.py:147-152` → `task.latest_run`. (The doc cited :147-152; **exact**.)
- Stamping at create — `ee/api/conversation.py:455-468`: `agent_runtime = SANDBOX if has_sandbox_mode_feature_flag(team, user) else LANGGRAPH`, passed into `Conversation.objects.create(...)`. The flag function is `has_sandbox_mode_feature_flag` at `ee/hogai/utils/feature_flags.py:106-108` (reads the `phai-sandbox-mode` flag). _(Not cited in the doc; located here for the decision.)_

### LangGraph history read path

- `DjangoCheckpointer` — `ee/hogai/django_checkpoint/checkpointer.py`. It reads/writes the `ee_conversationcheckpoint`, `ee_conversationcheckpointblob`, `ee_conversationcheckpointwrite` rows and reconstructs the graph state. The graph state's `messages` channel is what history-load consumes. **Cited path — exact** (the doc cited "→ state.messages"; the actual hop is `graph.aget_state(...).values` → `state_class.model_validate(...)` → `state.messages`, done in the serializer, not in the checkpointer — see below).
- `get_messages` serializer method — `ee/hogai/api/serializers.py:101-125`. **Cited at ~:101-125 — exact.**
  - Sandbox early-return `messages: []` — `serializers.py:104-105`. **Cited at ~:104-105 — exact.**
  - For LangGraph it calls `_get_cached_state` → `_aget_state` (`serializers.py:190-257`), which compiles the graph (`graph.aget_state({"configurable": {"thread_id": ..., "checkpoint_ns": ""}})`), validates `snapshot.values` into the typed state, and the serializer then enriches and `model_dump()`s `list(state.messages)`.
  - **Correction to the doc's framing:** the doc (`outstanding_items.md:107`) says LangGraph history is _"`state.messages` (LangChain message objects)."_ It is **not** LangChain message objects. `state.messages` is a `Sequence[AssistantMessageUnion]` of **PostHog schema models** (`ee/hogai/utils/types/base.py:70`, union of `HumanMessage`, `AIMessageUnion`, `NotebookUpdateMessage`, `ContextMessage`; `AIMessageUnion` is at `base.py:59-69` and has **nine** members — `AssistantMessage`, `VisualizationMessage`, `ArtifactRefMessage`, `FailureMessage`, `AssistantToolCallMessage`, `MultiVisualizationMessage`, `ReasoningMessage`, `PlanningMessage`, `TaskExecutionMessage` — so the mapper must handle the full set, not just the four the table enumerates; the un-tabled members reduce to text or are dropped). This matters for the converter: tool calls are already first-class typed objects (`AssistantMessage.tool_calls: list[AssistantToolCall]`, `posthog/schema.py:11004`; `AssistantToolCallMessage.tool_call_id`/`content`/`ui_payload`, `posthog/schema.py:832-848`), not opaque LangChain blobs. The mapping is therefore _more_ tractable than the doc implies — but still lossy onto the ACP card model.

### Sandbox history read path

- The frontend bootstraps from the `logs/` endpoint, not from the serializer. `sandboxStreamLogic.bootstrapRun` (`frontend/src/scenes/max/sandboxStreamLogic.ts:583-628`) calls `api.tasks.runs.getLogEntries(taskId, runId)`, filters to notification frames, and replays each through `ingestAcpFrame` to rebuild the rendered history (with `cache.bootstrapReplay = true` so replayed permission requests don't re-fire telemetry). **The doc cited the bootstrap at `sandboxStreamLogic.ts:583-613, 896-913` for the § 2.2 item — confirmed present.**
- Logs endpoint — `products/tasks/backend/api.py:2306-2325` (`@action url_path="logs"`, `logs()` method). It walks `task_run.get_resume_chain()` and concatenates each run's S3 log via `object_storage.read(run.log_url, ...)`, returning `application/jsonl`. **Cited at ~:2306-2325 — exact.**
- S3 log location — `TaskRun.log_url` = `{tasks_folder}/logs/team_{team_id}/task_{task_id}/run_{id}.jsonl` (`products/tasks/backend/models.py:785-787`).
- Appending to the log — `TaskRun.append_log(entries)` (`products/tasks/backend/models.py:861-890`): drops `agent_message_chunk` frames, reads existing S3 content, appends NDJSON lines, writes back, tags new files with a 30-day TTL. **This is the exact seam a converter would use to seed a synthetic log.**

### The wire frames the frontend actually renders

The converter's output must be made of frames the frontend already knows how to ingest. From `frontend/src/scenes/max/types/sandboxWireTypes.ts` (**corrected path** — the source doc and several § references write `frontend/src/scenes/max/sandboxWireTypes.ts`; the real file is under `types/`):

- `_posthog/user_message` notification — params `{ content, _meta }` (`sandboxWireTypes.ts:224,323`; Python mirror `products/posthog_ai/backend/wire_types.py:66-79`, `METHOD_USER_MESSAGE = "_posthog/user_message"`, `UserMessageParams` TypedDict). **Doc cited wire_types `:66-79` — exact.** This is the only "user turn" frame, and it's exactly what `message_routing._log_user_message` writes today (`products/posthog_ai/backend/message_routing.py:555-571`).
- `session/update` notifications carrying a `SessionUpdateBody` (`sandboxWireTypes.ts:107-178`):
  - `agent_message` / `agent_message_chunk` — assistant text (`{ messageId?, content?: { text }, text? }`).
  - `tool_call` — `{ toolCallId?, serverName?, toolName?, title?, kind?, status?, rawInput?, input?, locations?, content? }`.
  - `tool_call_update` — `{ toolCallId?, status?, rawOutput?, error?, content?, _meta? }`.
  - `current_mode_update` — mode badge.
- Note: `append_log` strips `agent_message_chunk` frames (`models.py:863`), so a converter must emit **`agent_message`** (the non-chunk form), not chunks, for assistant text.

### Migration 0004 (column shape confirmed)

`products/posthog_ai/backend/migrations/0004_conversation_agent_runtime_conversation_task_and_more.py` (generated 2026-06-09). It adds exactly two columns and re-alters two deprecated ones:

- `AddField conversation.agent_runtime` — `CharField(max_length=16, choices=[("langgraph","LangGraph"),("sandbox","Sandbox")], db_index=True, default="langgraph")`.
- `AddField conversation.task` — `ForeignKey(to="tasks.task", null=True, blank=True, on_delete=SET_NULL, related_name="+")`.
- `AlterField` on the deprecated `sandbox_run_id` / `sandbox_task_id` UUID fields (now help-texted "Deprecated").

So **flipping a conversation to sandbox requires only: set `agent_runtime="sandbox"` and set `task=<new Task>`.** No new column is needed — the existing schema already supports a converted conversation. **Correction to the doc:** the doc says migration 0004 is "under `products/posthog_ai/backend/migrations or ee`" — it is in `products/posthog_ai/backend/migrations/`, **not** ee.

### Reference: how a sandbox conversation is created today (the converter's template)

`message_routing.PostHogAIMessageRouter._handle_first_message` (`products/posthog_ai/backend/message_routing.py:331-409`) is the exact shape a converter mirrors, minus the workflow start:

1. `Task.create_and_run(team, title, description, origin_product=POSTHOG_AI, user_id, repository=None, create_pr=False, mode="interactive", start_workflow=False)` — `products/tasks/backend/models.py:309-321` (`create_and_run` has a `start_workflow: bool = True` param at :321; the converter passes `False`).
2. `task_run = task.latest_run`.
3. Build `PostHogAIRunState(...)`, merge into `run_state`, then in a `transaction.atomic()` block save `task_run.state` and link `conversation.task = task` (`message_routing.py:377-381`).
4. **First-message path then starts the workflow** (`execute_task_processing_workflow`, :388-396). **A converter must NOT do this** — there is no live agent turn to run; the run exists only to host the seeded historical log.

## Approach

**Decide before writing any code. Recommended: Option A (coexistence). Build the converter (Option B) only if a named criterion below is met.**

### Option A — coexistence (recommended, ~0 code)

Old threads stay LangGraph and read-only-forever on that runtime; only new threads (created while the user has the sandbox flag) are sandbox. This is the **current behavior** — the `agent_runtime` per-conversation field already supports both runtimes side by side, the serializer already branches on it (`get_messages`, `_aget_state`), and the frontend already renders both. **There is literally nothing to build.** A user with mixed history sees old threads render via the LangGraph `messages` array and new threads render via the S3 ACP logs; both open and replay correctly today.

The only real cost of Option A is **operational, not user-facing**: we keep the LangGraph runtime (graph compilation, `DjangoCheckpointer`, the `ee_conversationcheckpoint*` tables) alive indefinitely to serve read-only history. That is acceptable as long as we are not under pressure to delete LangGraph.

**Recommendation: ship Option A for v1.** Rationale: (a) zero risk and zero work; (b) the conversion is inherently lossy (see Option B) so converting silently degrades a user's own history — worse than leaving it intact on the runtime that produced it; (c) the migration's goal is "new conversations run on the sandbox," which Option A already achieves; (d) retiring LangGraph is a separate, later project with its own cost/benefit, and it does not block flipping users to sandbox.

### Option B — convert on reopen (L, lossy)

Build a converter that, **when a user reopens a LangGraph thread under the sandbox runtime**, reads the thread's `state.messages`, maps each into ACP frames, seeds a synthetic `TaskRun` log in S3, links a new `Task`, and flips `agent_runtime` to `sandbox`. On-demand at reopen (not a bulk backfill) so blast radius is bounded to threads users actually revisit, and a converter bug can't corrupt cold history en masse.

#### Mapping table: PostHog schema message → ACP frame

| Source (`state.messages` item)                                             | Maps to                                                                                         | Fidelity                                                                                                                                                                                                                                                |
| -------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `HumanMessage` (`content: str`)                                            | `_posthog/user_message` notification, `params.content = <text>`                                 | **Clean** — same shape `_log_user_message` already writes.                                                                                                                                                                                              |
| `AssistantMessage` (`content: str`, no `tool_calls`)                       | `session/update` → `agent_message` `{ content: { text } }`                                      | **Clean** — plain assistant text.                                                                                                                                                                                                                       |
| `AssistantMessage.tool_calls[i]` (`AssistantToolCall`)                     | `session/update` → `tool_call` `{ toolCallId, toolName, input }`                                | **Degraded** — name/input survive; live status, `serverName`, MCP server attribution, and any `_meta.claudeCode.*` are absent (they were never stored LangGraph-side). Card renders as a completed generic tool call.                                   |
| `AssistantToolCallMessage` (`content: str`, `tool_call_id`, `ui_payload?`) | `session/update` → `tool_call_update` `{ toolCallId, status: "completed", rawOutput: content }` | **Degraded** — output text survives; rich result rendering depends on whether the frontend's extractors can re-derive a card from `rawOutput` alone (see G5). `ui_payload` (contextual-tool frontend payload) has no ACP equivalent and is **dropped**. |
| `VisualizationMessage` / `MultiVisualizationMessage`                       | best-effort `tool_call_update` with the query/answer serialized into `content`/`rawOutput`      | **Lossy** — the LangGraph visualization card (insight preview) does not round-trip to the sandbox visualization extractor; degrades to a text/JSON block unless a dedicated adapter is written.                                                         |
| `NotebookUpdateMessage`                                                    | text summary in an `agent_message`, or dropped                                                  | **Lossy** — no ACP notebook-block frame; the live notebook artifact is gone.                                                                                                                                                                            |
| `ContextMessage` / system/internal messages                                | dropped (filtered by `should_output_assistant_message`, as today)                               | n/a — never surfaced to users anyway.                                                                                                                                                                                                                   |
| Pending approval interrupts (`approval_decisions` + checkpoint interrupts) | **not converted**                                                                               | A converted thread is historical/terminal; there is no live approval to resume. Any pending approval is abandoned by conversion.                                                                                                                        |

**Lossiness contract (must be agreed before building Option B):** human and plain-assistant turns convert faithfully; tool-call _cards_ degrade to name+input / output-text without live status, server attribution, or `_meta`; visualization and notebook artifacts degrade to text. A converted thread is **read-only-historical** — it is not resumable into a live sandbox turn (no snapshot filesystem, no agent state). If the product wants converted threads to be _continuable_, that is strictly more than this converter delivers and should be ruled out of scope explicitly.

#### Where the converter runs

On-demand, server-side, at the retrieve/stream entry point — **not** a Temporal backfill. The natural hook is the streaming/retrieve path in `ee/api/conversation.py` (the same place that stamps `agent_runtime` and routes sandbox vs LangGraph). When a request arrives for a `langgraph` conversation _and_ the requesting user currently has the sandbox flag _and_ Option-B conversion is enabled, run the converter once, idempotently (guard on `conversation.task_id is None and agent_runtime == langgraph`), inside the same request before returning the bootstrap IDs. Subsequent opens see `agent_runtime == sandbox` and take the normal sandbox path.

#### How the synthetic TaskRun + S3 ACP log is seeded

Mirror `_handle_first_message` **without** `execute_task_processing_workflow`:

1. `task = Task.create_and_run(team, title=<conversation.title or first user msg>, description=..., origin_product=POSTHOG_AI, user_id, repository=None, create_pr=False, mode="interactive", start_workflow=False)`.
2. `task_run = task.latest_run`. Mark the run terminal (a converted historical run is not live — set its status to a completed/terminal value so `bootstrapRun` treats it read-only via `isTerminalRunStatus`, `sandboxStreamLogic.ts:621`).
3. Build the ordered list of ACP frames from the mapping table; call `task_run.append_log(frames)` (`models.py:861`). `append_log` writes `run_<id>.jsonl` to S3 and tags it with the 30-day TTL — **flag this: converted history must NOT inherit the 30-day TTL** or it silently disappears (see _Open questions_).
4. In one `transaction.atomic()`: set `conversation.task = task`, `conversation.agent_runtime = SANDBOX`, save both. (Narrow the atomic block to exactly these writes per CLAUDE.md.)
5. The S3 write in step 3 is an irreversible side effect — do it _before_ the atomic flip so a rollback of the flip leaves an orphan log (harmless, GC-able) rather than a flipped conversation pointing at a missing log. Do **not** put the S3 write inside the atomic block.

## Implementation steps

**If Option A (recommended): no implementation.** Close Item 4 as a non-task. Record the decision (and the criteria that would reopen it) in `TODO.md`. Stop here. The remaining steps apply only to Option B.

### Option B steps (ordered)

1. **Agree the lossiness contract and TTL policy** (see _Decisions_). Do not start until product signs off that converted tool/visualization cards degrade to text and converted threads are read-only.
2. **Write the pure mapper** `langgraph_to_acp.py` in `products/posthog_ai/backend/` — a function `messages_to_acp_frames(messages: Sequence[AssistantMessageUnion]) -> list[dict[str, Any]]` implementing the mapping table. Pure, no I/O, fully unit-testable. mypy-strict, module-level imports.
3. **Write the seeder** (a method on a new `LangGraphConversionService` or alongside the message router) that: reads `state.messages` via the existing `_aget_state` machinery (reuse, don't duplicate, the serializer's graph-compile path), calls the mapper, creates the Task + terminal TaskRun (`start_workflow=False`), `append_log`s the frames, and flips `agent_runtime`/`task` in a narrow transaction. Idempotency guard on `task_id is None`.
4. **Wire the on-demand hook** in `ee/api/conversation.py` at the stream/retrieve entry, gated on a feature flag (`phai-convert-legacy-history`) and the user already having `phai-sandbox-mode`. Guard the trigger against double-submission (a second concurrent open must not create a second Task — reuse the conversation row lock pattern from `_handle_terminal_resume`, `message_routing.py:465`).
5. **Decide TTL handling** for converted logs (do not let `append_log`'s 30-day tag silently expire user history — either skip tagging for converted runs or set a long/no TTL; this likely needs a small `append_log` parameter or a sibling write method).
6. **Telemetry**: capture a `phai_legacy_conversion` event (frames in, frames dropped by type, duration) so we can measure fidelity and catch conversions that drop everything.

## Files to change

**Option A:** none. (Optionally: a note in `docs/internal/posthog-ai-migration/TODO.md` recording the decision.)

**Option B:**

| Path                                                                                | Change                                                                                                                                                                                  |
| ----------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `products/posthog_ai/backend/langgraph_to_acp.py` _(new)_                           | Pure mapper `messages_to_acp_frames` implementing the mapping table.                                                                                                                    |
| `products/posthog_ai/backend/message_routing.py` (or a new `conversion_service.py`) | Seeder: read `state.messages`, map, create Task + terminal TaskRun (`start_workflow=False`), `append_log`, flip `agent_runtime`/`task` in a narrow transaction; idempotency + row lock. |
| `ee/api/conversation.py` (~:455-499)                                                | On-demand conversion hook at the stream/retrieve entry, flag-gated, with double-submit guard.                                                                                           |
| `products/tasks/backend/models.py` (`append_log`, ~:861)                            | Optional: parameterize/skip the 30-day TTL tag so converted history isn't auto-expired.                                                                                                 |
| `products/posthog_ai/backend/test/test_langgraph_to_acp.py` _(new)_                 | Parameterized mapper tests (one case per source message type).                                                                                                                          |
| `products/posthog_ai/backend/test/test_message_routing.py`                          | Seeder integration tests (idempotency, terminal status, transaction atomicity, no workflow start).                                                                                      |

## Decisions & open questions

1. **Coexistence (A) vs. convert (B)?** — _Recommend A._ Flip to B **only** if one of these concrete criteria is met: (i) we have a hard deadline to delete the LangGraph runtime (and the `ee_conversationcheckpoint*` tables) — e.g. to remove the LangGraph dependency, reclaim Postgres, or cut graph-compilation cost — _and_ preserving reopenable history is required; (ii) a measured, non-trivial fraction of users actively reopen and want to _continue_ old threads on sandbox features (would also require the read-only limitation to be lifted, which is out of scope here). Absent (i) or (ii), A wins.
2. **Are converted threads continuable or read-only?** — _Recommend read-only._ Making them continuable needs a live sandbox + filesystem snapshot + agent state that simply do not exist for a historical thread; that is a different, much larger project. Rule it out explicitly.
3. **TTL on converted logs.** — Converted history must not inherit `append_log`'s 30-day S3 TTL, or reopened-then-converted threads vanish after a month. _Recommend_ a long/no TTL for converted runs (small change to `append_log` or a dedicated write path).
4. **Pending approvals / in-flight turns at conversion time.** — _Recommend_ refusing to convert a non-idle LangGraph conversation (only convert `status == IDLE`), so we never strand a live approval. Document that abandoned approvals are dropped if conversion ever runs on a non-idle thread.
5. **`ui_payload` / visualization / notebook fidelity.** — These have no clean ACP target. _Recommend_ degrading to text for v1 of the converter and only investing in dedicated adapters if user feedback demands it. This dovetails with G5 (tool-card parity) — if G5 ships richer extractors that can re-derive cards from `rawOutput`, converted tool results improve for free; do not duplicate that work here.

## Dependencies & sequencing

- **Within this pass:** Option A has no dependencies (it is the status quo). Option B's mapper (step 2) is independent and testable first; the seeder (step 3) depends on the mapper; the API hook (step 4) depends on the seeder.
- **Cross-references (do not duplicate their scope):**
  - **G3 (`get_task` / `latest_run` query cost):** the converter creates exactly the `Task` + `TaskRun` shape G3 optimizes the read of. No conflict — G4 writes that shape, G3 reads it. If both land, converted conversations benefit from G3's `current_run_id` annotation automatically.
  - **G5 (tool-card parity):** the converter's degraded `tool_call`/`tool_call_update` frames render through the same `mcpToolRegistry`/extractors G5 improves. If Option B ships, its converted cards inherit whatever fidelity G5 delivers — so sequence Option B _after_ G5 if card fidelity for converted threads matters.
  - **G6 (notification rendering):** the converter only emits `_posthog/user_message` + `session/update`; it does not emit the `_posthog/usage_update`/`status`/etc. notifications G6 renders, so there is no overlap.
- **Rollout sequencing (from outstanding_items.md § 7):** this is the explicit "decision gate" step — resolve A-vs-B before sizing the rest of the roadmap. If A, the item closes with no code; LangGraph retirement is deferred to its own future project.

## Testing

**Option A:** no new tests. (Existing serializer tests already cover the dual-runtime read paths — `get_messages` returning `[]` for sandbox and the LangGraph state path. Confirm those remain green; no change is being made.)

**Option B:**

- **Unit (mapper):** parameterized test, one case per source message type in the table — `HumanMessage` → `_posthog/user_message`; `AssistantMessage` text → `agent_message`; `AssistantMessage` with `tool_calls` → `tool_call`(s); `AssistantToolCallMessage` → `tool_call_update`; `VisualizationMessage`/`NotebookUpdateMessage` → degraded form; `ContextMessage` → dropped. Assert no `agent_message_chunk` is ever emitted (would be stripped by `append_log`).
- **Integration (seeder):** convert a fixtured LangGraph conversation end-to-end; assert (a) exactly one `Task` + one terminal `TaskRun` created, (b) `conversation.agent_runtime == sandbox` and `task` linked, (c) the S3 log round-trips through the `logs/` endpoint into the same frames, (d) **idempotency** — a second conversion call is a no-op (no second Task), (e) `execute_task_processing_workflow` is **not** called (assert the workflow client is never invoked), (f) the transaction is atomic (simulate a save failure → no half-flipped conversation).
- **Query-count:** assert conversion runs a bounded number of queries (one graph state read, the Task/Run creates, two saves) — it must not N+1 over messages.
- **Frontend (jest, light):** verify the frontend's `bootstrapRun` replay renders converted frames without error (a converted log of mixed human/assistant/tool frames produces the expected thread items and is treated as read-only via `isTerminalRunStatus`). A Playwright test is overkill for a read-only converted thread; skip unless Option B becomes continuable.

## Rollout / flagging

**Option A:** n/a — it is the current behavior; nothing to flag.

**Option B:**

- Gate the on-demand conversion behind a new flag `phai-convert-legacy-history`, **layered on top of** `phai-sandbox-mode` (only convert for users already flipped to sandbox). Start at 0%, internal-only.
- Telemetry: `phai_legacy_conversion` event with `frames_total`, `frames_dropped_by_type`, `duration_ms`, `messages_total`. Watch the dropped-by-type histogram during rollout — a spike in dropped visualization/notebook frames is the signal that conversion is degrading real user history and the rollout should pause.
- Gradual: enable for internal users → small cohort → measure reopen-and-continue behavior → only then consider LangGraph retirement.
- **Irreversibility caveat:** flipping `agent_runtime` to `sandbox` is a one-way door per the current model (never re-evaluated). A bad conversion permanently degrades that thread's rendered history (the source checkpoints still exist, but the conversation now reads from S3). Keep the source checkpoints until conversion is proven, so a manual revert (`agent_runtime = langgraph`, `task = NULL`) is possible.

## Effort & risk

- **Effort:** Option A = ~0 (a decision + a doc note). Option B = **L** — pure mapper (S) + seeder with idempotency/transaction/lock (M) + API hook + TTL change + telemetry + tests (M). The mapping table is the deceptively hard part: getting tool-call and visualization frames to render acceptably is where the time goes, and full fidelity is impossible (acknowledged in the lossiness contract).
- **Risks (Option B):**
  - _Silent history degradation_ — the conversion is lossy by construction; a user's rich tool/insight cards become text. Mitigated by recommending A, and by the dropped-frames telemetry + read-only-only scope if B ships.
  - _One-way door_ — `agent_runtime` is never re-evaluated; a buggy conversion is permanent for that thread unless manually reverted. Mitigated by retaining source checkpoints and an idempotency guard.
  - _Orphaned S3 logs / TTL expiry_ — converted logs written before the atomic flip can orphan on rollback (harmless, GC-able), and the default 30-day `append_log` TTL would silently expire converted history (must be addressed — Decision 3).
  - _Concurrency_ — two concurrent opens racing to convert the same thread could create two Tasks; mitigated by the conversation row lock (reuse `lock_conversation_for_followup`).
  - _Scope creep to "continuable"_ — strong product pull to make converted threads resumable; that is a different project and must be ruled out (Decision 2).
