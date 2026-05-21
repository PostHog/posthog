# 05 — Sandbox sizing and Task model adjustments

PostHog AI sandboxes do dramatically less local work than PostHog Code sandboxes — no git clone, no `npm install`, no language toolchains, no test runs, no compilation. The agent process makes HTTP calls to MCP servers (which execute server-side in PostHog cloud) and shuttles ACP frames back. That workload is bound by network latency and JSON parsing, not CPU or memory.

This spec sizes the PostHog AI sandbox accordingly and defines the Task-model touchpoints that route a Task to the smaller profile.

---

## 1. Workload inventory

What actually runs inside a PostHog AI sandbox:

| Process | Purpose | Resource character |
|---|---|---|
| `agent-server` (Node.js, ~80 MB resident) | Tapped ACP stream relay + HTTP listener for `/command/` and `/events/` | Idle most of the time; bursts on tool calls. CPU-light, memory-stable. |
| Claude SDK / Codex (Node.js, ~150 MB resident) | The actual model client — token stream consumer, ACP request emitter | Idle while the model thinks; bursts when streaming tokens in / tool calls out. |
| `SessionLogWriter` flush loop | Coalesces `agent_message_chunk` into `agent_message`, batches `POST /append_log/` calls | Tiny CPU, negligible memory. |
| No git, no language toolchains, no package installs, no tests, no builds. | — | — |

Compared to PostHog Code's sandbox — which clones a repo (potentially gigabytes), runs `npm install` / `pip install` / `cargo build`, executes test suites, holds a working tree — the PostHog AI workload is roughly an order of magnitude lighter in both CPU and memory.

---

## 2. Recommended sizing

**Memory:** 1 GB hard limit.

Headroom calculation:
- Node.js base × 2 processes: ~250 MB resident
- Conversation context buffered locally before flush: peaks at ~50 MB even on a long chat
- ACP frame buffers + `session-log-writer` queues: ~50 MB
- HTTP keep-alive pools for MCP servers: ~30 MB

Total expected resident set: ~400 MB. A 1 GB ceiling gives 2.5× headroom for spikes (large tool outputs, long markdown bodies, mid-conversation re-reads of historical log).

**CPU:** 0.5 vCPU.

CPU is dominated by JSON parse / stringify on each ACP frame and by the HTTP keep-alive bookkeeping for the MCP servers. At Claude's typical token-stream rate (~50 tokens/sec sustained, ~150 burst), a single core processing JSON is ~5% utilized. 0.5 vCPU gives 10× headroom.

The agent does **no** local data processing — no HogQL execution, no insight rendering, no notebook compilation. Those workloads live behind MCP HTTP calls and run in PostHog cloud's regular Django + ClickHouse pool.

**Comparison to PostHog Code:** PostHog Code sandboxes typically run 2–4 GB / 2–4 vCPU to accommodate `npm install` + builds + test runs. The PostHog AI profile is roughly 25–50% of those numbers per dimension, which translates to ~25–50% of the per-sandbox compute cost.

---

## 3. Network policy

PostHog AI's outbound dependencies are narrower than PostHog Code's:

| Destination | Required for | Frequency |
|---|---|---|
| LLM gateway (`{region}.llm.posthog.com` or similar) | Model invocations | Every turn |
| PostHog cloud REST (`{region}.posthog.com/api/...`) | `append_log/`, `set_output/`, `relay_message/`, MCP server endpoints | Every tool call + every assistant turn |
| User-installed MCP server URLs | When a customer has installed third-party MCPs | Variable; only if installed |
| Claude's hosted `WebSearch` tool's destinations | When the agent uses web search | Rare, model-decided |

Doesn't need: GitHub, npm registry, PyPI, apt repos, Docker Hub, arbitrary public HTTP. Anything required for source compilation or dependency install is absent because there is no source compilation or dependency install inside the sandbox.

**Recommended policy:** `network_access_level === "trusted"` (cloud spec § 2.7) — confirms that "trusted" includes the LLM gateway + posthog.com domains. If trusted doesn't cover the LLM gateway, use `"custom"` with the explicit allow list:

```
{region}.posthog.com
{region}.llm.posthog.com
<each user-installed MCP server hostname>
```

`include_default_domains: false` (the "default domains" set is sized for code-running sandboxes — npm, pypi, etc. — none of which PostHog AI needs).

The `WebSearch` tool's destinations are handled separately by Claude SDK; they ride on whatever network policy the LLM gateway already permits.

---

## 4. Sandbox-environment selection

PostHog AI users do **not** pick a sandbox environment. The mode dropdown stays in `WorkspaceModeSelect.tsx` for PostHog Code; PostHog AI's chat input doesn't surface it.

Three implementation choices for selecting the constrained profile:

1. **Implicit profile keyed on `origin_product`.** The cloud-agent provisioner reads `task.origin_product == "posthog_ai"` and applies the 1 GB / 0.5 vCPU / `trusted`-network preset. No new field, no user-visible knob. **Recommended.**
2. **A reserved `SandboxEnvironment` row per region** (named e.g. `"posthog-ai-default"`) that the `POST /sandbox/` handler always references for PostHog AI Runs via `state.sandbox_environment_id`. No model change; uses existing fields. Slightly less elegant than (1) — the row is invisible-from-UI which feels surprising.
3. **A new `Task.sandbox_profile` enum field** with values like `default | posthog_ai`. Cleanest in terms of explicit intent but adds a Django migration for what is effectively a derived value.

Bias toward (1). It puts the routing decision in one place (the provisioner) and keeps the Django schema slim. `origin_product` already exists per the cloud spec § 2.3.

If we want to keep the door open for users to tune sandboxes themselves down the road (e.g., an enterprise wanting more RAM for very large MCP responses), option (3) becomes more attractive — but that's not on the roadmap.

---

## 5. Image / boot

The cloud-agent sandbox image today is Node.js-based and includes Claude Code's runtime. PostHog AI uses the same image — no fork. Two reasons:

1. **Avoid maintaining two image build pipelines.** Forking would mean two CI build paths, two security update cadences.
2. **The image's footprint that PostHog AI doesn't use** (git, build toolchains if any) is dwarfed by Node.js + Claude SDK itself. The savings from a forked image are small relative to the operational cost.

If cold-start latency hurts first-message UX (today's "Starting the sandbox…" loading screen), revisit. The pre-warming flow in § 8 is the primary mitigation; image slimming is lower-leverage in comparison.

---

## 6. Idle / shutdown

PostHog AI conversations are typically short bursts (one to a few user turns) followed by long idle gaps as the user reads the response or navigates away. A long idle-shutdown policy wastes sandbox compute; a short one means more cold starts on follow-ups.

Existing cloud-agent behavior: the sandbox is provisioned for the lifetime of a Run. On `_posthog/turn_complete` with no follow-up, the Run remains alive until either (a) a follow-up `POST /command/` arrives, or (b) an idle timeout fires server-side and the Run transitions to `completed` / `failed` / `cancelled`.

**Recommended idle timeout for PostHog AI Runs:** 5 minutes after `_posthog/turn_complete` with no incoming command. Reasons:

- The "I'll be right back" attention window for chat conversations is closer to 5 min than the multi-hour debugging sessions PostHog Code accommodates.
- After 5 min idle, a follow-up message creates a new Run with `state.resume_from_run_id` (per `02_CORE.md` § 5.3). Cold-start cost paid once per resumed conversation.

If the cloud-agent provisioner doesn't have per-`origin_product` idle policy today, this becomes a new knob — see § 8 open question 4.

---

## 7. Task model touchpoints summary

What `02_CORE.md` § 2 already covers and what this spec adds:

| Field on `Task` | Set by | Value for PostHog AI |
|---|---|---|
| `origin_product` (existing — cloud spec § 2.3) | Adapter at Task-create | `"posthog_ai"` — **drives the constrained sandbox profile** per § 4 above |
| `repository` | Adapter at Task-create | `null` — no repo (`04_PROMPTS.md` § 2.3) |
| `github_integration` | Adapter at Task-create | `null` |
| `internal` | Adapter at Task-create | `false` |
| `signal_report` | Adapter at Task-create | `null` (PostHog AI is user-initiated, never signal-report-triggered) |

What needs to land in the cloud-agent provisioner (not in Django):

- Recognize `task.origin_product == "posthog_ai"` and apply the constrained resource preset (§ 2).
- Apply the constrained network policy (§ 3) if not already covered by `SandboxEnvironment.network_access_level == "trusted"`.
- Apply the constrained idle timeout (§ 6).

These changes live below the Django layer — they're cloud-provisioning rules, not Task fields per se.

---

## 8. Pre-warming

The cloud-agent spec has no native pre-warming. First-message latency is dominated by sandbox boot + agent-server `newSession()` initialization (model-side cache warm-up adds more on top). Pre-warming amortizes that cost by spinning the sandbox up *before* the user submits.

### 8.1 Per-conversation eager warm

When the user focuses the chat input and types the first non-whitespace character, the frontend issues `POST /api/.../conversations/{id}/prewarm/`. The handler:

1. Creates a Task if the conversation doesn't yet have one (`Conversation.sandbox_task IS NULL`) — the same path as first-message Task creation in § 5.1, minus the `pending_user_message`.
2. Calls `POST /api/projects/{tid}/tasks/{taskId}/run/` with `mode: "interactive"`, **no** `pending_user_message`, **no** `state.attached_context`, and the standard systemPrompt. The agent-server boots, opens the ACP session, emits `_posthog/run_started`, and idles waiting for `POST /command/` `user_message`.
3. The new Run is the latest on the Task, so `Conversation.current_sandbox_run` (derived — see `02_CORE.md` § 2.2) automatically resolves to it. No conversation-row update needed.

When the user submits the message, the `POST /sandbox/` handler reads `conversation.current_sandbox_run.status`, finds it `in_progress`, and routes via the in-progress branch of § 6.1 — `POST /command/` to the existing sandbox. First-token latency drops from ~5–8 s (cold boot + session init) to roughly model invocation time.

**Cancellation.** If the input goes empty for >5 s OR the user navigates away from the chat surface, the frontend issues `DELETE /api/.../conversations/{id}/prewarm/`. The handler sends `POST /command/` `cancel` and lets the Run transition to terminal. The conversation can prewarm again on the next typing session — a new Run, fresh `created_at`.

**Idle self-cancel inside the sandbox.** A warmed Run that never receives a `user_message` should self-terminate after a short interval (60 s recommendation). Today's idle timer (`05_SANDBOX.md` § 6) fires on `_posthog/turn_complete` with no follow-up — a warmed Run never reaches `turn_complete`, so the existing timer never fires. We need a separate "never-started" timer dimension. See open question 9 below.

**Trigger refinement.** Debounce on first non-whitespace keystroke (200–300 ms), require the input to remain non-empty, *don't* prewarm on focus alone (users tab-switch repeatedly without typing — that's not a signal of intent).

### 8.2 Wire shape

```http
POST   /api/environments/{tid}/conversations/{id}/prewarm/
       → 204 No Content (warmed; sandbox booting or ready)

DELETE /api/environments/{tid}/conversations/{id}/prewarm/
       → 204 No Content (cancelled or no-op)
```

Both idempotent. POST on an already-warmed conversation is a no-op. DELETE on a non-warmed conversation is a no-op. Conversation row creation (if needed) happens inside the POST, atomic.

### 8.3 Agent-server compatibility

Per cloud spec § 10.6, the initial-task-message resolution falls through four sources: `resume_from_run_id` → `state.pending_user_message` → `state.initial_prompt_override` → `task.description`. For a fresh prewarm all four are empty. **Need to verify** that `agent-server.ts:1077-1297` handles this — the agent-server should boot the session and idle, not error out. If it doesn't, we patch with a `state.await_user_message: true` flag that short-circuits the initial-message logic. Tracked as open question 10.

---

## 9. Restoration semantics

Sandboxes are ephemeral; conversations survive. The cloud-agent already covers most failure modes — this section enumerates them and the recovery path so it's clear what's automatic, what's manual, and where the holes are.

### 9.1 Sandbox dies mid-conversation (the common case)

Triggers: spot-VM preemption, OOM, idle timeout, host crash, agent process exit. The Run transitions to a terminal status — `failed` for crashes, `cancelled` for clean idle timeouts, `completed` if a graceful close fired.

**What survives**:

- The S3 NDJSON log up to the last `SessionLogWriter` flush (per cloud spec § 10.10, the flush debounce is 500 ms / max 5 s / 50-entry threshold — so worst-case ~500 ms of frames are lost).
- `Conversation.sandbox_task` (the Task is independent of any single Run).
- `Conversation.current_sandbox_run` still resolves to the now-terminal Run because it's still the latest by `created_at` until a successor is created.

**Recovery path**: the user's next message triggers § 6.2's terminal-then-resume branch. The `POST /sandbox/` handler creates a new Run with `state.resume_from_run_id = previous_run_id` and kicks off the new sandbox. `current_sandbox_run` automatically resolves to the new Run via the Task's reverse relation — no conversation-row update. The agent-server's session-init code (`agent-server.ts:1515-1527`) reads the predecessor's S3 log via `resumeFromLog`, replays conversation history into the model's context, then handles the new user message. From the user's perspective there's a brief "starting…" indicator (the existing `CloudInitializingView` surface) and then the conversation continues.

**Recovery is automatic.** The frontend doesn't need any new behavior — § 6.2 already specifies it.

### 9.2 S3 log lost or corrupted

If a Run's NDJSON log in S3 is missing or unreadable, `resumeFromLog` reads nothing. The new sandbox boots with no model context — the agent appears to "forget" everything before the last resume boundary.

**What we can do**:

- **Frontend conversation-message mirror**: if PostHog continues to mirror messages Django-side (today's `ConversationMessage` table or equivalent — open question 11 below), the frontend's thread view still renders prior turns. The user can re-orient even though the agent's memory is gone.
- **No automatic agent-memory recovery**. Reconstituting agent context from a non-S3 source isn't in the cloud-agent today and isn't worth building unless S3 loss becomes common.

**Mitigation is at the storage layer**, not the application layer — cross-region replication on the log bucket, retention policy reviews, backup posture. Out of scope for this spec; flag to infra.

This is the only failure mode without automatic recovery.

### 9.3 Client disconnects while sandbox lives

Tab close, network glitch, navigation away. The sandbox keeps running; logs keep accumulating in S3. The browser's `EventSource` against `/api/projects/{tid}/tasks/.../stream/` closes; Django wasn't holding the SSE in the first place, so no server-side teardown work is needed (see § 9 of `02_CORE.md`).

**Recovery path**: the user reopens the conversation. The bootstrap in `02_CORE.md` § 4.2 walks the full Task → Runs chain, fetches every `session_logs/`, concatenates, plus opens fresh SSE if the current Run is non-terminal. Already specified, already automatic.

### 9.4 Long-conversation case study

A conversation that's been alive for a week, picked up and dropped repeatedly, accumulating (say) 8 Runs across idle timeouts overnight, two preemptions, and one OOM:

| Conversation row state | Value |
|---|---|
| `sandbox_task` | Single Task created on the first message — same across all 8 Runs |
| `current_sandbox_run` (derived) | Resolves to the 8th Run (`in_progress` if the user is active, `cancelled` if last idle-timed-out) — it's the latest by `created_at` |
| `Task.runs` | All 8 Runs, ordered by `created_at` |
| S3 NDJSON logs | 8 files, one per Run; the bootstrap reads all and concatenates per § 4.2 |

Each Run after the first carries `state.resume_from_run_id` linking to its predecessor — the chain is reconstructable from either `created_at` ordering or the resume-from pointer (both agree in healthy operation).

If a single conversation accumulates dozens of Runs and the bootstrap fetch becomes slow, see the long-conversation perf mitigations in `02_CORE.md` § 4.2 (parallel fetch, server-side concat cache).

### 9.5 Future cleanup — `TaskRun.previous_run` as a real FK

`state.resume_from_run_id` is a soft-schema JSON field — brittle, no DB-level integrity, easy to corrupt with a stray `state` patch. A real `TaskRun.previous_run = ForeignKey("self", null=True, on_delete=models.SET_NULL)` would give us referential integrity and a JOIN-able predecessor link. That change lives on the cloud-agent side (`products/tasks/backend/models.py::TaskRun`) and is out of scope for this migration, but worth tracking as a follow-up — file as a separate issue when the migration ships.

---

## 10. Open questions

1. **Current PostHog Code sandbox sizing.** Need exact numbers before claiming "PostHog AI is 25–50%". *Owner: infra.*
2. **Does the provisioner support per-`origin_product` profiles today?** If not, option (3) in § 4 (the `Task.sandbox_profile` field) becomes the carrying mechanism, even though (1) reads cleaner. *Owner: infra.*
3. **Does `network_access_level: "trusted"` include the LLM gateway?** The existing `SandboxEnvironment.effective_domains` property (`products/tasks/backend/models.py:1218–1225`) returns the resolved domain list. Spot-check that the LLM gateway hostname is on it; if not, PostHog AI Runs need `"custom"` with the explicit list in § 3. *Owner: infra.*
4. **Per-`origin_product` idle timeout.** Cloud-agent provisioner today probably ships one idle timeout for everyone. Need a new dimension or a per-Run override via `state.idle_timeout_seconds`. *Owner: infra.*
5. **Memory ceiling validation.** 1 GB is a conservative ceiling based on observed Node.js footprint. Confirm with a load-test of a long conversation (50+ turns, large MCP responses) before pinning. If memory pressure shows up at 1 GB, bump to 1.5 GB and reassess. *Owner: AI.*
6. **CPU ceiling validation.** Same — confirm 0.5 vCPU sustains streaming during the peak (large tool result + simultaneous next-turn agent_message_chunk). Bump to 1 vCPU if latency suffers. *Owner: AI.*
7. **Cost projection.** With constrained sizing, what's the per-sandbox-hour cost? Compare to the LLM cost per chat — if compute is < 10% of LLM cost, further tightening doesn't matter for the unit economics. *Owner: finance + AI.*
8. **Prewarm latency telemetry.** Once § 8 ships, measure: median time from `POST /prewarm/` to `_posthog/run_started`. If this exceeds the median typing time (i.e., users submit before the sandbox is ready), the prewarm signal needs to fire earlier or we need a different acceleration story. *Owner: AI.*
9. **Never-started idle timer for warmed Runs.** § 8.1 needs an idle-cancel that fires when a Run reaches `in_progress` but no `user_message` arrives within ~60 s. Today's idle timer fires on `_posthog/turn_complete`, which a warmed Run never reaches. New dimension in the provisioner, or a per-Run `state.warm_only_timeout_seconds` override. *Owner: infra.*
10. **Agent-server handles empty initial message.** Confirm `agent-server.ts:1077-1297` doesn't error when all four initial-message sources are empty (per § 8.4). If it does, propose `state.await_user_message: true`. *Owner: AI + agent-server.*
11. ~~**Conversation-message mirror Django-side.**~~ **Resolved**: sandbox-runtime conversations do **not** mirror messages Django-side. History lives in S3 ACP logs and is retrieved via the new `/log/` endpoint (`02_CORE.md` § 4.6) or the SSE bootstrap snapshot (`02_CORE.md` § 4.2). The detail endpoint's `messages` field is empty for sandbox conversations and populated only for LangGraph (`02_CORE.md` § 4.7). This leaves § 9.2 (S3 log loss) as a storage-layer concern — durability handled by S3 replication, not by application-layer mirroring.
12. **S3 log retention / backup.** What's the durability story for the NDJSON logs? Single-bucket, no replication, or replicated cross-region? Affects § 9.2 likelihood. *Owner: infra.*

---

## 11. Cross-references

- `02_CORE.md` § 2 — Task linkage on the `Conversation` row (single FK; `current_sandbox_run` derived).
- `02_CORE.md` § 4.2 — multi-Run bootstrap that consumes the chain documented in § 9.
- `02_CORE.md` § 5.3 — terminal-then-resume lifecycle that ties § 9.1 together.
- `04_PROMPTS.md` § 2.3 — no-repository posture (related Task-field disposition).
- `00_OVERVIEW.md` § 12 — out-of-scope items (sandbox environment CRUD UI stays PostHog Code only).
- Cloud spec § 2.7 — `SandboxEnvironment` shape including `network_access_level` and `allowed_domains`.
- Cloud spec § 10.1 — agent-server boot CLI flags (image-level concerns).
- Cloud spec § 10.10 — `SessionLogWriter` flush semantics referenced by § 9.1.
