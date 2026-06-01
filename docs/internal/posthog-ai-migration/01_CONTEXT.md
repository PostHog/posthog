# 01 — Context migration

The new context model is intentionally small. Previously we pre-computed and serialized rich `MaxUIContext` payloads because not every entity referenced in a conversation was reachable via a tool. That constraint no longer holds — the sandbox agent has data tools for every entity type we care about — so context becomes a flat list of references that the agent fetches on demand.

This rewrite supersedes the earlier hybrid (`A/B/C/D`) proposal. There is **one** delivery channel: per-message attachment. There is **no** mid-Run refresh, **no** `posthog-context` MCP server, **no** systemPrompt-side context injection, **no** core memory, **no** dynamic tool injection.

---

## 1. The model

A user message carries an optional list of typed attachments. The Django `POST /sandbox/` handler (`products/posthog_ai/backend/message_routing.py` — see [`02_CORE.md`](./02_CORE.md) § 4) wraps the message with a `<posthog_context>` block — on both first messages and follow-ups — and forwards the wrapped text into the `products/tasks` Task/Run in-process (direct Python calls, no HTTP-to-self). The frontend never sees the wrapped form on its own outbound requests; it speaks `/conversations/*` as today and just adds an `attached_context` field to the request body.

```ts
interface AttachedContext {
  type: 'dashboard' | 'insight' | 'event' | 'action' | 'error_tracking_issue' | 'evaluation' | 'notebook' | 'text'
  id?: string | number // entity types
  name?: string // optional human label for entity types
  value?: string // type === 'text'
}
```

The wrapped message the agent sees:

```text
<posthog_context>
The user attached the following PostHog entities. Use the appropriate tools to retrieve their details only if relevant to the request.
- Dashboard #123 ("Marketing Funnel")
- Insight #abc-def ("Daily Signups")
- Error tracking issue #019249ab-... ("TypeError in checkout flow")
- Free text: "I think this regressed in last Thursday's deploy"
</posthog_context>

<user's actual message>
```

That's the whole contract. No JSON, no schema the agent has to parse — the wrapper renders to a deterministic Markdown-ish text block. The agent calls `read_dashboard(123)` / `read_insight("abc-def")` / etc. as it judges useful.

### Why this works now

| Old reason for pre-computation                                | Current state                                                                                                                                 |
| ------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| Some entity types had no read tool — agent couldn't fetch     | Every entity type listed above is covered by an inner tool of the single-exec `posthog` MCP server (see `04_PROMPTS.md` § 5)                  |
| Token cost of an extra round-trip per dashboard mattered      | Tool-call round-trips are cheap relative to model latency; pre-loading every dashboard the user might mention is wasteful when most go unused |
| The LangGraph node graph needed deterministic prompt assembly | The sandbox agent decides its own tool sequence — pre-fetching steals decisions from it                                                       |

---

## 2. What gets removed

| Concept (in the old spec / old code)                                                                                       | Disposition                                                                                                                                                                                                |
| -------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Pre-interpolated `MaxUIContext` payloads (dashboards-with-tiles, insights-with-query, events-with-properties)              | **Gone.** Replaced by IDs the agent fetches via tools.                                                                                                                                                     |
| `posthog-context` MCP server proposal                                                                                      | **Gone.** General data tools (`read_dashboard`, `read_insight`, ...) cover it.                                                                                                                             |
| Static team-scope injection into `systemPrompt` (groups, billing, core memory)                                             | **Gone.** Already accessible via MCP — no need to duplicate in the system prompt.                                                                                                                          |
| Core memory (`/remember`, `ManageMemoriesTool`)                                                                            | **Dropped entirely** for the new PostHog AI. Not migrated.                                                                                                                                                 |
| Mid-Run context refresh (`set_config_option("posthog_active_context", …)`, `_posthog/refresh_session` for context updates) | **Gone.** Context is static per message. To change context, attach to the next message.                                                                                                                    |
| Dynamic tool injection (`useMaxTool` registering scene-specific tools at mount time)                                       | **Gone.** Only the static MCP tool set is available. If a scene needs to act on Max output, it does so reactively (subscribe to the new logic's outputs), not by registering a callback the agent invokes. |
| Two-channel hybrid (static slice in `systemPrompt` + per-turn block)                                                       | **Collapsed.** Single channel: per-message `<posthog_context>` wrapper.                                                                                                                                    |
| `compiledContext` selector merging scene + manual contexts into a `MaxUIContext` object                                    | Replaced by a flat `attachedContext: AttachedContext[]` reducer. No "compilation".                                                                                                                         |
| `createMaxContextHelpers.dashboard(dashboard)` (takes the full Dashboard object and serializes)                            | Replaced by `attach({ type: 'dashboard', id, name })` — just IDs and labels.                                                                                                                               |
| `maxBillingContextLogic`                                                                                                   | **Delete.** Billing data, when needed, is exposed via the billing MCP tool.                                                                                                                                |

---

## 3. Frontend design

> **Coexistence mode** (per [`BACKWARD_COMPAT.md`](./BACKWARD_COMPAT.md) #1, #2). The existing `maxContextLogic.ts` stays untouched for LangGraph users — its `maxContext` selector contract on the 3 scene logics is preserved verbatim. Sandbox context lives in a **new** sibling logic at `frontend/src/scenes/max/posthogAiContextLogic.ts`. The two coexist for the entire rollout. The simplification described in this section is the _end state_ (post default-on); during the soak only the new file is added.

The new `posthogAiContextLogic.ts` holds **one flat `attachments` reducer** plus a thin scene-pull listener that _reads_ the existing 3 scenes' `maxContext` selectors and **projects** their rich `MaxContextInput[]` items down to flat `AttachedContext[]` at consumption time. Zero scene-side edits — the scenes keep returning their existing rich shapes.

Items added by the scene listener and items added by the user via TaxonomicFilter are **the same kind of thing** — there's no "source" attribute, no manual-vs-scene split, no separate persistence policy. The same entity arriving from both channels is one item.

### 3.1 The new `posthogAiContextLogic.ts`

```ts
interface PostHogAiContextLogicValues {
  attachments: AttachedContext[]
  chipsForDisplay: { key: string; label: string; icon: ReactNode; onRemove: () => void }[]
}

interface PostHogAiContextLogicActions {
  attach: (item: AttachedContext) => void // dedup-add; called by scene sync AND TaxonomicFilter
  detach: (key: string) => void // key = `${type}:${id ?? value}`
  clearAttachments: () => void // convenience reset (e.g. on new conversation)
  syncSceneAttachments: () => void // router listener; calls attach() for each projected scene item
}
```

State is per-thread (per `maxThreadLogic` instance — see `02_CORE.md`). **Nothing clears on send** — attachments persist across messages. Cross-message dedupe of the rendered `<posthog_context>` block happens server-side — see § 4.3.

### 3.2 The scene `maxContext` selector contract — fully preserved

The 3 scenes that expose `maxContext` today (dashboard, insight, project homepage — confirmed by `grep -rn "maxContext\b" frontend/src/scenes/`) **keep returning `MaxContextInput[]`** verbatim, exactly as today. The sandbox logic does the projection at consumption time:

```ts
// inside posthogAiContextLogic, syncSceneAttachments listener
const sceneItems: MaxContextInput[] = activeSceneLogic.values.maxContext ?? []
for (const item of sceneItems) {
  const projected = projectToAttachedContext(item)
  if (projected) actions.attach(projected)
}
```

Where `projectToAttachedContext()` is a one-screen helper that strips the rich nested data and emits a flat `{ type, id, name? }` record per entity. The `attach` reducer dedupes on `(type, id ?? value)` so calling it for an item the user already pinned (or that the scene already contributed) is a no-op. This is the **only** new code touching the existing scene-context contract — and it lives in the new file, not in the existing logic. Zero edits to `maxContextLogic.ts`, `dashboardLogic.tsx`, `insightSceneLogic.tsx`, or `projectHomepageLogic.tsx`.

Today's selector (unchanged during the migration):

```ts
maxContext: [
  (s) => [s.dashboard],
  (dashboard): MaxContextInput[] => {
    if (!dashboard) return []
    return [createMaxContextHelpers.dashboard(dashboard)] // serializes nested tiles
  },
]
```

The sandbox logic reads this and projects:

```ts
// posthogAiContextLogic.ts — at consumption time
function projectToAttachedContext(item: MaxContextInput): AttachedContext | null {
  if (item.type === MaxContextType.DASHBOARD) {
    return { type: 'dashboard', id: item.data.id, name: item.data.name }
  }
  // ... one branch per existing MaxContextType
}
```

This stays a one-way street: existing scenes ignore the sandbox runtime entirely; the sandbox runtime adapts the existing shapes.

### 3.3 Chip UI

`Context.tsx` keeps its visual role. The component branches on `conversation.agent_runtime`:

- `'langgraph'` → renders chips from `maxContextLogic.values.contextOptions` (today's behavior, unchanged).
- `'sandbox'` → renders chips from `posthogAiContextLogic.values.chipsForDisplay`. The X on each chip dispatches `detach(key)` — no source distinction; one removal path.

The taxonomic-filter "add context" affordance also branches the same way. Same TaxonomicFilter component, same group types; the dispatched action differs (`maxContextLogic.handleTaxonomicFilterChange` vs `posthogAiContextLogic.attach`).

### 3.6 Wrapped-message visibility (debug)

By default the user sees only their typed text on each message bubble — the `<posthog_context>` block the agent actually receives is **not** rendered in the thread. For internal devs debugging "what did the agent see?", a feature-flag-gated `Show context sent to Max` toggle expands an inline preview that calls `GET /api/environments/{tid}/conversations/{id}/preview_wrap/?content=…&attached_context=…` and renders the returned string. The endpoint is a thin wrapper around `wrap_user_message` so the rendered template never duplicates into TypeScript — see § 4.3.

The toggle is gated by a separate internal flag (e.g. `phai-sandbox-debug`) so external users never see the raw wrapper text. The preview endpoint is read-only and stateless.

### 3.4 Lifecycle (sandbox runtime)

- **On scene mount or scene change**: router listener calls `posthogAiContextLogic.syncSceneAttachments`, which projects every item in `activeSceneLogic.values.maxContext` and calls `attach()` for each. Already-attached items are no-ops (dedup on `(type, id ?? value)`). Items the user previously `detach`ed in _this scene_ won't re-appear unless they navigate away and back — re-navigation is the explicit signal that the scene's contribution should re-assert.
- **On user attach via TaxonomicFilter / @-mention**: same `attach(item)` dispatch — no separate manual reducer, no separate persistence policy.
- **On user remove (X on chip)**: dispatches `detach(key)`. Sticks for the rest of the current scene view.
- **On message send** (in `maxThreadLogic`, sandbox branch):
  1. Snapshot current `posthogAiContextLogic.values.attachments`.
  2. Build the request payload (see § 3.5) with the full list — server-side handles cross-message dedupe of the rendered prompt block (§ 4.3).
  3. **Nothing is cleared.** The list survives to the next message.
- **On conversation open from history**: `attachments` starts empty; the active scene's `syncSceneAttachments` fires on mount and repopulates from the current scene. History rendering shows the historical context per message (read from the persisted log).
- **On new conversation / explicit reset**: optional `clearAttachments()` for a fresh slate; otherwise the next conversation inherits the previous attachment set (acceptable since scene-sync re-asserts what's relevant).

LangGraph conversations follow today's lifecycle unchanged.

### 3.5 Sending a message — wire shape

The frontend talks to the public `/conversations/*` API as today. The only addition is an `attached_context` field on the request body.

**First message** (conversation create + open stream — `02_CORE.md` § 5):

```http
POST /api/environments/{teamId}/conversations/{conversationId}/sandbox/
{
    "content": "Why did checkout conversions drop last week?",
    "trace_id": "...",
    "attached_context": [
        { "type": "dashboard", "id": 123, "name": "Marketing Funnel" },
        { "type": "insight", "id": "abc-def", "name": "Daily Signups" }
    ]
}
```

**Follow-up** (same conversation — `02_CORE.md` § 5.2 / 5.3):

```http
POST /api/environments/{teamId}/conversations/{conversationId}/sandbox/
{
    "content": "Show me the trend for last 30 days",
    "trace_id": "...",
    "attached_context": [
        { "type": "insight", "id": "xyz", "name": "Conversion by source" }
    ]
}
```

The shape is the same in both cases. The `POST /sandbox/` handler is responsible for:

1. Deduping `attached_context` against entity refs already named in the conversation's persisted ACP log (see § 4.3). Dedupe affects only the rendered prompt block — the structured record stays verbatim.
2. Wrapping `content` with the `<posthog_context>` block built from the deduped list before sending it on — in-process: the wrapped text becomes the run state's `pending_user_message` at `Task.create_and_run(...)` / `task.create_run(...)` time for the first turn (`products/tasks/backend/models.py:279`, `:230`), or the `wrapped_content` passed to `signal_task_followup_message(run.workflow_id, ...)` for an in-progress follow-up (`products/tasks/backend/temporal/client.py:314`).
3. Including the **full, undeduped** structured `attached_context` under the outbound payload's `state.attached_context` (first turn) or `params._meta.attached_context` (follow-up) so the persisted ACP log keeps a complete record per message.

`ui_context` (today's rich-payload field) is **dropped** from the request shape for `agent_runtime === 'sandbox'` conversations. The LangGraph path keeps reading it for `agent_runtime === 'langgraph'`. The frontend can keep sending both during the soak — the sandbox `POST /sandbox/` handler just ignores `ui_context`.

---

## 4. Backend design

### 4.1 Storage

Two places — both downstream of the `POST /sandbox/` handler:

1. **`Run.state.attached_context: AttachedContext[]`** — set at Run-create time from the initial conversation request. Survives for the life of the Run.
2. **`_posthog/user_message` log entries** — each follow-up user message logged with its own `attached_context` (and the wrapped content) so the persisted ACP log is a complete record.

In **both** locations the structured record is the **full, undeduped** list as the user sent it. Cross-message dedupe (§ 4.3) applies only to the rendered `<posthog_context>` text block — the structured record stays verbatim so the audit trail, debug views, and any future re-render path are not data-lossy.

`state` is a free-form JSON bag in the existing `products/tasks` Task/Run model (the contract is documented in `CLOUD_IMPLEMENTATION.md` § 2.5; it is implemented in this monorepo at `products/tasks/backend/`). Adding a key is non-breaking.

The `Conversation` row in PostHog's database does **not** need an `attached_context` column. The structured record lives on the Run side; the conversation row stays slim.

### 4.2 Where wrapping happens

The Django `POST /sandbox/` handler (`products/posthog_ai/backend/message_routing.py` — see [`02_CORE.md`](./02_CORE.md) § 4) calls the dedupe+wrap pair at two points:

- **First message** — when constructing the run state for the in-process `Task.create_and_run(...)` / `task.create_run(...)` call (`products/tasks/backend/models.py:279`, `:230`). The handler computes `pending_user_message = wrap_user_message(content, prune_repeated_entity_refs(attached_context, prior=[]))` (on a brand-new conversation the prior set is empty, so dedupe is a no-op) and sets `state.attached_context = attached_context` with the full list.
- **Follow-up message** — when constructing the `signal_task_followup_message(run.workflow_id, wrapped_content, artifact_ids)` call for an in-progress run (`products/tasks/backend/temporal/client.py:314`). The handler first walks prior `_posthog/user_message` entries on the conversation's persisted ACP log to collect already-named `(type, id)` pairs, then computes `wrapped_content = wrap_user_message(content, prune_repeated_entity_refs(attached_context, prior=seen))` and records `_meta.attached_context = attached_context` with the full list on the logged message.

The wrap+dedupe happens entirely in the Django handler (`products/posthog_ai`) **before** the in-process `products/tasks` call. The Temporal workflow and sandbox provisioning belong to `products/tasks` and are reused as-is — the PostHog AI handler does not own or duplicate them. The first-message wrapped content rides in the run state's `pending_user_message`; the in-progress follow-up rides through `signal_task_followup_message`; the terminal follow-up (resume) rides in `task.create_run(...)` `extra_state.pending_user_message` (`products/tasks/backend/models.py:230`).

### 4.3 The wrapping function

```python
# products/posthog_ai/backend/context_wrapper.py

def wrap_user_message(content: str, attached_context: list[AttachedContext]) -> str:
    if not attached_context:
        return content
    block = _render_posthog_context_block(attached_context)
    return f"{block}\n\n{content}"


def _render_posthog_context_block(items: list[AttachedContext]) -> str:
    lines = [
        "<posthog_context>",
        "The user attached the following PostHog entities. "
        "Use the appropriate tools to retrieve their details only if relevant to the request.",
    ]
    for item in items:
        lines.append(_format_item(item))
    lines.append("</posthog_context>")
    return "\n".join(lines)


def prune_repeated_entity_refs(
    attached: list[AttachedContext],
    prior: Iterable[tuple[str, str | int]],
) -> list[AttachedContext]:
    """Drop entity refs (type, id) that were already named in earlier messages
    of the same conversation. `text` items are NEVER deduped — repeated text is
    intentional (e.g. consecutive error snippets).

    The agent retains entity IDs from prior turns in its context; re-listing
    them inflates the prompt without adding information. The agent can re-fetch
    any prior entity via its read tools.
    """
    seen = set(prior)
    out: list[AttachedContext] = []
    for item in attached:
        if item.type == "text":
            out.append(item)
            continue
        key = (item.type, item.id)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
```

`_format_item` emits one line per attachment naming the entity type, ID, and (if present) human label. It does **not** name specific tool function signatures — naming is owned by `04_PROMPTS.md` § 5 — but the wrapper does name the tool _category_ ("Use the appropriate tools..."). Tool descriptions on the MCP side carry the function signatures the agent reads.

Both functions are pure, side-effect-free, snapshot-testable. `wrap_user_message` skips emitting the block entirely when its input is empty — so when dedupe removes everything, the user's message is forwarded without any wrapper noise. Called from the `POST /sandbox/` handler at both first-message run-create and follow-up `signal_task_followup_message` time (§ 4.2).

**Template single-sourcing.** The `<posthog_context>` template lives only here, in Python. The frontend never builds it. If a future debug surface needs to show the wrapped form (§ 3.6), it calls a thin `GET /preview_wrap/` endpoint that delegates to `wrap_user_message` — no TypeScript mirror, no risk of the two copies drifting.

**Dedupe scope: lifetime-wide.** `prune_repeated_entity_refs` walks every prior `_posthog/user_message` log entry in the conversation, regardless of how old. There is no windowing or "expire after N turns" behavior. The agent retains entity IDs across the whole conversation; re-listing them once they've been named is pure overhead. Revisit only if an eval surfaces a case where the agent has demonstrably forgotten an entity by turn N — and the right fix there is probably user-side re-priming via a slash command, not changing dedupe.

### 4.4 Server-side validation

The `attached_context` field is user input. Validate at the boundary:

- `type` ∈ allowed set.
- `id` matches the type's id shape (int for `dashboard`, short_id for `insight`, UUID for `error_tracking_issue`, ...).
- Hard-cap the list at **32 items** to prevent prompt-injection-via-overflow.
- Hard-cap `value` for `text` items at **4096 chars**.
- For entity refs, **don't** validate existence — let the agent's tool call surface a missing-row error naturally. Cheaper than a sync DB lookup per submit.
- Team-scope safety belongs in the tools themselves (every read tool already filters by `team_id` via `get_team()`).

Both caps are conservative starting points; the real binding constraint is whatever pushes the wrapped block past ~4k tokens (which dedupe substantially reduces in practice). Revisit with eval data — not with per-customer escalations.

### 4.5 Database changes

None to the existing models. `Run.state` is a JSON field. Add a doc comment to the model listing the new well-known key (`attached_context`) and link to this spec.

If a future iteration needs efficient querying by attached entity (e.g. "show all conversations that referenced this dashboard"), introduce a dedicated `RunAttachment` table later. Out of scope for this migration.

---

## 5. Migration steps

Ordered. Each step is a self-contained PR. **None of these steps modifies the existing `maxContextLogic.ts`, scene logics, or `MaxContextInput`/`MaxUIContext`/`createMaxContextHelpers` types** — that belongs in the deferred cleanup phase per [`BACKWARD_COMPAT.md`](./BACKWARD_COMPAT.md).

1. **Types.** Add `AttachedContext` to `frontend/src/scenes/max/maxTypes.ts` (new export, no existing edits).
2. **Backend wrapper + dedupe.** Add `products/posthog_ai/backend/context_wrapper.py` with both `wrap_user_message` and `prune_repeated_entity_refs`. Snapshot test for: empty, one-of-each-type, mixed-with-free-text, repeated-entity-ref dedupe, repeated-text not-deduped, length-capped, missing-name fallbacks. Pure functions — independent of the handler plumbing.
3. **`POST /sandbox/` handler integration.** The `POST /sandbox/` handler (`products/posthog_ai/backend/message_routing.py`, `02_CORE.md` § 4) calls `prune_repeated_entity_refs` then `wrap_user_message` at run-create and at every in-process `signal_task_followup_message` — only on the sandbox branch. The full undeduped list goes to `state.attached_context` / the logged message's `_meta.attached_context`.
4. **New sandbox context logic.** Add `frontend/src/scenes/max/posthogAiContextLogic.ts` (sibling to `maxContextLogic.ts`). Includes `projectToAttachedContext` helper and the single `attachments` reducer with dedup-on-`attach`. Mounted by `maxThreadLogic` only when `conversation.agent_runtime === 'sandbox'`.
5. **`Context.tsx` runtime branch.** Add a runtime-aware render branch — LangGraph path uses today's chips; sandbox path uses the new logic. Existing LangGraph branch is verbatim.
6. **Wire send-message.** `maxThreadLogic.sendMessage` already builds the request body. Add an `if conversation.agent_runtime === 'sandbox'` branch that reads from `posthogAiContextLogic.values.attachments` and sets `attached_context` instead of `ui_context`. Send does not clear attachments. LangGraph branch unchanged.
7. **(Deferred to cleanup phase.)** Once the flag is default-on for everyone and a soak confirms parity, a follow-up PR can delete `maxContextLogic.ts`, `maxBillingContextLogic.tsx`, `createMaxContextHelpers`, the `compiledContext` / `loadAndProcessDashboard` / `loadAndProcessInsight` machinery, and the redundant `MaxContextInput` / `MaxUIContext` shapes. The 3 scene `maxContext` selectors can then collapse to `AttachedContext[]`. This is NOT part of the migration — tracked separately.

---

## 6. Cross-spec dependencies

| Spec            | Dependency                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `02_CORE.md`    | `POST /conversations/{id}/sandbox/` request body carries `attached_context` field for both first and follow-up messages. The handler calls `prune_repeated_entity_refs` then `wrap_user_message` before the in-process `products/tasks` call (`Task.create_and_run` / `signal_task_followup_message` / `task.create_run`). The endpoint is non-streaming — frontend opens SSE directly against the existing `products/tasks` endpoint `/api/projects/{tid}/tasks/{taskId}/runs/{runId}/stream/` (`products/tasks/backend/api.py:2659`) after the response returns. |
| `03_RICH_UI.md` | Scene–agent interaction is one-directional: scenes contribute attachments via the existing `maxContext` selector and can subscribe to thread state read-only (`useValues(maxThreadLogic)`). No agent-side callbacks; `useMaxTool` / `MaxTool` are deleted (owned by `03`).                                                                                                                                                                                                                                                                                         |
| `04_PROMPTS.md` | (a) Don't inject groups, billing, or core memory into `systemPrompt` — MCP tools handle it. (b) Tool naming used in `<posthog_context>` wrappers comes from § 5 of that spec — keep the wrapper template generic ("the appropriate tools") so renames don't break this. (c) Drop `ManageMemoriesTool` from the catalog (no core memory).                                                                                                                                                                                                                           |

---

## 7. What this spec does not cover

- **Tool naming and MCP server layout** → `04_PROMPTS.md`.
- **Where the wrapped message is stored on the wire** (Run.state JSON key vs dedicated column) → backend implementation choice; the spec says "in `state`" and that's enough.
- **Conversation export / sharing** → out of scope (per `00_OVERVIEW.md` § 11).
- **Artifacts / file uploads** → orthogonal. `TaskRunArtifact[]` still exists for actual file uploads (screenshots, PDFs). Attached context is for entity references and free text only.
- **History rendering of attached context** → each persisted user-message log entry already carries its `attached_context`; the thread renderer in `03_RICH_UI.md` reads it and shows the chips inline.
