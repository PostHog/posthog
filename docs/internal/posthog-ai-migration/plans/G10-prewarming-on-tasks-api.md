# Prewarming as a generic tasks-API capability

> **Source:** sandbox-API design thread (prewarm generalization) · **Locus:** backend — products/tasks runs viewset + cloud provisioner; PostHog AI conversation caller
> **Effort:** M · **Priority:** Medium (unblocks cross-product warm; PostHog AI prewarming already works via the conversation layer, so this is generalization, not a new user-facing feature) · **Blocks rollout:** No
> **Joins:** Pairs with [G11 — sandbox conversation API → tasks-API migration](./G11-sandbox-logic-tasks-api-migration.md), which consumes the `warm` action as the backend of the conversation `prewarm`/`open(content=null)` path. Independently shippable: G10 can land and be exercised by the existing conversation prewarm before G11 starts.

> Line refs reflect the codebase as researched on 2026-06-17. Where a ref is drawn from a cross-file mapping rather than opened in place, it is marked `(mapping)`; re-verify on implementation — line numbers drift.

## Problem

Prewarming — eagerly booting a sandbox + ACP session while the user is still forming intent, so first-token latency drops from cold-boot (~5–8 s) to roughly model-invocation time — lives entirely inside PostHog AI's conversation layer today.
`MessageRoutingService.prewarm()` / `prewarm_release()` (`products/posthog_ai/backend/message_routing.py:208` / `:278`, _mapping_) are exposed as `POST` / `DELETE /api/.../conversations/{id}/prewarm/` (`ee/api/conversation.py:782-807`).

But warming is not conversation-specific — it is a generic run-lifecycle optimization.
Any product that drives an interactive sandbox benefits from the same boot-ahead: an interactive PostHog Code session the user is about to type into, a Signals investigation a user is about to interact with, a future interactive surface that does not exist yet.
Keeping the capability conversation-scoped forces every other product to reimplement the hard parts — provisioning, quota gating, concurrency control, the never-started idle timer — and to invent a conversation row they do not otherwise need.

This spec moves the warm **mechanic** plus its **guardrails** (quota, concurrency caps) onto the generic products/tasks API, leaving each product a thin caller that owns only two things the tasks API structurally cannot: **when** to warm (the trigger) and **birth + ownership** of the Task being warmed.

## Current behavior (verified)

**The conversation prewarm action** — `ee/api/conversation.py`:

- `@action(detail=True, methods=["POST", "DELETE"], url_path="prewarm")` at `:782`; `POST` warms, `DELETE` releases, both idempotent and sandbox-runtime only (`:790-791` guards `agent_runtime == SANDBOX`).
- `POST` shares the AI-credit billing gate (`is_team_limited(..., QuotaResource.AI_CREDITS, ...)` at `:800-805`) and the AI rate throttle (the `is_prewarm_warm` branch in `check_throttles`, `:373-375`) — "warming provisions a real sandbox, so it must share the same rate limit" (`:371-372` comment).
- `DELETE` calls `service.prewarm_release()` (`:796`); `POST` calls `service.prewarm()` (`:806`).

**The routing-service implementation** — `products/posthog_ai/backend/message_routing.py` (_mapping_):

- `prewarm()` at `:208` — "Eagerly boots sandbox + ACP session while user types. Caps to max 2 concurrent per user, 10 per org. Idempotent: no-op if current Run already in-progress. Calls `execute_task_processing_workflow()` after the transaction commits." It creates a Task in-process if the conversation has none (`Conversation.task IS NULL`), then starts a Run with `mode="interactive"`, **no** `pending_user_message`, **no** `attached_context`.
- `prewarm_release()` at `:278` — cancels the warm Run via `send_cancel(run, auth_token=self._connection_token(run))`.
- `_connection_token()` at `:297` — mints the RS256 connection JWT via `create_sandbox_connection_token` (`products/tasks/backend/services/connection_token.py:131`, RS256, 24 h TTL).

**The underlying tasks primitives the prewarm uses** — `products/tasks/backend/models.py` (_mapping_):

- `Task.create_and_run(...)` at `:279` — first warm (no Task yet).
- `task.create_run(...)` at `:230` — re-warm on an existing Task.
- `Task.OriginProduct` enum holds `USER_CREATED, ERROR_TRACKING, SLACK, SIGNAL_REPORT, AUTOMATION` today; **`POSTHOG_AI` is not yet a value** (added by [G1](./G1-small-data-sandboxes.md) / `05_SANDBOX.md` §4).

**Precedent for per-product quota on a run-lifecycle action** — `products/tasks/backend/api.py`:

- `resume_in_cloud` at `:2616` returns `429` with `"Team is over its posthog_code usage limit"` (`:2609-2611`). So a generic runs action already gates on a product-specific usage limit — the pattern this spec generalizes.

**Release is already a generic verb** — the `cancel` JSON-RPC method is on the relay allowlist (`products/tasks/backend/serializers.py:1400`, `TaskRunCommandRequestSerializer.ALLOWED_METHODS = ["user_message", "cancel", "close", "permission_response", "set_config_option"]`) and is proxied to the sandbox via `POST /api/.../runs/{run}/command/` (`api.py:2322`). `prewarm_release` is functionally identical to issuing `cancel` on the warm run.

## Approach

**Move the warm mechanic and its guardrails to a generic `warm` action on `TaskRunViewSet`; keep the trigger and Task ownership per-product; release is the existing `cancel` verb.**

```text
POST /api/projects/{tid}/tasks/{task}/runs/warm/            scope: task:write
  1. idempotent: if a non-terminal run already exists on the task → return it (no double-warm)
  2. enforce quota (dispatched on task.origin_product) + warm-pool concurrency caps  ← BEFORE provisioning
  3. else create_and_run(mode="interactive", await_user_message=true, no pending_user_message)
  → 200 { run_id, status }
  → 402/429 when over the product's quota or the warm-pool cap
```

Release is **not** a new endpoint — it is the generic `cancel` verb the relay already accepts:

```text
POST /api/projects/{tid}/tasks/{task}/runs/{run}/command/   { "method": "cancel" }
```

### Why this cut

Three of `prewarm`'s four responsibilities are generic or generalizable; one is irreducibly per-product. The cut follows that line exactly:

| Responsibility                                                            | Disposition                                                                                                                                         |
| ------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Boot an interactive run with no pending message and idle awaiting input   | **Generic** → the `warm` action (`create_and_run` minus the message)                                                                                |
| Quota gate (today AI credits)                                             | **Generic, dispatched on `task.origin_product`** — `POSTHOG_AI → AI_CREDITS`, `POSTHOG_CODE → posthog_code limit`, … (precedent: `resume_in_cloud`) |
| Concurrency caps (today 2/user, 10/org)                                   | **Generic warm-pool limiter** with per-product defaults                                                                                             |
| Trigger (user typing in the Max composer)                                 | **Per-product** — a UI signal; never moves                                                                                                          |
| Task birth + linking to the product's own entity (`conversation.task` FK) | **Per-product** — `warm` operates on an _existing_ Task                                                                                             |

The last two are why the action stays clean: `warm` never needs to know what a Conversation is. Every product that would warm already owns a Task before it warms (that is how tasks are born for non-PostHog-AI products), and PostHog AI's "create the Task if the conversation has none" is its own bootstrap, performed _before_ it calls `warm` (see G11).

### Why guardrails must move _with_ the mechanic

Warming provisions a real sandbox — a cost surface and an abuse surface. If `warm` is callable by any product but the quota/cap enforcement stays at the conversation layer, a non-PostHog-AI caller provisions sandboxes with no gate. So the quota dispatch and the warm-pool cap are **load-bearing parts of the generic action**, not optional decoration. This is the single most important correctness property of the spec.

### Rejected alternatives

- **A boolean `warm` flag on the existing `POST .../runs/` create action** instead of a dedicated `warm` action. Workable, but the create action (`api.py:1260`, _mapping_) is built for the cloud artifact-upload flow (create-without-starting, then `start` at `:1401`); overloading it with "create + start + idle + quota + idempotent-return-existing" muddies a method with different semantics. A dedicated `warm` action reads its own intent and keeps idempotency local.
- **Leaving prewarm in PostHog AI and copying it per product.** Rejected — that re-implements provisioning, quota, and the never-started timer N times and re-creates the leak risk below in each.

## Implementation steps

1. **Add `Task.OriginProduct.POSTHOG_AI`** if [G1](./G1-small-data-sandboxes.md) has not already landed it — the quota dispatch keys on it. (Coordinate with G1; do not add it twice.)

2. **Add the `warm` action** to `TaskRunViewSet` (`products/tasks/backend/api.py`, next to `resume_in_cloud` at `:2616` — the closest sibling shape):
   - `@action(detail=False, methods=["post"], url_path="warm", required_scopes=["task:write"])` on the runs collection (detail=False — it acts on the Task, returning a run). Schema-annotate with `@validated_request` / `@extend_schema` per `/improving-drf-endpoints` so generated types are correct; define `WarmRunResponseSerializer` (`run_id`, `status`, `just_created`) with `help_text` on every field.
   - **Idempotency first:** resolve the task's latest non-terminal run (`Task.latest_run` / a filtered query); if one exists, return it with `just_created=false`. This is what makes repeated warms (the debounced typing trigger fires many times) cheap.
   - **Quota dispatch:** a small registry `ORIGIN_PRODUCT_WARM_QUOTA: dict[OriginProduct, QuotaCheck]` mapping `POSTHOG_AI → AI_CREDITS` and `POSTHOG_CODE → posthog_code limit` (reuse `resume_in_cloud`'s checker), raising `QuotaLimitExceeded` (402) / `Throttled` (429) as the product dictates. A product with no registered gate either warms ungated or is rejected — **decide the default explicitly** (see open question 3).
   - **Warm-pool cap (state-derived, no counter):** the cap counts only _currently-warm_ runs — `for_team(team_id).filter(created_by=user, origin_product=…, status__in=NON_TERMINAL, state__await_user_message=True).count()` — with per-product defaults (PostHog AI: 2/user, 10/org, lifted from `MessageRoutingService.prewarm`). Reject over-cap with 429. **Do not maintain an increment/decrement counter** — deriving from state means every exit path decrements for free: a terminal run (released, self-cancelled, crashed) fails the `NON_TERMINAL` filter, and an activated run fails the `await_user_message` filter (see step 2a). Guard the count-then-create with the `SELECT FOR UPDATE` row-lock pattern `MessageRoutingService` already uses, so two debounced warms cannot both pass the cap and double-provision.
   - **Provision:** `Task.create_and_run` / `task.create_run` with `mode="interactive"`, `await_user_message=true`, no pending message, no attached context; dispatch `execute_task_processing_workflow(...)` via `transaction.on_commit` (the warm must not provision inside an atomic block — irreversible side effect, per CLAUDE.md).
   - Keep the action thin: extract the actual warm into a `products/tasks/backend/services/` helper (e.g. `warm_run(task, *, user)`), so both the HTTP action and an in-process caller (G11's conversation prewarm) share one implementation and cannot drift.

2a. **Mark the warm→active transition (the decrement that frees warm budget).** A warm run is "speculative" only until a human commits a message to it; from that point it is a normal active run governed by the AI-credit quota, not the warm-pool cap. Represent "speculative" with the same `state.await_user_message` flag the agent-server reads to idle (step 3), and **clear it at the moment a `user_message` is dispatched to the run** — in G11's `open(content)` activation branch (`signal_task_followup_message`) and in the relay's `user_message` handler (`api.py` command action). Clearing it is the only "decrement": the state-derived cap query in step 2 stops counting the run the instant the flag flips. Flip at dispatch time (Django-observable), not on an agent-server ack — once a human commits work the run is no longer speculative even if the dispatch later fails. Net: one flag partitions runs into warm (counts against the warm cap, spends no LLM tokens) vs active (counts against AI credits); the two budgets are disjoint by construction.

3. **Provisioner prerequisites (Twig / cloud-agent side)** — these were filed as PostHog-AI-specific open questions in `05_SANDBOX.md` §8 but become **cross-product contracts** the moment `warm` is generic. Resolve them as first-class agent-server behavior, not a Max hack:
   - **Idle-on-empty-initial-message** (`05_SANDBOX.md` §8.3 / open q10): the agent-server must boot the session and idle when all initial-message sources are empty, rather than erroring. The clean form is a `state.await_user_message: true` flag the `warm` action sets. **Without this, `warm` cannot work for anyone.**
   - **Never-started idle timer** (`05_SANDBOX.md` §8.1 / open q9): a warm run that reaches `in_progress` but never receives a `user_message` must self-cancel after a short interval (~60 s). Today's idle timer fires on `_posthog/turn_complete`, which a warm run never reaches — so an abandoned warm leaks a sandbox. As a generic capability this **must** exist provisioner-side (a new timer dimension, or a per-run `state.warm_only_timeout_seconds`), or any product can strand warm sandboxes.

4. **Repoint PostHog AI's prewarm at the shared helper** (this is the G11 seam, but the warm-pool/quota numbers move here in G10): `MessageRoutingService.prewarm()` becomes "ensure the Task exists + linked, then call `warm_run(task, user=...)`". The AI-credit gate and the 2/10 caps are now enforced inside `warm_run`, so the conversation layer stops duplicating them. `prewarm_release()` becomes `send_cancel(run, ...)` exactly as today (or, post-G11, the relay `cancel`).

5. **Generated types:** run `hogli build:openapi` so the `warm` action's serializer reaches the generated tasks client (`products/tasks/frontend/generated/api.ts`) and the core types. Do not hand-edit generated files.

## Files to change

| Path                                                                                            | Change                                                                                             |
| ----------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `products/tasks/backend/models.py`                                                              | `Task.OriginProduct.POSTHOG_AI` (if not already added by G1)                                       |
| `products/tasks/backend/api.py`                                                                 | New `warm` action on `TaskRunViewSet` + `@validated_request` annotations + response serializer     |
| `products/tasks/backend/services/` (new or existing)                                            | `warm_run(task, *, user)` helper: idempotency, quota dispatch, warm-pool cap, provision-on-commit  |
| `products/posthog_ai/backend/message_routing.py`                                                | `prewarm()` delegates to `warm_run(...)`; drop the now-shared AI-credit gate + 2/10 caps from here |
| Generated tasks client (`products/tasks/frontend/generated/*`, `frontend/src/generated/core/*`) | Regenerated by `hogli build:openapi` — do not hand-edit                                            |
| Twig agent-server (`packages/agent/src/server/agent-server.ts`)                                 | Idle-on-empty-initial-message (`await_user_message`); never-started warm timeout                   |

## Decisions & open questions

1. **`warm` action vs. a flag on `create`.**
   **Recommendation: dedicated `warm` action.** Distinct semantics (idempotent-return-existing, quota, idle) justify a distinct verb; the existing `create`/`start` pair keeps its artifact-upload meaning.

2. **`detail=False` (Task-level, returns a run) vs. `detail=True` on a pre-created run.**
   **Recommendation: `detail=False` on the runs collection** — the caller has a Task and wants "a warm run, creating one if needed." Idempotency (return the existing non-terminal run) is natural there; a `detail=True` warm would require the caller to create the run first, defeating the point.

3. **Default quota behavior for a product with no registered gate.**
   Two options: (a) reject (fail-closed — a product must opt in with a gate before it can warm), or (b) warm ungated. **Recommendation: (a) fail-closed.** Warming costs real compute; an unregistered product warming for free is a silent cost leak. New products register a gate explicitly. Document this in the action.

4. **Warm-pool caps — generic constant vs. per-product config.**
   **Recommendation: per-product defaults** (PostHog AI 2/10) with a generic fallback. Different workloads warrant different ceilings; hard-coding PostHog AI's numbers globally would constrain Code.

5. **Where does the never-started timeout live — provisioner default vs. per-run override?**
   **Recommendation: provisioner dimension keyed on `await_user_message`/`origin_product`, with a `state.warm_only_timeout_seconds` override escape hatch.** Owner: infra / agent-server. This is the highest-risk dependency (a missing timer leaks sandboxes across all products) — gate broad rollout on it.

6. **Should `prewarm_release` survive as a conversation endpoint, or collapse into the relay `cancel`?**
   **Resolved: collapse into the relay `cancel` verb.** Release is functionally `send_cancel(run)`, and the state-derived cap (step 2) needs **no decrement on release** — cancelling the run makes it terminal, which drops it from the `NON_TERMINAL` count automatically. The only requirement collapse imposes is that the client hold the warm run id, which G11's handle-returning openers provide (`warm` returns `{run_id, …}`). Releasing therefore inherits the same "command the latest run" caveat as the other control verbs (a stale id cancels a terminal run — a harmless no-op). G10 keeps `prewarm_release` as a thin alias until G11's frontend lands, then deletes it.

## Dependencies & sequencing

- **Within this pass:** `Task.OriginProduct.POSTHOG_AI` (step 1) → `warm_run` helper + action (step 2) → repoint PostHog AI prewarm (step 4) → regenerate types (step 5). The Twig prerequisites (step 3) are **parallel and gating for rollout, not for merge** — the Django action can land and be unit-tested with a mocked provisioner before the agent-server changes ship.
- **Cross-plan:** coordinate `Task.OriginProduct.POSTHOG_AI` with [G1](./G1-small-data-sandboxes.md). [G11](./G11-sandbox-logic-tasks-api-migration.md) consumes `warm_run` as the conversation prewarm backend and decides `prewarm_release`'s fate.
- **External prerequisite:** the two agent-server behaviors (step 3). Until they ship, `warm` only works for PostHog AI in the exact shape that already works; broad cross-product warming waits on them.

## Testing

- **`warm_run` helper (unit):** idempotent return of an existing non-terminal run (no second provision); fresh provision when none exists; quota dispatch raises the right error per `origin_product` (parameterized over `POSTHOG_AI`/`POSTHOG_CODE`/unregistered); warm-pool cap rejects over-limit; provisioning is dispatched via `on_commit`, not inside the atomic block.
- **Warm-count accounting (unit, the load-bearing correctness property):** the cap counts a warm run while `await_user_message` is set; after the activation flip (step 2a) the same run no longer counts, so a user at the cap who activates one warm can warm another; a terminal run (released via `cancel`, self-cancelled by the never-started timer, or crashed) drops from the count with no explicit decrement; two concurrent warms under the row lock cannot both pass the cap. Assert the warm partition and the active (AI-credit) partition never double-count the same run.
- **`warm` action (API test):** happy path (200 + run handle); over-quota → 402/429 with the product-appropriate message; over-cap → 429; another team's task → 404 (reuse the ownership pattern from `test_command_on_other_user_run_returns_404`); idempotent repeat returns the same run id.
- **PostHog AI prewarm equivalence:** assert `MessageRoutingService.prewarm()` post-refactor produces the same run shape as before and still no-ops when the current run is in-progress (mirror the existing prewarm tests).
- **Provisioner (Twig):** an empty-initial-message session boots + idles (no error); a warm run with no `user_message` self-cancels after the timeout. Covered in Twig's agent-server suites; this pass only verifies, except where the `await_user_message` flag is newly wired.
- **Type drift:** after `hogli build:openapi`, assert no uncommitted generated diff (CI's generated-types check).

## Rollout / flagging

- Gate the **cross-product warm callers** (Code, Signals) behind their own product flags as they adopt `warm`. The **action itself** is harmless until called with a registered gate (fail-closed default), so it can ship unflagged.
- PostHog AI's prewarm is already behind the sandbox rollout flag; the refactor (step 4) is behind no new flag — it is a backend-internal repoint with identical external behavior.
- **Telemetry:** emit a capture on warm request + outcome (warmed / returned-existing / over-quota / over-cap / failed), tagged `task_id`, `run_id`, `origin_product`, outcome — mirroring `05_SANDBOX.md` §8 open q8 (prewarm latency). This lets us watch warm adoption and the abandon/leak rate before widening.
- **Hard gate for broad rollout:** the never-started idle timer (decision 5). Do not enable cross-product warming until abandoned warms are proven to self-cancel.

## Effort & risk

**Effort: M.** One action + one shared service helper + a small quota registry on the Django side; the heavy lifting (provisioning, SSRF-guarded transport, connection JWT) already exists. The agent-server prerequisites are the larger unknown.

**Risks:**

- **Sandbox leak via abandoned warms** — the dominant risk; mitigated only by the never-started timer (decision 5). Treat as a rollout gate.
- **Ungated cost leak** — mitigated by the fail-closed quota default (decision 3) and the per-product registry.
- **Idempotency races** — two debounced warm POSTs landing together could double-provision; mitigate with the same row-level lock pattern `MessageRoutingService` already uses for follow-ups (`SELECT FOR UPDATE` on the Task), or a unique non-terminal-run guard.
