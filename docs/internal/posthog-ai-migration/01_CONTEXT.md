# 01 — Context migration

The new context model is intentionally small. Previously we pre-computed and serialized rich `MaxUIContext` payloads because not every entity referenced in a conversation was reachable via a tool. That constraint no longer holds — the sandbox agent has data tools for every entity type we care about — so context becomes a flat list of references that the agent fetches on demand.

This rewrite supersedes the earlier hybrid (`A/B/C/D`) proposal. There is **one** delivery channel: per-message attachment. There is **no** mid-Run refresh, **no** `posthog-context` MCP server, **no** systemPrompt-side context injection, **no** core memory, **no** dynamic tool injection.

---

## 1. The model

A user message carries an optional list of typed attachments. The Django sandbox adapter (`ee/hogai/sandbox/`) wraps the message with a `<posthog_context>` block — on both first messages and follow-ups — and forwards the wrapped text into the cloud-agent Task/Run. The frontend never sees the wrapped form on its own outbound requests; it speaks `/conversations/*` as today and just adds an `attached_context` field to the request body.

```ts
interface AttachedContext {
    type:
        | 'dashboard'
        | 'insight'
        | 'event'
        | 'action'
        | 'error_tracking_issue'
        | 'evaluation'
        | 'notebook'
        | 'text'
    id?: string | number   // entity types
    name?: string          // optional human label for entity types
    value?: string         // type === 'text'
}
```

The wrapped message the agent sees:

```
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

| Old reason for pre-computation | Current state |
|---|---|
| Some entity types had no read tool — agent couldn't fetch | Every entity type listed above is covered by an MCP tool exposed by `posthog-data` / `posthog-notebook` (see `04_PROMPTS.md` § 5) |
| Token cost of an extra round-trip per dashboard mattered | Tool-call round-trips are cheap relative to model latency; pre-loading every dashboard the user might mention is wasteful when most go unused |
| The LangGraph node graph needed deterministic prompt assembly | The sandbox agent decides its own tool sequence — pre-fetching steals decisions from it |

---

## 2. What gets removed

| Concept (in the old spec / old code) | Disposition |
|---|---|
| Pre-interpolated `MaxUIContext` payloads (dashboards-with-tiles, insights-with-query, events-with-properties) | **Gone.** Replaced by IDs the agent fetches via tools. |
| `posthog-context` MCP server proposal | **Gone.** General data tools (`read_dashboard`, `read_insight`, ...) cover it. |
| Static team-scope injection into `systemPrompt` (groups, billing, core memory) | **Gone.** Already accessible via MCP — no need to duplicate in the system prompt. |
| Core memory (`/remember`, `ManageMemoriesTool`) | **Dropped entirely** for the new PostHog AI. Not migrated. |
| Mid-Run context refresh (`set_config_option("posthog_active_context", …)`, `_posthog/refresh_session` for context updates) | **Gone.** Context is static per message. To change context, attach to the next message. |
| Dynamic tool injection (`useMaxTool` registering scene-specific tools at mount time) | **Gone.** Only the static MCP tool set is available. If a scene needs to act on Max output, it does so reactively (subscribe to the new logic's outputs), not by registering a callback the agent invokes. |
| Two-channel hybrid (static slice in `systemPrompt` + per-turn block) | **Collapsed.** Single channel: per-message `<posthog_context>` wrapper. |
| `compiledContext` selector merging scene + manual contexts into a `MaxUIContext` object | Replaced by a flat `attachedContext: AttachedContext[]` reducer. No "compilation". |
| `createMaxContextHelpers.dashboard(dashboard)` (takes the full Dashboard object and serializes) | Replaced by `attach({ type: 'dashboard', id, name })` — just IDs and labels. |
| `maxBillingContextLogic` | **Delete.** Billing data, when needed, is exposed via the billing MCP tool. |

---

## 3. Frontend design

> **Coexistence mode** (per [`BACKWARD_COMPAT.md`](./BACKWARD_COMPAT.md) #1, #2). The existing `maxContextLogic.ts` stays untouched for LangGraph users. Sandbox context lives in a **new** sibling logic at `frontend/src/scenes/max/posthogAIContextLogic.ts`. The two coexist for the entire rollout. The simplification described in this section is the *end state* (post default-on); during the soak only the new file is added.

The new `posthogAIContextLogic.ts` holds a flat `attachments: AttachedContext[]` reducer plus a thin scene-pull listener that *reads* the existing 3 scenes' `maxContext` selectors and **projects** their rich `MaxContextInput[]` items down to flat `AttachedContext[]` at consumption time. Zero scene-side edits — the scenes keep returning their existing rich shapes.

### 3.1 The new `posthogAIContextLogic.ts`

```ts
interface PostHogAIContextLogicValues {
    attachments: AttachedContext[]
    chipsForDisplay: { key: string; label: string; icon: ReactNode; onRemove: () => void }[]
}

interface PostHogAIContextLogicActions {
    attach: (item: AttachedContext) => void
    detach: (key: string) => void   // key = `${type}:${id ?? value}`
    clearAttachments: () => void
    syncFromScene: () => void       // called by router listener; reads activeScene.maxContext and projects to AttachedContext[]
}
```

State is per-thread (per `maxThreadLogic` instance — see `02_CORE.md`). Cleared after each message is sent — see § 3.4.

### 3.2 The scene `maxContext` selector contract — fully preserved

The 3 scenes that expose `maxContext` today (dashboard, insight, project homepage — confirmed by `grep -rn "maxContext\b" frontend/src/scenes/`) **keep returning `MaxContextInput[]`** verbatim, exactly as today. The sandbox logic does the projection at consumption time:

```ts
// inside posthogAIContextLogic, syncFromScene listener
const sceneItems: MaxContextInput[] = activeSceneLogic.values.maxContext ?? []
const projected: AttachedContext[] = sceneItems.map(projectToAttachedContext)
actions.replaceSceneAttachments(projected)
```

Where `projectToAttachedContext()` is a one-screen helper that strips the rich nested data and emits a flat `{ type, id, name? }` record per entity. This is the **only** new code touching the existing scene-context contract — and it lives in the new file, not in the existing logic. Zero edits to `maxContextLogic.ts`, `dashboardLogic.tsx`, `insightSceneLogic.tsx`, or `projectHomepageLogic.tsx`.

Today (to be removed):

Today's selector (unchanged during the migration):

```ts
maxContext: [
    (s) => [s.dashboard],
    (dashboard): MaxContextInput[] => {
        if (!dashboard) return []
        return [createMaxContextHelpers.dashboard(dashboard)]  // serializes nested tiles
    },
]
```

The sandbox logic reads this and projects:

```ts
// posthogAIContextLogic.ts — at consumption time
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
- `'sandbox'` → renders chips from `posthogAIContextLogic.values.chipsForDisplay`.

The taxonomic-filter "add context" affordance also branches the same way. Same TaxonomicFilter component, same group types; the dispatched action differs (`maxContextLogic.handleTaxonomicFilterChange` vs `posthogAIContextLogic.attach`).

### 3.4 Lifecycle (sandbox runtime)

- **On scene change**: router listener calls `posthogAIContextLogic.syncFromScene`, which:
  1. Reads `activeSceneLogic.values.maxContext` if present.
  2. Projects to `AttachedContext[]` via `projectToAttachedContext`.
  3. Replaces only the *scene-sourced* portion of `attachments`. Manually-attached items (via TaxonomicFilter or @-mention) persist until the user removes them or sends a message.
- **On message send** (in `maxThreadLogic`, sandbox branch):
  1. Snapshot current `posthogAIContextLogic.values.attachments`.
  2. Build the request payload (see § 3.5).
  3. Dispatch `clearAttachments` (or only-clear-manual-items — open question § 7).
- **On conversation open from history**: `attachments` starts empty. History rendering shows the historical context per message (read from the persisted log).

LangGraph conversations follow today's lifecycle unchanged.

### 3.5 Sending a message — wire shape

The frontend talks to the public `/conversations/*` API as today. The only addition is an `attached_context` field on the request body.

**First message** (conversation create + open stream — `02_CORE.md` § 5):

```http
POST /api/environments/{teamId}/conversations/stream/
{
    "content": "Why did checkout conversions drop last week?",
    "trace_id": "...",
    "attached_context": [
        { "type": "dashboard", "id": 123, "name": "Marketing Funnel" },
        { "type": "insight", "id": "abc-def", "name": "Daily Signups" }
    ]
}
```

**Follow-up** (same conversation, continued stream — `02_CORE.md` § 6):

```http
POST /api/environments/{teamId}/conversations/{conversationId}/stream/
{
    "content": "Show me the trend for last 30 days",
    "trace_id": "...",
    "attached_context": [
        { "type": "insight", "id": "xyz", "name": "Conversion by source" }
    ]
}
```

The shape is the same in both cases. The adapter is responsible for:

1. Wrapping `content` with the `<posthog_context>` block before sending it on (to either `POST /tasks/{id}/run/` `pending_user_message` for the first turn, or `POST /command/` `user_message` for follow-ups).
2. Including the structured `attached_context` under the outbound payload's `state.attached_context` (first turn) or `params._meta.attached_context` (follow-up) so the persisted ACP log keeps a structured record.

`ui_context` (today's rich-payload field) is **dropped** from the request shape for `agent_runtime === 'sandbox'` conversations. The LangGraph path keeps reading it for `agent_runtime === 'langgraph'`. The frontend can keep sending both during the soak — the sandbox adapter just ignores `ui_context`.

---

## 4. Backend design

### 4.1 Storage

Two places — both downstream of the adapter:

1. **`Run.state.attached_context: AttachedContext[]`** — set at Run-create time from the initial conversation request. Survives for the life of the Run.
2. **`_posthog/user_message` log entries** — each follow-up user message logged with its own `attached_context` (and the wrapped content) so the persisted ACP log is a complete record.

`state` is a free-form JSON bag in the existing Task/Run model (cloud-agent spec § 2.5). Adding a key is non-breaking.

The `Conversation` row in PostHog's database does **not** need an `attached_context` column. The structured record lives on the Run side; the conversation row stays slim.

### 4.2 Where wrapping happens

The Django sandbox adapter (`ee/hogai/sandbox/adapter.py` — owned by `02_CORE.md`) calls the wrapper at two points:

- **First message** — when constructing the `POST /tasks/{id}/run/` body. The adapter sets `pending_user_message = wrap_user_message(content, attached_context)` and `state.attached_context = attached_context`.
- **Follow-up message** — when constructing the `POST /command/` body. The adapter sets `params.content = wrap_user_message(content, attached_context)` and `params._meta.attached_context = attached_context`.

There is no Temporal workflow involvement. The cloud-agent SSE relay and the sandbox JWT scheme handle the rest of the lifecycle.

### 4.3 The wrapping function

```python
# ee/hogai/sandbox/context_wrapper.py

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
```

`_format_item` emits one line per attachment naming the entity type, ID, and (if present) human label. It does **not** name specific tool function signatures — naming is owned by `04_PROMPTS.md` § 5 — but the wrapper does name the tool *category* ("Use the appropriate tools..."). Tool descriptions on the MCP side carry the function signatures the agent reads.

Pure function, no side effects, fully snapshot-testable. Called from the adapter at both first-message Run-create and follow-up `POST /command/` time (§ 4.2).

### 4.4 Server-side validation

The `attached_context` field is user input. Validate at the boundary:

- `type` ∈ allowed set.
- `id` matches the type's id shape (int for `dashboard`, short_id for `insight`, UUID for `error_tracking_issue`, ...).
- Length-cap the list (e.g. 32 items) to prevent prompt-injection-via-overflow.
- Length-cap `value` for `text` items (e.g. 4096 chars).
- For entity refs, **don't** validate existence — let the agent's tool call surface a missing-row error naturally. Cheaper than a sync DB lookup per submit.
- Team-scope safety belongs in the tools themselves (every read tool already filters by `team_id` via `get_team()`).

### 4.5 Database changes

None to the existing models. `Run.state` is a JSON field. Add a doc comment to the model listing the new well-known key (`attached_context`) and link to this spec.

If a future iteration needs efficient querying by attached entity (e.g. "show all conversations that referenced this dashboard"), introduce a dedicated `RunAttachment` table later. Out of scope for this migration.

---

## 5. Migration steps

Ordered. Each step is a self-contained PR. **None of these steps modifies the existing `maxContextLogic.ts`, scene logics, or `MaxContextInput`/`MaxUIContext`/`createMaxContextHelpers` types** — that belongs in the deferred cleanup phase per [`BACKWARD_COMPAT.md`](./BACKWARD_COMPAT.md).

1. **Types.** Add `AttachedContext` to `frontend/src/scenes/max/maxTypes.ts` (new export, no existing edits).
2. **Backend wrapper.** Add `ee/hogai/sandbox/context_wrapper.py`. Snapshot test for: empty, one-of-each-type, mixed-with-free-text, length-capped, missing-name fallbacks. Independent of adapter plumbing.
3. **Adapter integration.** The adapter (`02_CORE.md`) calls `wrap_user_message` at Run-create and at every `POST /command/` — only on the sandbox branch.
4. **New sandbox context logic.** Add `frontend/src/scenes/max/posthogAIContextLogic.ts` (sibling to `maxContextLogic.ts`). Includes `projectToAttachedContext` helper. Mounted by `maxThreadLogic` only when `conversation.agent_runtime === 'sandbox'`.
5. **`Context.tsx` runtime branch.** Add a runtime-aware render branch — LangGraph path uses today's chips; sandbox path uses the new logic. Existing LangGraph branch is verbatim.
6. **Wire send-message.** `maxThreadLogic.sendMessage` already builds the request body. Add an `if conversation.agent_runtime === 'sandbox'` branch that reads from `posthogAIContextLogic.values.attachments` and sets `attached_context` instead of `ui_context`. LangGraph branch unchanged.
7. **(Deferred to cleanup phase.)** Once the flag is default-on for everyone and a soak confirms parity, a follow-up PR can delete `maxContextLogic.ts`, `maxBillingContextLogic.tsx`, `createMaxContextHelpers`, the `compiledContext` / `loadAndProcessDashboard` / `loadAndProcessInsight` machinery, and the redundant `MaxContextInput` / `MaxUIContext` shapes. The 3 scene `maxContext` selectors can then collapse to `AttachedContext[]`. This is NOT part of the migration — tracked separately.

---

## 6. Cross-spec dependencies

| Spec | Dependency |
|---|---|
| `02_CORE.md` | `/conversations/stream/` request body gains `attached_context` field for both first and follow-up messages. Adapter calls `wrap_user_message` before forwarding. |
| `03_RICH_UI.md` | Scene–agent interaction is one-directional: scenes contribute attachments via the existing `maxContext` selector and can subscribe to thread state read-only (`useValues(maxThreadLogic)`). No agent-side callbacks; `useMaxTool` / `MaxTool` are deleted (owned by `03`). |
| `04_PROMPTS.md` | (a) Don't inject groups, billing, or core memory into `systemPrompt` — MCP tools handle it. (b) Tool naming used in `<posthog_context>` wrappers comes from § 5 of that spec — keep the wrapper template generic ("the appropriate tools") so renames don't break this. (c) Drop `ManageMemoriesTool` from the catalog (no core memory). |

---

## 7. Open questions

1. **Selector rename.** Keep `maxContext` (zero churn) or rename to `sceneAttachments` (clearer post-Max)? Bias toward keeping the name during the migration window; revisit after `scenes/max/` is deleted.
2. **Persistence of manually-attached items across messages.** When the user explicitly adds (via TaxonomicFilter) an insight that isn't part of the current scene, does that attachment stick across messages, or clear on send like the scene-sourced ones? Bias toward "clear on send" — matches today's chip UX where the chip vanishes after submission — but the chip-UI could grow a pin affordance later.
3. **`text` attachment ergonomics.** Useful for paste-snippets ("here's the error I saw: ..."). Or skip until a real need shows up? Bias toward shipping with `text` supported since the wrapper handles it generically and removing later costs nothing.
4. **Wrapper-template drift.** The wrapping is centralized in the Django adapter, so frontend and follow-up wrapping share one template definition. Confirm there's no scenario where the frontend needs the wrapped form before sending (e.g., to show the user what was sent) — if so, we either duplicate the template in TS or expose a small `/api/.../preview_wrap/` endpoint.
5. **Wrapped-message visibility in UI.** Should the user see the `<posthog_context>` block (folded by default), or only their typed text? Bias toward hiding by default with a "Show context sent to Max" debug toggle behind a feature flag for internal users.
6. **Attachment limits.** What's the hard cap on `attached_context` length? 32 items × 2048 chars per `value` is generous; the actual number that hurts is whatever pushes the wrapped block past ~4k tokens. Pick a number and revisit with eval data.

---

## 8. What this spec does not cover

- **Tool naming and MCP server layout** → `04_PROMPTS.md`.
- **Where the wrapped message is stored on the wire** (Run.state JSON key vs dedicated column) → backend implementation choice; the spec says "in `state`" and that's enough.
- **Conversation export / sharing** → out of scope (per `00_OVERVIEW.md` § 11).
- **Artifacts / file uploads** → orthogonal. `TaskRunArtifact[]` still exists for actual file uploads (screenshots, PDFs). Attached context is for entity references and free text only.
- **History rendering of attached context** → each persisted user-message log entry already carries its `attached_context`; the thread renderer in `03_RICH_UI.md` reads it and shows the chips inline.
