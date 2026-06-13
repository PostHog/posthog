# Outstanding items — newly noticed gaps (planning triage)

Companion to [`cloud_implementation_gaps.md`](./cloud_implementation_gaps.md) (Twig-vs-spec drift) and [`TODO.md`](./TODO.md) (post-migration backfills).
Audited on 2026-06-13. This document triages **six items noticed outside those two docs**, each grounded in current code, so we can plan and size every one.
It ends with a prioritized roadmap (§ 7) that folds these into the already-documented outstanding work.

Each card carries: **Priority · Effort · Blocks broad rollout? · Evidence (file:line) · What's missing · Approach · Open questions**.
Effort is S / M / L. "Blocks broad rollout" = must land before flipping non-internal users from the LangGraph runtime to the sandbox runtime.

---

## 1. Smaller sandboxes for data-only conversations

**Priority: highest** (user-stated) · **Effort: M** · **Blocks rollout: no** (cost/latency lever, not correctness)

### What's missing

Every sandbox is provisioned identically — **4 CPU / 16 GB / 64 GB disk** — whether it runs a real coding task or answers "what's my WAU trend." PostHog AI conversations are pure data Q&A over MCP tools with **no repo checkout**, so the coding-grade machine is wasted spend and slower boots.

### Evidence

- `SandboxConfig` defaults: `products/tasks/backend/services/sandbox.py:68-81` — `memory_gb=16`, `cpu_cores=4`, `disk_size_gb=64`.
- Config is built with those defaults and **never parameterized** by intent: `products/tasks/backend/temporal/process_task/activities/provision_sandbox.py:356-364` (no `cpu_cores`/`memory_gb` passed).
- Defaults map straight to Modal: `products/tasks/backend/services/modal_sandbox.py:357-358` (`"cpu": float(config.cpu_cores), "memory": int(config.memory_gb * 1024)`).
- PostHog AI is always no-repo: `products/posthog_ai/backend/message_routing.py:351` (`repository=None`); the activity already branches on "no repo" at `provision_sandbox.py:239-240`.
- Intent is already knowable at provision time: `ctx.origin_product == Task.OriginProduct.POSTHOG_AI`, `ctx.repository is None`, and the run state dict (`PostHogAIRunState`, `message_routing.py:366-373`) can carry a tier hint. `TaskProcessingContext.mode` exists at `get_task_processing_context.py:65-67`.

### Approach

1. Carry a tier signal (`sandbox_tier: "data_only"` or similar) from conversation creation into `run_state` / `ProcessTaskInput`, **or** derive it implicitly — since _all_ PostHog AI runs are no-repo, the simplest cut is "PostHog AI origin + no repo ⇒ small tier" with no new field.
2. Compute `cpu_cores` / `memory_gb` / `disk_size_gb` (and optionally a slimmer image without the coding toolchain) from that signal in `provision_sandbox.py:356-364`.
3. Gate behind a rollout flag; add boot-time + cost telemetry to confirm the smaller machine holds up.

### Open questions

- What's the right small spec? Validate that data Q&A (SQL execution, query-result handling, notebook/insight rendering) fits in, say, 1–2 CPU / 2–4 GB before committing. Disk needs are dominated by query-result caching, not source.
- Do any PostHog AI flows legitimately need heavy compute (large result post-processing, notebook artifact rendering)? If a rare flow does, it needs an escape hatch to the big tier.
- One small image variant vs. just smaller CPU/mem on the existing image — the latter is far cheaper to ship first.

---

## 2. Cancel button shows the "bail" (stop) affordance after cancellation

**Priority: high** · **Effort: S** · **Blocks rollout: no** (visible bug, small fix)

### What's missing

After the user cancels an in-flight turn, the composer's primary button keeps rendering the **stop** state ("Let's bail") instead of returning to **send** ("Let's go!"), because the button derives its state from loading flags that aren't all cleared at cancel time.

### Evidence

- `stopGeneration` listener: `frontend/src/scenes/max/maxThreadLogic.tsx:1295-1313`. It fires `loadConversation(...)` **without awaiting** (`:1311`) and then synchronously `setCancelLoading(false)` (`:1312`) — the two race.
- Button/tooltip derivation: `frontend/src/scenes/max/components/QuestionInput.tsx:463-479` — tooltip is "Let's bail" whenever `showStopButton` is true; `showStopButton = threadLoading && !isQueueingSubmission`, and `threadLoading = conversationLoading || streamingActive`.
- Suspected root cause: at cancel, `cancelLoading` flips to `false` while `conversationLoading` is still `true` (the fire-and-forget `loadConversation` refetch is in flight) and/or `streamingActive` hasn't torn down — so `threadLoading` stays `true`, `showStopButton` stays `true`, and the stop tooltip persists.

### Approach

- Reset the button state from a definite conversation status (idle / canceling) rather than from the union of loading flags; or move `setCancelLoading(false)` into `loadConversation`'s success path so it doesn't pre-empt the refetch; and ensure `streamingActive` / `generationController` teardown actually flips `showStopButton`.
- **Confirm scope:** `stopGeneration` here is LangGraph-centric (`api.conversations.cancel`). The sandbox runtime cancels via the command relay (`method: "cancel"`) through `sandboxStreamLogic` — verify whether the same stale-button symptom exists on that path and fix both, or confirm the sandbox path derives state differently.

### Open questions

- Is the report from the LangGraph path, the sandbox path, or both? That decides whether the fix lives in `maxThreadLogic` only or also in `sandboxStreamLogic`.

---

## 3. `get_task` extra query + `latest_run` full-scan in the conversation serializer

**Priority: medium-high** · **Effort: S** · **Blocks rollout: no**

### What's missing — and what it actually is

This was flagged as an N+1 in the conversation serializer. To be precise about what's there today:

- It is **not** a classic list N+1. `list` uses `ConversationMinimalSerializer`, which omits `task`; `retrieve` uses the full `ConversationSerializer` with the `get_task` method (`serializers.py:140-152`, comment at `:142-144` claims "never hit on `list`" — verified correct).
- Two **real** costs remain:
  1. **`latest_run` materializes every run.** `get_task` → `conversation.current_run` (`assistant.py:147-152`) → `task.latest_run` (`products/tasks/backend/models.py:240-247`), which does `list(self.runs.all())` and picks the max in Python. Cost grows with conversation length (every follow-up adds a run row), even though we only need the newest.
  2. **Request-level N+1 by design.** Because the list serializer omits `task` / `current_run_id`, the frontend has no bootstrap handle from the list and must `retrieve` each conversation to open its stream — i.e. N retrieves when restoring history. That is the N+1 the design invites, just one layer up from the ORM.

### Evidence

- Serializer: `ee/hogai/api/serializers.py:140-152` (`get_task`), `:55-58` (the sandbox-task sub-serializer already exposes `current_run_id`).
- Model hops: `products/posthog_ai/backend/models/assistant.py:147-152`; `products/tasks/backend/models.py:240-247`.
- List path: `ee/api/conversation.py:325-326` (defers fields) and `:402-403` (minimal serializer).

### Approach

- Replace `latest_run`'s `list(self.runs.all())` with an ordered `.order_by("-created_at").first()` **or** a `Max(created_at)` annotation — but first check other callers of `latest_run`, since the current shape is deliberately prefetch-friendly (a bare `.first()` breaks prefetch reuse where tasks are loaded in bulk).
- Surface a lightweight `current_run_id` on the **list** queryset via a subquery annotation (feed it into the existing sub-serializer field) so the frontend can bootstrap each stream without a per-conversation `retrieve` — kills the request-level N+1.

### Open questions

- Are there bulk-load callers of `Task.latest_run` that rely on the prefetch-cache behavior? If so, annotate rather than `.first()`.

---

## 4. Legacy LangGraph conversation history → sandbox conversion

**Priority: medium-high** · **Effort: L (full migration) / negligible (if coexistence accepted)** · **Blocks rollout: depends on the product decision below**

### What's missing

`agent_runtime` is stamped at create and **never re-evaluated** (`assistant.py:130-136`), so a conversation stays on whichever runtime it was born under. There is **no converter** that takes a LangGraph conversation's window message history and rehydrates it as a sandbox conversation (new Task + TaskRun + seeded S3 ACP log). Until one exists, a user mid-thread on LangGraph can't be moved to the sandbox runtime without losing their history, and we can't retire the LangGraph runtime.

### Evidence

- LangGraph history: read via `DjangoCheckpointer` (`ee/hogai/django_checkpoint/checkpointer.py`) → `state.messages` (LangChain message objects), serialized in `get_messages` (`serializers.py:101-125`).
- Sandbox history: lives in S3 ACP run logs, returned as `messages: []` from the serializer (`serializers.py:104-105`) and loaded by the frontend from the tasks logs endpoint (`products/tasks/backend/api.py:2306-2325`). Wire shape for a seeded user turn: `products/posthog_ai/backend/wire_types.py:66-79` (`_posthog/user_message`).
- No backfill code exists; migration `0004` only adds the `agent_runtime` / `task` columns.

### Approach

This item only exists if we need cross-runtime history. **Decide first:**

- **Option A — coexistence (cheap).** Old threads stay LangGraph read-only forever; only new threads are sandbox. The `agent_runtime` per-conversation field already supports both runtimes side by side, so this is ~zero work. Likely acceptable for v1.
- **Option B — convert (expensive, lossy).** Map each LangChain message → an ACP log notification (`_posthog/user_message`, assistant message, tool_call, tool_result), seed a synthetic `TaskRun` log in S3, flip `agent_runtime` to `sandbox`. Lossy because LangGraph tool calls / artifacts don't map 1:1 onto ACP frames — visible human/assistant turns convert cleanly; rich tool-call cards likely degrade to text. Do it on-demand when a user reopens an old thread, not as a bulk backfill, to bound risk.

### Open questions

- **The decision that determines whether this is L or zero:** is coexistence (Option A) acceptable, or must existing threads become sandbox-native? Recommend A unless there's a concrete reason to retire LangGraph immediately.

---

## 5. Code diff rendering for tool-call content

**Priority: medium-low** · **Effort: M** · **Blocks rollout: no**

### What's missing

Already noted as a known gap in `cloud_implementation_gaps.md` § 5. There is **no diff UI** in the sandbox runtime. Any file-edit-shaped tool call falls through to `FallbackMcpToolRenderer.tsx`, rendering input/output as raw JSON/text — no added/removed lines, no syntax highlighting. `extractors.ts` has no diff extractor.

### Evidence

- Fallback card: `frontend/src/scenes/max/messages/FallbackMcpToolRenderer.tsx` (JSON-in / text-out, `:75-100`).
- Extractors: `frontend/src/scenes/max/messages/adapters/extractors.ts` — handles visualizations/queries/dashboards/notebooks/recordings/error-tracking; nothing for diffs or edits.

### Approach

- Add an extractor + adapter that detects edit-shaped tool calls (`old_string`/`new_string`, Edit/Write/MultiEdit) and renders a diff (reuse the existing Monaco diff editor or a lightweight line-diff component).

### Open questions

- **Confirm there's anything to render first.** PostHog AI is no-repo, so classic file edits are near-zero. Identify which tool calls actually emit diff-shaped payloads in PHAI (insight-update? notebook block edits? none today?) before building — this may be premature until a concrete producer exists.

---

## 6. Mobile friendliness of the Max UI

**Priority: lowest** (user-stated) · **Effort: M-L** · **Blocks rollout: no**

### What's missing

The Max chat UI is desktop-only — fixed widths, no responsive breakpoints. On a narrow viewport it renders poorly.

### Evidence

- Fixed-width thread + composer: `frontend/src/scenes/max/Thread.tsx:239,254` and `frontend/src/scenes/max/components/QuestionInput.tsx:232` (`max-w-180`, no `sm:`/`md:`/`lg:` variants).
- Side-panel mount has hard minimums: `frontend/src/layout/navigation-3000/sidepanel/SidePanel.tsx:80-81` (`DEFAULT_WIDTH = 512`, compact min `330`).
- No `useBreakpoint` usage anywhere in the Max scene.

### Approach

- Introduce breakpoints; make the Max panel go full-width / overlay on small screens; audit the composer and artifact cards for hardcoded widths. Defer until the higher-priority items land.

---

## 7. Prioritized roadmap

### Newly noticed (this doc)

| #   | Item                                 | Priority      | Effort | Blocks rollout                    |
| --- | ------------------------------------ | ------------- | ------ | --------------------------------- |
| 1   | Smaller data-only sandboxes          | **Highest**   | M      | No                                |
| 2   | Cancel "bail" button bug             | High          | S      | No                                |
| 3   | `get_task` / `latest_run` query cost | Medium-high   | S      | No                                |
| 4   | Legacy history → sandbox conversion  | Medium-high\* | L / ~0 | \*Depends on coexistence decision |
| 5   | Code diff rendering                  | Medium-low    | M      | No                                |
| 6   | Mobile friendliness                  | Lowest        | M-L    | No                                |

\* Item 4's priority and effort both collapse if we accept runtime coexistence (Option A). Make that decision before sizing anything else here.

### Suggested sequencing

1. **Quick wins first:** #2 (cancel button) and #3 (query cost) are both S and independent — clear them early.
2. **Biggest lever:** #1 (small sandboxes) — highest user-stated priority; M effort; immediate cost + boot-latency payoff. Needs a tier-classification decision but the plumbing is ready.
3. **Decision gate:** resolve Item #4's coexistence question. If Option A, close it as a non-task; if Option B, schedule the L migration before LangGraph retirement.
4. **Deferred:** #5 (only once a diff producer exists) and #6 (lowest).

### Already documented elsewhere — still outstanding

- **Gaps-doc-derived items** — every claim in `cloud_implementation_gaps.md` was verified against the code on 2026-06-13; the ones that need work are listed as bullets in § 8.
- **Backfills from `TODO.md`** (each already has a full card there): billing context, slash commands (`/init`, `/usage`, …), web-search gating for Bedrock teams, MultiQuestionForm answer channel, notebook block streaming, insight-editor "fix this query" trigger, PostHog AI → PostHog Code integration, scene-enriched workflows (contextual insight editing).

---

## 8. Gaps verified against the code (2026-06-13)

Every claim in `cloud_implementation_gaps.md` was checked against both repos (PostHog + `/Users/georgiy/Projects/posthog/Twig`), with `git` archaeology on each cited commit. This section keeps only what needs planning. Everything else verified accurate and needs no work — the § 1 file-index moves, the § 4.2.1 `{queued: true}` relay, the § 4.3 endpoint / JWT / env plumbing, the § 5.4 wire facts (no `messageId`, non-terminal `task_run_state`, `Last-Event-ID` precedence), and the § 6 out-of-scope set.

**Verified resolved — do NOT re-plan:**

- **Permission-lifecycle log recovery (§ 2.2)** — shipped. `sandboxStreamLogic.bootstrapRun` replays the `logs/` endpoint and re-derives approval cards from the persisted `_posthog/permission_request` / `_posthog/permission_resolved` notifications (`frontend/src/scenes/max/sandboxStreamLogic.ts:583-613, 896-913`). Reload-mid-approval is fixed; only the spec prose (`02_CORE.md` § 6.3, `cloud_implementation.md` § 10.8) is stale.
- **Agent-readiness tracking (§ 4.2.3)** — shipped. `runStarted` / `turnComplete` reducers + an `isThinking` selector already exist in `sandboxStreamLogic` (~`:554`, ~`:561`).

### Needs planning

- **`_meta.claudeCode.*` is emitted but never consumed (§ 3.3.2 / § 3.3.5)** — _latent correctness bug, not missing UI._ Twig emits permission/denial metadata as nested camelCase (`_meta.claudeCode.toolName`, `_meta.claudeCode.toolResponse.{decisionReason, decisionReasonType, message}` — `Twig sdk-to-acp.ts:810-818`, `permission-handlers.ts:59-68`), but PostHog's `SessionUpdateToolCallMeta` type expects flat snake_case (`frontend/src/scenes/max/sandboxWireTypes.ts:141-145`) and `resolveToolKey` never reads `claudeCode.*` (`sandboxStreamLogic.ts:112-147`, zero hits repo-wide). Effect today: tool denials render as generic failures (reason dropped) and MCP approval cards can't name the server + inner tool. Fix the type to the real shape and read it in `resolveToolKey` + the denial renderer. **Effort: S–M · Priority: medium-high (silent data loss).**

- **`_posthog/resources_used` "PostHog resources used" bar (§ 3.2)** — the agent emits the list of PostHog products touched per turn (derived from MCP `exec` inner-tool calls); PostHog types it (`sandboxWireTypes.ts:288-291`) but drops it at dispatch (`sandboxStreamLogic.ts:914`). Twig renders a persistent bar above the composer (`SessionResourcesBar.tsx`). This is **exactly the signal every Max data conversation generates**, so it pairs naturally with Item 1 (small data-only sandboxes). Decide whether PostHog AI wants the affordance; if yes, render the bar. **Effort: S–M · Priority: medium.**

- **Other typed-but-unrendered `_posthog/*` notifications (§ 3.1)** — typed in `sandboxWireTypes.ts`, dropped at `sandboxStreamLogic.ts:914`; each is incremental render work:
  - `_posthog/usage_update` — token usage + cost, plus a separate context-window breakdown (two forms; the Codex variant differs). Token/cost + context-window UI.
  - `_posthog/status` + `_posthog/compact_boundary` — context-compaction start/end + post-compaction summary; render inline as Twig does.
  - `_posthog/task_notification` — task milestones.
  - `_posthog/sdk_session` — adapter / session identification (mostly diagnostic).

  **Effort: M total, incremental · Priority: low-medium.** (`_posthog/progress` is deliberately excluded — no Twig adapter emits it, so there is nothing to render.)

- **Claude built-in tool display mapping (§ 5.1)** — `Task` / `Skill` / `ToolSearch` / `TodoWrite` and other built-ins render through `FallbackMcpToolRenderer` with the raw wire name + default icon. Add friendly titles / icons in `mcpToolRegistry.tsx`. **Effort: S · Priority: medium (affects every sandbox conversation's tool cards).**

- **`refresh_session` not on the relay allowlist (§ 2.1)** — `TaskRunCommandRequestSerializer.ALLOWED_METHODS` (`products/tasks/backend/serializers.py:1400-1406`) rejects it with a 400, while the in-sandbox JWT `/command` endpoint accepts it. **Blocks the planned MCP hot-loading** (`04_PROMPTS.md` § 5.4): either add it to the relay allowlist (+ sandbox proxying) or route the refresh server-side. **Effort: M · Priority: medium (feature-blocking for hot-loading; otherwise dormant).**

- **Pre-first-message transparency statuses (§ 5.3)** — only coarse `queued` / `in_progress` exists; no fine-grained provisioning / activation steps before the first agent message. **Effort: M · Priority: low-medium (rollout polish).**

- **Sandbox disconnect / crash telemetry + crash affordance (§ 4.1)** — no `CLOUD_STREAM_DISCONNECTED` equivalent for reconnect budgets, and an agent crash (`"Agent server crashed: …"`) surfaces as a generic error (`sandboxStreamLogic.ts:677`), not a distinct affordance. **Effort: S · Priority: low-medium (telemetry / UX parity).**

- **Richer SSE reconnect model (§ 2.3)** — PostHog has only the 5 / 2s / 30s model (`sandboxStreamLogic.ts:39-52`); Twig adds a cumulative cap, a healthy-connection rule, and a separate stream-error budget. **Effort: M · Priority: low (the simple model fails safe).**

- **Code diffs (§ 5.2)** — already carded as **Item 5** above; not repeated here.
