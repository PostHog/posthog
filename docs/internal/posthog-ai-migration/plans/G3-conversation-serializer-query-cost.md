# get_task extra query + latest_run full-scan + request-level N+1 in the conversation serializer

> **Source:** outstanding*items.md § 3 (Item 3) · **Locus:** backend — serializer + models
> **Effort:** S (small, but touches a shared model property with cross-product callers — read the bulk-load finding before editing) · **Priority:** Medium-high · **Blocks rollout:** No
> **Joins:** Standalone backend pass. Two distinct costs that happen to chain through the same code path (the conversation `retrieve` serializer → `Conversation.current_run` → `Task.latest_run`): (1) `latest_run` materializing every run row to pick the newest, and (2) a request-level N+1 created by the \_design* — the list payload omits the bootstrap handle, so the frontend must `retrieve` each conversation to open its sandbox stream. Both are fixed here because they share the same serializer + model locus; nothing else folds in.

## Problem

A PostHog AI conversation that runs on the sandbox runtime is backed by a `products/tasks` `Task`, and each user turn appends a `TaskRun` row to that Task. To open (or reconnect to) the sandbox SSE stream, the frontend needs two IDs: the backing `Task.id` and the _current_ (latest) `TaskRun.id`. These are surfaced by the conversation serializer's `task` field.

Two separate costs exist today:

1. **`latest_run` materializes every run.** Resolving the current run walks `Conversation.current_run` → `Task.latest_run`, and `latest_run` does `list(self.runs.all())` and picks the max `created_at` in Python. For a long conversation (every follow-up adds a run row) this loads all N runs just to return the newest one. We only ever need the single newest row.

2. **Request-level N+1 by design.** The conversation **list** endpoint uses `ConversationMinimalSerializer`, which omits the `task` field entirely. So when the frontend restores history (the side-panel conversation list), it gets no bootstrap handle from the list and must issue a separate `retrieve` per sandbox conversation just to learn each one's `task.current_run_id` before it can open the stream. That is N retrieves for N conversations — the N+1 the omission invites, one layer up from the ORM.

This was originally flagged as a classic list-level ORM N+1. It is **not** that: the list serializer never calls `get_task` (the `:142-144` comment claiming "never hit on `list`" is **accurate** — verified, see below). The two real costs are the per-row run materialization and the per-conversation retrieve.

## Current behavior (verified)

All citations below were opened and confirmed on 2026-06-13. Several line numbers in the triage doc had drifted; corrected ranges are given here and in the citation-corrections list.

**Serializer (`ee/hogai/api/serializers.py`):**

- `get_task` is at **`:140-151`** (doc said `:140-152`). The inline comment claiming the extra query is "acceptable on single retrieve, never hit on `list`" is at **`:142-144`** and is **accurate** — `list` uses `ConversationMinimalSerializer` (below), which has no `task` field, so `get_task` is never invoked on the list path. Body: `current_run = conversation.current_run` (`:147`), returns `{"id": str(conversation.task_id), "current_run_id": str(current_run.id) if current_run else None}` (`:148-151`).
- The sub-serializer `ConversationSandboxTaskSerializer` is at **`:47-58`**; its `current_run_id` field (the field we will feed on the list path) is at **`:55-58`** (doc said `:55-58` — correct).
- `ConversationMinimalSerializer` (`:61-67`) declares only `_conversation_fields` (`:22-34`) — **no `task`, no `current_run_id`**. `ConversationSerializer` (`:70-99`) extends it and adds `task = serializers.SerializerMethodField()` (`:99`), wired to `get_task` via `@extend_schema_field(ConversationSandboxTaskSerializer(allow_null=True))` (`:140`).

**Model hops:**

- `Conversation.current_run` is a `@property` at **`products/posthog_ai/backend/models/assistant.py:147-152`** (doc said `:147-152` — correct). It returns `None` when `self.task is None`, else `task.latest_run`.
- `Task.latest_run` is a `@property` at **`products/tasks/backend/models.py:240-247`** (doc said `:240-247` — correct). Body: `runs = list(self.runs.all()); return max(runs, key=lambda r: r.created_at) if runs else None`. The comment at `:242-243` documents the intent: _"Use `.all()` which respects prefetch_related cache, then sort in Python. This avoids N+1 queries when tasks are loaded with `prefetch_related('runs')`."_
- `TaskRun.Meta.ordering = ["-created_at"]` (`products/tasks/backend/models.py:628`) — the relation's default ordering already returns newest-first.

**List path (`ee/api/conversation.py`):**

- `safely_get_queryset` is at `:309-327`. It does `select_related("user")` (`:310`), filters/orders by `-updated_at` (`:324`), and — for the `list` action only — defers heavy fields at **`:325-326`** (doc said `:325-326` — correct): `queryset.defer("approval_decisions", "messages_json", "sandbox_task_id", "sandbox_run_id")`.
- `get_serializer_class` is at `:397-404`; the `list` action returns `ConversationMinimalSerializer` at **`:402-403`** (doc said `:402-403` — correct). `retrieve` falls through to `super()` → the full `ConversationSerializer`.
- A second `current_run` consumer lives at **`ee/api/conversation.py:819`** (the `permission` action: `task_run = conversation.current_run`) — single-object path, benefits from fix #1 for free.

**Cross-product callers of `Task.latest_run` (the decisive finding — see Decisions):**

- **`products/tasks/backend/serializers.py:185-189`** — `TaskSerializer.get_latest_run` calls `obj.latest_run` directly. `TaskSerializer` is the `serializer_class` for the main `TaskViewSet` (`products/tasks/backend/api.py:365`), whose list/retrieve queryset does **`prefetch_related("runs")`** (`products/tasks/backend/api.py:722-724`). This is a **bulk-load caller that deliberately relies on the prefetch cache** — the exact case the `latest_run` comment protects. A bare `.first()` here would fire one fresh query per task row, reintroducing an N+1 on the tasks list endpoint.
- Other in-process single-object callers that don't prefetch and are unaffected: `products/posthog_ai/backend/message_routing.py:256,358`; `ee/hogai/sandbox/executor.py:160`; `products/tasks/backend/max_tools.py:214,297,379`; `posthog/temporal/ai/posthog_code_slack_mention.py:1043`; `products/tasks/backend/temporal/code_workstreams/activities/rebuild_workstreams.py:52,146`; `products/tasks/backend/services/custom_prompt_internals.py:115`.
- Note: `TaskSummarySerializer.get_latest_run` (`products/tasks/backend/serializers.py:877-879`) does **not** use the property — it reads a `_latest_run` Subquery annotation. The annotation that feeds it is built in the `summaries` POST action at `products/tasks/backend/api.py:457-465` (there's a sibling `_latest_run_status` subquery at `:700-702` in the list queryset). Both correlate via `OuterRef("pk")` because their outer queryset is `Task`. Mirror this shape for fix #2, but correlate via `OuterRef("task_id")` since the conversation list's outer queryset is `Conversation` (whose FK to Task is `task` → column `task_id`), not `Task` itself.

**Frontend touch-point (where the per-conversation retrieve happens):**

- `frontend/src/scenes/max/maxThreadLogic.tsx:2025-2033` bootstraps the sandbox stream from `conversation.task.current_run_id` / `conversation.task.id`. The `conversation` object comes from `maxGlobalLogic`'s `conversationHistory`.
- `frontend/src/scenes/max/maxGlobalLogic.tsx`: `loadConversationHistory` (`:111-125`) calls `api.conversations.list()` (`:118`) → list payload (no `task`); `loadConversation` (`:127-139`) calls `api.conversations.get(id)` (`:128`) → full retrieve (has `task`). `mergeConversations` (`frontend/src/scenes/max/maxLogic.tsx:1019-1032`) merges a list item into an existing detail while preserving `messages` — so a list item that _carries_ `task` flows straight through.
- API client: `api.conversations.list()` returns `PaginatedResponse<Conversation>` (`frontend/src/lib/api.ts:6710-6712`); `api.conversations.get()` returns `ConversationDetail` (`:6714-6716`). The handwritten `Conversation` type (`frontend/src/types.ts:7055-7079`) **already** declares `task?: { id: string; current_run_id: string | null } | null` (`:7078`) — so surfacing `task` on the list payload needs **zero** frontend type changes.

## Approach

Two independent fixes, both backend-only.

### Fix 1 — make `latest_run` cheap _without_ breaking prefetch reuse

Because a bulk-load caller (`TaskSerializer` + `prefetch_related("runs")`) genuinely depends on the prefetch-cache shape, **do not** replace the property body with a bare `.order_by("-created_at").first()` — that would issue a fresh query per task and regress the tasks list endpoint. Instead, keep the property prefetch-friendly but make it cheap in _both_ states:

- If the `runs` relation is already prefetched (cache populated), reuse the cache exactly as today (max-in-Python over the in-memory list — already cheap, the rows are loaded).
- If it is **not** prefetched, issue a single ordered `.order_by("-created_at").first()` instead of `list(self.runs.all())` + Python max.

This is detectable via Django's prefetch cache: `"runs" in self._prefetched_objects_cache`. Concretely:

```python
@property
def latest_run(self) -> Optional["TaskRun"]:
    # When runs are prefetched (e.g. the tasks list endpoint does
    # prefetch_related("runs")), reuse the cache to avoid an N+1.
    if "runs" in getattr(self, "_prefetched_objects_cache", {}):
        runs = list(self.runs.all())
        return max(runs, key=lambda r: r.created_at) if runs else None
    # Otherwise fetch only the newest row (TaskRun.Meta.ordering is "-created_at",
    # but order explicitly so the query is correct regardless of model default).
    return self.runs.order_by("-created_at").first()
```

This satisfies the doc's "first check other callers; the current shape is deliberately prefetch-friendly" requirement and the open question "are there bulk-load callers that rely on the prefetch cache?" — **yes, there is one** (`TaskSerializer`), so we keep the prefetch branch and only optimize the non-prefetched branch. The serializer `get_task` path (single conversation, no prefetch) takes the cheap `.first()` branch, dropping from "load N runs" to "load 1 row." Behavior is identical (same newest-by-`created_at` row); only the query cost changes.

**Rejected alternative — bare `.first()`:** simplest, but regresses the tasks list endpoint's prefetch reuse into an N+1. Explicitly not chosen.

**Rejected alternative — push a `Max(created_at)` / Subquery annotation into every caller:** correct but invasive — it would require touching every single-object caller (`message_routing`, `executor`, `max_tools`, the slack-mention temporal, etc.), far beyond an S-sized change. The annotation approach is used only where it's already idiomatic and bulk (fix #2's list queryset).

### Fix 2 — surface `current_run_id` on the list payload (kill the request-level N+1)

Add the `task` handle to the **list** path so the frontend gets each conversation's bootstrap IDs from the single list call, eliminating the per-conversation `retrieve`.

- Annotate the list queryset (in `safely_get_queryset`, `list` branch) with a correlated subquery for the latest run id, mirroring the existing `products/tasks/backend/api.py:457-465` pattern:

  ```python
  from django.db.models import OuterRef, Subquery  # module-level import

  latest_run = TaskRun.objects.filter(task=OuterRef("task_id")).order_by("-created_at")
  queryset = queryset.annotate(current_run_id=Subquery(latest_run.values("id")[:1]))
  ```

  `OuterRef("task_id")` (the conversation's FK column to Task), **not** `OuterRef("pk")` — the tasks-api patterns use `pk` only because their outer queryset is `Task`; here it's `Conversation`. The alias `current_run_id` does not collide with any `Conversation` model field (the model has `sandbox_run_id` / `sandbox_task_id` and a `current_run` _property_, but no `current_run_id` column), so the annotation is safe and `get_task` reads it via `getattr(conversation, "current_run_id", None)`. This adds **one** subquery to the list SQL — constant, not per-row — and yields `None` for LangGraph conversations (no `task`) automatically.

- Add a `task` field to `ConversationMinimalSerializer` that reads `conversation.task_id` + the annotated `current_run_id`, reusing the existing `ConversationSandboxTaskSerializer` shape so the wire contract stays identical between list and retrieve. Implement it as a `SerializerMethodField` annotated with `@extend_schema_field(ConversationSandboxTaskSerializer(allow_null=True))` (so the generated TS keeps the `{ id, current_run_id }` shape and the existing handwritten `Conversation.task` type still matches):

  ```python
  task = serializers.SerializerMethodField()

  @extend_schema_field(ConversationSandboxTaskSerializer(allow_null=True))
  def get_task(self, conversation: Conversation) -> dict[str, Any] | None:
      if conversation.task_id is None:
          return None
      return {
          "id": str(conversation.task_id),
          "current_run_id": (str(crid) if (crid := getattr(conversation, "current_run_id", None)) else None),
      }
  ```

  Because this `get_task` reads `conversation.task_id` (already on the row, no extra query) and the **annotated** `current_run_id` (resolved by the single subquery in the list SQL), the list path stays at a constant query count regardless of conversation count. It never touches `current_run` / `latest_run`, so it cannot regress.

- The full `ConversationSerializer.get_task` (retrieve path) is left as-is functionally but now benefits from Fix 1's cheaper `latest_run`. Optionally, the retrieve queryset could carry the same annotation, but retrieve is single-object so it's not required; keep retrieve on the property to avoid duplicating the annotation in the viewset's non-list path.

**Naming caution (per `/improving-drf-endpoints`):** the annotation alias `current_run_id` is a plain `UUIDField`-shaped subquery and is consumed only inside `get_task` — it is **not** itself a serializer field, so it won't collide in OpenAPI. The serializer field stays named `task` (typed by `ConversationSandboxTaskSerializer`), which is already in the generated schema. No new enum-collision-prone field names (`status`/`type`/`mode`/...) are introduced.

**Frontend:** essentially zero. The `Conversation` type already has `task` (`frontend/src/types.ts:7078`), and `mergeConversations` preserves it. The only consideration is whether `maxThreadLogic` still needs the `loadConversation` retrieve at all for the bootstrap — see Decisions; the safe shipping cut is to leave the existing retrieve in place (it now becomes redundant for the bootstrap handle but still loads `messages` for LangGraph threads) and let a follow-up remove the redundant retrieve once we confirm the list handle is sufficient.

## Implementation steps

1. **Fix 1 — `Task.latest_run`** (`products/tasks/backend/models.py:240-247`): replace the unconditional `list(self.runs.all())` + Python-max with the prefetch-aware branch (prefetched → cache + max-in-Python; not prefetched → `.order_by("-created_at").first()`). Preserve the existing explanatory comment and extend it to note the non-prefetched fast path. Keep the return type `Optional["TaskRun"]`.
2. **Fix 2a — list annotation** (`ee/api/conversation.py`, `safely_get_queryset`, the `if self.action == "list":` branch at `:325-326`): add `from django.db.models import OuterRef, Subquery` at module level, then annotate the list queryset with `current_run_id=Subquery(TaskRun.objects.filter(task=OuterRef("task_id")).order_by("-created_at").values("id")[:1])`. Import `TaskRun` from `products/tasks/backend/models` at module level (verify no circular import — `ee/api/conversation.py` already imports from `products` heavily; if a cycle appears, move the `TaskRun` reference behind the existing tasks import block).
3. **Fix 2b — minimal serializer** (`ee/hogai/api/serializers.py`, `ConversationMinimalSerializer` at `:61-67`): add a `task = serializers.SerializerMethodField()` plus a `get_task` reading `conversation.task_id` and the annotated `current_run_id`, decorated `@extend_schema_field(ConversationSandboxTaskSerializer(allow_null=True))`. **Expose `task` by overriding the minimal serializer's `Meta.fields` to `[*_conversation_fields, "task"]` — do NOT add `"task"` to the shared `_conversation_fields` list.** `ConversationSerializer.Meta.fields` already spreads `*_conversation_fields` _and_ appends `"task"` explicitly (`:73-82`), so adding `task` to `_conversation_fields` would list it twice and raise a DRF duplicate-field error. Because `ConversationSerializer` redefines both `task = SerializerMethodField()` (`:99`) and its own `get_task` (`:140-151`), the subclass's `get_task` (which resolves `current_run`) still wins on retrieve — Python/DRF MRO. Verify the full serializer's `Meta.fields` does not need `task` removed (it must keep it; it's declared once there).
4. **Regenerate OpenAPI types**: run `hogli build:openapi`. The `task` field already exists on the retrieve schema; this confirms the list operation now also exposes it. Verify the handwritten `frontend/src/types.ts:7078` shape still matches (it should — same `ConversationSandboxTaskSerializer`).
5. **Tests** — add query-count regression tests (see Testing) for both fixes.
6. **Frontend (optional, follow-up):** confirm `maxThreadLogic` can bootstrap from the list-provided `task` without the `loadConversation` retrieve; if so, drop the redundant retrieve from the sandbox reconnect path. Out of scope for the core fix; track separately.
7. Lint: `ruff check . --fix && ruff format .` (Python); `pnpm --filter=@posthog/frontend typescript:check` only if step 6 is done.

## Files to change

| Path                                                                                                        | Change                                                                                                                                           |
| ----------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `products/tasks/backend/models.py` (`Task.latest_run`, `:240-247`)                                          | Prefetch-aware: reuse cache when `runs` is prefetched, else `.order_by("-created_at").first()`.                                                  |
| `ee/api/conversation.py` (`safely_get_queryset`, `:325-326`; module imports)                                | Add `OuterRef`/`Subquery`/`TaskRun` imports; annotate list queryset with `current_run_id` subquery.                                              |
| `ee/hogai/api/serializers.py` (`ConversationMinimalSerializer`, `:61-67`; `_conversation_fields`, `:22-34`) | Add `task` SerializerMethodField + `get_task` reading annotated `current_run_id`; expose `task` in minimal serializer fields.                    |
| `ee/hogai/api/test/test_serializers.py`                                                                     | Add: minimal serializer exposes `task` with annotated `current_run_id`; `latest_run` query-count regression.                                     |
| `ee/api/test/test_conversation.py` (or the existing conversation viewset test module)                       | `assertNumQueries` on the list endpoint stays constant as conversation count grows (no per-conversation run query).                              |
| `products/tasks/backend/tests/test_api.py`                                                                  | Guard: tasks list endpoint with `prefetch_related("runs")` still issues no per-task run query (proves Fix 1 didn't regress the prefetch caller). |
| `frontend/src/generated/**` (auto)                                                                          | Regenerated by `hogli build:openapi` — do not hand-edit.                                                                                         |

## Decisions & open questions

1. **Are there bulk-load callers of `Task.latest_run` that rely on the prefetch cache?** **Resolved: yes — exactly one.** `TaskSerializer.get_latest_run` (`products/tasks/backend/serializers.py:185-189`) under `TaskViewSet`'s `prefetch_related("runs")` queryset (`products/tasks/backend/api.py:722-724`). **Recommendation (chosen):** keep the property prefetch-friendly via the `_prefetched_objects_cache` branch; only the non-prefetched path gets the `.first()` optimization. Do **not** use a bare `.first()`.

2. **Annotation vs. `.first()` for `latest_run`.** **Recommendation:** the hybrid prefetch-aware property (Fix 1) — it's the minimal change that helps the serializer path without rewriting every caller and without an annotation that single-object callers can't use. A queryset-level `Max`/Subquery annotation is reserved for the bulk list path (Fix 2), where it's already idiomatic.

3. **Where does `current_run_id` live on the list serializer — reuse `task` or add a flat field?** **Recommendation (chosen):** reuse the existing `task` shape via `ConversationSandboxTaskSerializer`, so list and retrieve return the identical `{ id, current_run_id }` object and the handwritten `Conversation.task` TS type needs no change. Adding a separate flat `current_run_id` top-level field would diverge the contract and require a new frontend field.

4. **Should the frontend drop the per-conversation `retrieve` once the list carries `task`?** **Recommendation:** ship the backend fix first (it makes the data available); treat the frontend retrieve removal as a fast-follow once verified, because `loadConversation` also fetches LangGraph `messages` and the reconnect path has subtleties (`maxThreadLogic.tsx:2001-2002` only loads when `threadRaw` is empty). Do not couple the two PRs.

5. **Add a compound `(task, created_at)` index on `TaskRun`?** Currently only the FK index on `task` exists (`TaskRun.Meta.indexes` at `:629-639` has no such index; ordering default is `-created_at`). For the per-conversation subquery the row counts are small, so the FK index + sort is adequate. **Recommendation:** do **not** add an index in this pass; revisit only if production query plans show the subquery hot. If added later, it must follow `/django-migrations` (concurrent, non-blocking) — out of scope here.

## Dependencies & sequencing

- **Self-contained backend pass.** No dependency on sibling plans for correctness.
- Cross-references (no scope overlap, just adjacency):
  - **G1-small-data-sandboxes.md** — touches `products/tasks` sandbox provisioning, not the run/serializer query path; independent.
  - **G2-cancel-bail-button.md** — frontend composer state; touches `maxThreadLogic` but a different listener (`stopGeneration`), not the bootstrap/`loadConversation` path. If both land near the same time, expect a trivial `maxThreadLogic.tsx` merge only if Decision 4's follow-up is done concurrently.
  - **G4-legacy-history-conversion.md** — also reasons about `current_run` / sandbox bootstrap but at the history-conversion layer; this plan's cheaper `latest_run` and list handle are upstream conveniences, not blockers.
- Within this pass: Fix 1 and Fix 2 are independent and can be separate commits; Fix 2b (serializer) depends on Fix 2a (annotation) being present for the field to populate, so land them together.

## Testing

- **Unit — `latest_run` correctness (`ee/hogai/api/test/test_serializers.py` already has `test_task_reports_latest_run` at `:339-347`):** keep it green (newest run returned). Add a parameterized case covering the prefetched and non-prefetched branches return the same row.
- **Query-count — `latest_run` non-prefetched fast path:** create a Task with N runs (e.g. 5), then `with self.assertNumQueries(1): task.latest_run` — proves it no longer loads all rows via a full-relation fetch + Python max (it's still 1 query, but assert it doesn't grow and assert the returned id is the newest). Pair with a prefetched case: load the task with `prefetch_related("runs")`, then `with self.assertNumQueries(0): prefetched_task.latest_run` to prove cache reuse.
- **Query-count — tasks list endpoint regression (`products/tasks/backend/tests/test_api.py`):** there's an existing `test_list_tasks_includes_latest_run` (`:749`). Wrap the list call in `assertNumQueries` and assert it stays constant as you add a second task with multiple runs — proves Fix 1 preserved the `prefetch_related("runs")` cache reuse (no per-task run query).
- **Query-count — conversation list N+1 (`ee/api/test/test_conversation.py`):** create several sandbox conversations each with a backing Task + runs; GET the list endpoint inside `assertNumQueries(constant)` and assert the count does **not** scale with conversation count (the latest-run subquery is one annotation, not one query per row). Assert each list item now carries `task.current_run_id` equal to the newest run id, and that LangGraph conversations report `task: null`.
- **Serializer field — minimal serializer exposes `task`:** assert `ConversationMinimalSerializer` output (via the list endpoint) includes the `{ id, current_run_id }` shape, matching the retrieve serializer.
- **No new jest/playwright required** for the backend-only fix. If Decision 4's frontend follow-up is done, add a `maxThreadLogic` jest test asserting bootstrap from list-provided `task` without a `loadConversation` retrieve.

## Rollout / flagging

n/a — pure performance/correctness fix behind no new behavior. The wire contract is unchanged for retrieve and strictly additive for list (`task` was previously absent and is now present with the same shape the frontend type already expects). No feature flag, no telemetry change. Sandbox vs. LangGraph branching is already encoded in `agent_runtime` and `task` being null for LangGraph rows.

## Effort & risk

- **Effort: S.** Three small backend edits + tests; OpenAPI regen is mechanical; frontend type already matches.
- **Risks:**
  - _Regressing the prefetch caller_ — the single real footgun. Mitigated by the `_prefetched_objects_cache` branch in Fix 1 and the explicit tasks-list query-count regression test. Do not skip that test.
  - _Subquery correctness for LangGraph rows_ — `OuterRef("task_id")` on a null FK yields no rows → `None`; covered by the "LangGraph reports task: null" assertion.
  - _Duplicate-field declaration_ — moving `task` into the minimal serializer while the full serializer also declares it; verify no DRF "field declared twice" error and that the full serializer's `get_task` (which resolves `current_run` for the single-object retrieve) still takes precedence on retrieve.
  - _Circular import_ of `TaskRun` into `ee/api/conversation.py` — low (the module already imports from `products`), but verify at module load.
