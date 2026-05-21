# 01 — Context migration

This spec covers the **Context** slice of the migration described in [`00_OVERVIEW.md`](./00_OVERVIEW.md). Read that document first — it establishes the Task/Run/SSE target architecture from [`CLOUD_AGENTS_FRONTEND_SPEC.md`](../CLOUD_AGENTS_FRONTEND_SPEC.md) and the concept mapping table. This document never restates that mapping; it cross-references it.

Scope of this document: how PostHog AI's `MaxUIContext` payload (dashboards, insights, events, actions, error-tracking issues, evaluations, notebooks) gets from the browser scene into the sandboxed `@posthog/agent` and stays correct across turns. Out of scope: the static body of the systemPrompt (`04_PROMPTS.md`), the streaming transport (`02_CORE.md`), and the rendering of tool-call results back into the conversation (`03_RICH_UI.md`).

---

## 1. Today: how Max context works

The current implementation has three layers:

1. **Compilation** — `maxContextLogic` aggregates context from two sources: the active scene's `maxContext` selector (auto-detected) and manual additions via the `@`-context taxonomic filter.
2. **Transport** — every `streamConversation` call attaches `ui_context: MaxUIContext` to the request body.
3. **Consumption** — Django serializer pulls `ui_context` off the HumanMessage, the LangGraph agent's `AssistantContextManager` formats it into a `ContextMessage` that lives in the conversation history.

### 1.1 Scene `maxContext` selector contract

Documented contract: [`frontend/src/scenes/max/README.md`](../../posthog/frontend/src/scenes/max/README.md). The pattern is:

```typescript
import { MaxContextInput, createMaxContextHelpers } from 'scenes/max/maxTypes'

selectors({
    maxContext: [
        (s) => [s.dashboard],
        (dashboard): MaxContextInput[] => {
            if (!dashboard) return []
            return [createMaxContextHelpers.dashboard(dashboard)]
        },
    ],
})
```

The contract is essentially: a scene's logic exposes one selector named `maxContext` that returns `MaxContextInput[]` (the union type defined in [`maxTypes.ts:146-153`](../../posthog/frontend/src/scenes/max/maxTypes.ts)).
There is no registration, no decorator, no React boundary — just a selector with a known name.

`maxContextLogic` auto-detects this via reflection:

[`maxContextLogic.ts:494-516`](../../posthog/frontend/src/scenes/max/maxContextLogic.ts) — the `rawSceneContext` selector reads the `activeSceneLogic` from `sceneLogic` (Kea's scene registry), checks if its `selectors` bag contains a `maxContext` key, and invokes it with the active scene's `paramsToProps`. If the selector throws or doesn't exist, the result is an empty array. Result equality is by deep-equal so unchanged context doesn't trip downstream listeners.

### 1.2 maxContextLogic compilation

`maxContextLogic` is a singleton logic that holds:

- **Manual context** — seven reducers, one per entity type, each backed by `addOrUpdate*` / `remove*` actions. State arrays live at:
  - `contextInsights: MaxInsightContext[]` — [`maxContextLogic.ts:133-142`](../../posthog/frontend/src/scenes/max/maxContextLogic.ts)
  - `contextDashboards: MaxDashboardContext[]` — `:143-154`
  - `contextEvents: MaxEventContext[]` — `:155-164`
  - `contextActions: MaxActionContext[]` — `:165-174`
  - `contextErrorTrackingIssues: MaxErrorTrackingIssueContext[]` — `:175-186`
  - `contextNotebooks: MaxNotebookContext[]` — `:187-197`
  - `contextEvaluations: MaxEvaluationContext[]` — `:198-219`
- **Scene context** — derived from `rawSceneContext` (see § 1.1). The `sceneContext` selector ([`:517-543`](../../posthog/frontend/src/scenes/max/maxContextLogic.ts)) maps each `MaxContextInput` through the type-specific converter in [`utils.ts`](../../posthog/frontend/src/scenes/max/utils.ts) (`insightToMaxContext`, `dashboardToMaxContext`, `eventToMaxContextPayload`, etc.).
- **Compilation** — the `compiledContext` selector ([`:631-760`](../../posthog/frontend/src/scenes/max/maxContextLogic.ts)) merges manual and scene context, dedupes by ID per entity type, filters out insights that are already attached to dashboards (so we don't double-count), and returns a single `MaxUIContext` object — the wire shape.
- **Reset on navigation** — the `locationChanged` listener ([`:221-276`](../../posthog/frontend/src/scenes/max/maxContextLogic.ts)) calls `resetContext` whenever the pathname or search params change, except for the `chat` query parameter and the `panel` hash parameter (those identify Max's own UI state). Note: this only resets the manual reducers; scene context is selector-derived and recomputes naturally.

The reducers do "upsert + remove by id" via two helpers:

```typescript
const addOrUpdateEntity = <T extends { id: string | number; type: string }>(state: T[], entity: T): T[] =>
    state.filter((item) => item.id !== entity.id).concat(entity)
```

[`maxContextLogic.ts:65-69`](../../posthog/frontend/src/scenes/max/maxContextLogic.ts) — last-write-wins by `id`.

### 1.3 What ships in the request body (MaxUIContext)

[`maxTypes.ts:79-88`](../../posthog/frontend/src/scenes/max/maxTypes.ts):

```typescript
interface MaxUIContext {
    dashboards?: MaxDashboardContext[]
    insights?: MaxInsightContext[]
    events?: MaxEventContext[]
    actions?: MaxActionContext[]
    error_tracking_issues?: MaxErrorTrackingIssueContext[]
    evaluations?: MaxEvaluationContext[]
    notebooks?: MaxNotebookContext[]
    form_answers?: Record<string, string>
}
```

Each entity carries:

- **Insight** (`MaxInsightContext`, [`maxTypes.ts:24-32`](../../posthog/frontend/src/scenes/max/maxTypes.ts)): `id` (short id), `name`, `description`, the actual `query` (`QuerySchema`), plus optional `filtersOverride` and `variablesOverride` — note that the **executable query is part of the payload**, so the agent has enough to re-run or to read structurally.
- **Dashboard** (`MaxDashboardContext`, [`:34-41`](../../posthog/frontend/src/scenes/max/maxTypes.ts)): `id`, `name`, `description`, `filters`, plus `insights: MaxInsightContext[]` — dashboard tiles are flattened into nested insights.
- **Event** / **Action**: id + name + description.
- **Error tracking issue**: UUID + name only — the backend re-fetches details from `ErrorTrackingIssue` rows via `ReadDataTool`/`SearchTool`.
- **Notebook**: `short_id` + title — backend re-fetches the notebook via `NotebookContext.from_short_id` ([`context.py:281-285`](../../posthog/ee/hogai/context/context.py)).
- **Evaluation**: id, name, description, `evaluation_type`, optional `hog_source` — the source code is embedded so the model can reason about and edit Hog programs.

The transport call is `streamConversation` in [`maxThreadLogic.tsx:1100-1113`](../../posthog/frontend/src/scenes/max/maxThreadLogic.tsx), with `ui_context: mergedUiContext` injected on every turn. `mergedUiContext` ([`:1003-1005`](../../posthog/frontend/src/scenes/max/maxThreadLogic.tsx)) is `compiledContext` from `maxContextLogic` shallow-merged with any per-call `uiContext` override (used by `MaxOpenContext` — see [`utils.ts:236-269`](../../posthog/frontend/src/scenes/max/utils.ts)).

### 1.4 Backend consumption

The wire is `POST /api/environments/{team_id}/conversations/stream/` ([`ee/api/conversation.py:102-127`](../../posthog/ee/api/conversation.py)). The serializer accepts `ui_context: JSONField` and embeds it into a `HumanMessage(content=..., ui_context=...)` Pydantic model.

The agent's `AssistantContextManager` ([`ee/hogai/context/context.py`](../../posthog/ee/hogai/context/context.py)) is the consumer:

- `get_ui_context(state)` ([`:86-93`](../../posthog/ee/hogai/context/context.py)) pulls `ui_context` off the start human message.
- `_format_ui_context(ui_context)` ([`:160-335`](../../posthog/ee/hogai/context/context.py)) renders each entity into a Mustache-templated XML block. Dashboards and insights are **actually executed** against the team's data before being inlined — the rendered prompt contains real numbers, not just query DSL. See `DashboardContext.execute_and_format()` and `InsightContext.execute_and_format()`.
- The result is wrapped in `<attached_context>…</attached_context>` per `ROOT_UI_CONTEXT_PROMPT` ([`ee/hogai/context/prompts.py:1-17`](../../posthog/ee/hogai/context/prompts.py)) and inserted as a `ContextMessage` **before** the start human message ([`:482-486`](../../posthog/ee/hogai/context/context.py)).

Per-turn behavior: a fresh `ContextMessage` is added every turn, deduped by exact-content equality against existing `ContextMessage`s ([`:475-480`](../../posthog/ee/hogai/context/context.py)). This means identical context across turns produces one entry; changed context produces a new entry.

In addition to the per-turn UI context, the system prompt itself is composed by `ChatAgentPromptBuilder.get_prompts()` ([`ee/hogai/chat_agent/prompt_builder.py:42-104`](../../posthog/ee/hogai/chat_agent/prompt_builder.py)) and pre-interpolates:

- `groups_prompt` — the team's group type names ("`organization`, `instance`, `project`, …") via `_context_manager.get_group_names()`.
- `core_memory` — the team's long-lived `CoreMemory` text ([`ee/hogai/chat_agent/memory/`](../../posthog/ee/hogai/chat_agent/memory/)).
- `billing_context` — output of `_get_billing_prompt()` based on user's billing role.

These are static-ish (per-team, slow-moving) — they belong in `systemPrompt`, not in per-turn context.

### 1.5 Manual context via taxonomic filter

[`Context.tsx:337-380`](../../posthog/frontend/src/scenes/max/Context.tsx) — the `ContextDisplay` component renders a `<TaxonomicPopover>` triggered by an `@` icon. The popover's group types are computed from `maxContextLogic.taxonomicGroupTypes` ([`maxContextLogic.ts:613-630`](../../posthog/frontend/src/scenes/max/maxContextLogic.ts)):

```
TaxonomicFilterGroupType.MaxAIContext   (only if scene context is non-empty)
TaxonomicFilterGroupType.Events
TaxonomicFilterGroupType.Actions
TaxonomicFilterGroupType.Insights
TaxonomicFilterGroupType.Dashboards
TaxonomicFilterGroupType.Notebooks
TaxonomicFilterGroupType.ErrorTrackingIssues
```

`mainTaxonomicGroupType` ([`:605-612`](../../posthog/frontend/src/scenes/max/maxContextLogic.ts)) picks `MaxAIContext` as the default tab when scene context is available (i.e., when the user is looking at a dashboard or insight), otherwise falls back to `Events`. `MaxAIContext` is a synthetic group — its options are the scene's current context items, surfaced as pickable entries so the user can confirm/keep an auto-detected insight or pull a particular tile out of a dashboard.

On selection, `handleTaxonomicFilterChange` ([`:355-488`](../../posthog/frontend/src/scenes/max/maxContextLogic.ts)) maps the taxonomic group type to the appropriate `addOrUpdate*` reducer. For insights, if the selection came via `MaxAIContext` (i.e., the user picked the active insight from the auto-detected list), the logic also looks up `insightSceneLogic.filtersOverride` / `variablesOverride` so any active dashboard-overrides ride along.

Also displayed:

- **Active tags** — `ContextTags` ([`Context.tsx:181-291`](../../posthog/frontend/src/scenes/max/Context.tsx)) renders one `LemonTag` per **manually-added** entity (scene-derived items are intentionally not shown as removable tags — they live in the auto-included row instead).
- **Tool context tags** — `ContextToolInfoTags` ([`Context.tsx:293-331`](../../posthog/frontend/src/scenes/max/Context.tsx)) shows a dashed-border tag per registered `useMaxTool`-driven contextual description. Sourced from `toolContextItems` ([`maxContextLogic.ts:794-813`](../../posthog/frontend/src/scenes/max/maxContextLogic.ts)) — every entry in `maxGlobalLogic.toolMap` with a `contextDescription` field.

---

## 2. Tomorrow: where context lives in the cloud-agent model

The cloud-agent architecture has four candidate delivery channels (the overview, § 3, suggests Hybrid). Let's evaluate each against the constraints of [`CLOUD_AGENTS_FRONTEND_SPEC.md`](../CLOUD_AGENTS_FRONTEND_SPEC.md).

### 2.1 Delivery channel comparison

| Channel | Where it lives | When it's set | Mutable mid-Run? | Pros | Cons |
|---|---|---|---|---|---|
| **A. Pre-interpolation into `systemPrompt`** | `state.initial_prompt_override` is unrelated — context goes into `clientConnection.newSession({ _meta: { systemPrompt } })` (`agent-server.ts:1529-1726`). Resolved server-side at Run-create time. | Run-create. Frozen for the life of the Run. | No — would need a new Run. | • Survives reconnects (it's compiled into the model's prompt cache). • No tool latency. • Free token-caching boundary. | • Stale the moment the user navigates to a new scene. • Re-creating a Run per scene-change is heavy. • Bloats `systemPrompt` with data that may never be needed. • Same context paid for every model call inside the turn. |
| **B. Initial-prompt content blocks** | `state.pending_user_message` becomes a multi-block cloud prompt (`packages/shared/src/cloud-prompt.ts`, see [`CLOUD_AGENTS_FRONTEND_SPEC.md` § 7](../CLOUD_AGENTS_FRONTEND_SPEC.md)). Context becomes `text` blocks (rendered XML) or `resource_link` blocks (file:// URIs that the agent reads when relevant). | Per-turn. Sent on every `user_message` command (or the first one when starting the Run). | Yes — every new `user_message` carries fresh context. | • One-source-of-truth wire shape: prompt body + context in one envelope. • Per-turn freshness is automatic. • Compatible with existing cloud-prompt machinery (no protocol invention). • Works with file:// references when context is large. | • Sent in full every turn — duplicates across multi-turn conversations unless we play games with prompt-caching. • Cannot serve "deep" detail (you'd embed thousands of rows if the user asks "show me everything"). • The whole `MaxUIContext` re-renders to text every turn even if unchanged. |
| **C. Live MCP server** | A new MCP server `posthog-context` (HTTP, mounted as `--mcpServers`) exposes tools like `get_active_context()`, `get_dashboard_details(id)`, `get_insight_query(id)`, `list_recent_pages()`. The agent calls them on demand. | At sandbox start the URL + auth token are baked in via `--mcpServers`. The *contents* are fetched lazily by the agent. | Yes — the server reads fresh data every call. Browser pushes scene changes via `set_config_option`/`refresh_session` or via a Redis-backed inbox the MCP server reads. | • Cheapest by default — you only pay for context the agent asks for. • Naturally lazy / on-demand. • Reusable from other agents (e.g., PostHog Code asking for an org's project list). | • Adds a round-trip latency to every fetch. • Need server infrastructure (auth, scoping, team_id). • Doesn't address "scene context the agent doesn't know to look at" — if the agent doesn't know "this user is staring at dashboard 1234", it can't help. • Requires a tool-use hop the agent has to be prompted to do. |
| **D. Hybrid** | • **Static, team-scoped** (group types, core memory, billing, project name) → pre-interpolated into `systemPrompt` at Run-create (channel A territory).<br>• **Per-turn scene snapshot** (the IDs/names of what the user is looking at right now, plus rendered insight tables for small payloads) → initial-prompt `text` block (channel B).<br>• **Late-bind / deep detail** (full dashboard run, notebook contents, error stack trace bodies, evaluation source) → on-demand MCP (channel C). | Mixed — see above. | Mid-Run scene-change refreshes only the channel-B content via a follow-up `user_message` (or `set_config_option` carrying a context payload, see § 5.2). | • Best efficiency profile — token cost matches the access pattern. • Each layer is testable independently. • Matches the overview's recommendation (§ 3 of `00_OVERVIEW.md`). | • Three places to keep in sync. • The "what goes where" decision needs to be explicit per entity type. |

### 2.2 Recommended channel mix

**Recommendation: Hybrid (channel D), with the per-entity split documented below.**

Rationale: PostHog AI context has three natural strata, and they don't map cleanly onto a single channel.

1. **Team-scope, slow-moving** — group types, core memory, billing context, available products. These are already pre-resolved server-side ([`prompt_builder.py:47-104`](../../posthog/ee/hogai/chat_agent/prompt_builder.py)) before today's first model call. Cloud-architecture equivalent: bake into `systemPrompt` at Run-create. (Owned by `04_PROMPTS.md`, but this spec defines the slot where dynamic context plugs in.)

2. **User-scope, per-turn** — what the user is currently looking at (active scene's dashboard/insight, manually `@`-pinned entities). This is the slice today's `compiledContext` selector produces. Cloud-architecture equivalent: serialize as a `text` block prepended to `pending_user_message` on each `user_message` command. Small enough to send every turn (a dashboard with five insights, after `_format_ui_context`-style flattening, is typically < 8 KB).

3. **Detail-on-demand** — full dashboard execution results, notebook bodies, evaluation Hog source listings, error-tracking issue stack traces. These can be large (a notebook may exceed 100 KB) and the agent often only needs them when reasoning about a specific question. Cloud-architecture equivalent: keep the per-turn block down to *references* (`id` + `name` + a brief shape descriptor) and let the agent fetch the body through an MCP tool.

The split mirrors what `_format_ui_context` already does on the server today, just at different layers: it inlines small things (event/action names, error tracking IDs) and *executes* large things (dashboards, insights) before inlining. The migration replaces "execute and inline before the model sees it" with "let the model decide whether to fetch, and only pay the bytes if it does."

The detailed per-entity recommendation is in § 4.1 (MCP tool definitions).

### 2.3 Trade-offs

**Channel A is rejected as the primary channel** because PostHog AI's context changes scene-by-scene. A new Run per scene change would mean:

- Losing the current conversation buffer (handed off to a fresh sandbox via `state.resume_from_run_id` — see [`agent-server.ts:1077-1297`](https://github.com/posthog/cloud-agents/agent-server.ts) and `CLOUD_AGENTS_FRONTEND_SPEC.md` § 10.6) on every scene navigation.
- A multi-second restart cost on every navigation (sandbox boot, ACP handshake).
- Wasted token-prefix caching (the model re-reads the entire systemPrompt on the first message of every new Run).

Channel A is reserved exclusively for **truly per-Run** data: team identity, group types, billing access, core memory, agent mode.

**Channel B alone is rejected** because of large entities. Dashboards and notebooks already exercise the upper bound of what's reasonable inside a single user message. Today's `_format_ui_context` mitigates by running the query and inlining only the result, but for cloud agents we want the agent to drive *which* slice of data it cares about. Forcing every turn to carry the rendered execution result for every attached dashboard is wasteful.

**Channel C alone is rejected** because the agent doesn't know what context exists unless someone tells it. The model can't `get_active_context()` if it doesn't know there is one. We need at least a per-turn *hint* — "user is on dashboard X with insights Y, Z" — for the agent to know there's something to fetch.

**Hybrid wins** because:

- A short text block per turn (just IDs + names of attached entities) keeps the prompt small enough to fit in cache.
- An MCP tool serves the heavy detail when needed.
- The team-scope slice lives where it belongs — in the systemPrompt.

The cost is complexity. The mitigation is consistency: every entity type maps to one of the three strata, picked once and documented.

---

## 3. The new logic: `posthogAiContextLogic`

### 3.1 File location and shape

**Location:** `frontend/src/scenes/posthog-ai/posthogAiContextLogic.ts`.

**Goal:** Preserve the existing scene `maxContext` selector contract (§ 3.3) and produce two outputs:

1. **`compiledContextBlock: string | null`** — the per-turn text block to prepend to `pending_user_message`. Equivalent to today's `compiledContext`, but pre-formatted as the same XML-tagged structure the backend's `_format_ui_context` produces. The pre-formatting moves to the browser (or to a thin server-side endpoint — see § 7.1) so the agent receives the same `<attached_context>...</attached_context>` shape it understands today.
2. **`activeContextManifest: ContextManifest`** — a structured snapshot of currently-attached entities. Pushed into the sandbox via a per-Run "active context" channel (a Redis key, the `set_config_option` command, or a small `_posthog/active_context` payload — see § 5.2) so the MCP server can answer `get_active_context()` without the agent having to repeat IDs from its own context block.

### 3.2 Reducers / selectors / listeners

The logic preserves today's reducer surface 1:1, because manual-add is unchanged from the user's perspective.

Pseudo-shape (interface sketch — not implementation):

```typescript
interface PosthogAiContextValues {
    // Existing per-entity manual reducers (unchanged from maxContextLogic)
    contextInsights: MaxInsightContext[]
    contextDashboards: MaxDashboardContext[]
    contextEvents: MaxEventContext[]
    contextActions: MaxActionContext[]
    contextErrorTrackingIssues: MaxErrorTrackingIssueContext[]
    contextNotebooks: MaxNotebookContext[]
    contextEvaluations: MaxEvaluationContext[]

    // Scene-derived (selector, recomputed naturally)
    sceneContext: MaxContextItem[]
    rawSceneContext: MaxContextInput[]

    // Combined, deduped — same semantics as today's compiledContext
    compiledContext: MaxUIContext | null

    // NEW: pre-formatted XML block, ready to prepend to pending_user_message
    compiledContextBlock: string | null

    // NEW: structured manifest pushed to the MCP server
    activeContextManifest: ContextManifest

    // Taxonomic-filter integration (unchanged surface)
    contextOptions: MaxContextTaxonomicFilterOption[]
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
    mainTaxonomicGroupType: TaxonomicFilterGroupType
    toolContextItems: Array<{ text: string; icon: ComponentType }>
    hasData: boolean
}

interface PosthogAiContextActions {
    // Manual add/remove — names preserved for compatibility with any external triggers
    addOrUpdateContextInsight: (data, filtersOverride?, variablesOverride?) => void
    addOrUpdateContextDashboard: (data) => void
    // ...one per entity type, identical signatures to maxContextLogic
    removeContextInsight: (id: string | number) => void
    // ...
    resetContext: () => void

    // Bulk operations
    handleTaxonomicFilterChange: (value, groupType, item) => void

    // NEW: explicit "context changed, push to sandbox" trigger
    pushActiveContextToRun: (taskId: string, runId: string) => void
}

interface ContextManifest {
    scene: { id: string; path: string } | null
    dashboards: Array<{ id: number; name: string }>
    insights: Array<{ id: string; name: string }>
    events: Array<{ id: string; name: string }>
    actions: Array<{ id: number; name: string }>
    error_tracking_issues: Array<{ id: string; name: string | null }>
    notebooks: Array<{ short_id: string; name: string | null }>
    evaluations: Array<{ id: string; name: string | null; type: 'hog' | 'llm_judge' }>
    updated_at: string
}
```

Listeners:

- **`locationChanged`** — same semantics as today ([`maxContextLogic.ts:222-276`](../../posthog/frontend/src/scenes/max/maxContextLogic.ts)). Reset manual context on path/search-param changes; ignore the `chat` param and the `panel` hash key. Scene-derived context recomputes via the selector with no action needed.
- **`addOrUpdateContext*` / `removeContext*` / `resetContext`** — after any state change while a Run is in `in_progress`, call `pushActiveContextToRun(taskId, runId)` (debounced to ~250 ms).
- **`pushActiveContextToRun`** — issue a `POST /command/` with `{ method: "set_config_option", params: { configId: "posthog_active_context", value: JSON.stringify(activeContextManifest) } }`. This refreshes the in-sandbox MCP server's view of "what's pinned" without restarting the session. See § 5.2.
- **`loadAndProcessDashboard` / `loadAndProcessInsight`** — same as today ([`maxContextLogic.ts:277-354`](../../posthog/frontend/src/scenes/max/maxContextLogic.ts)). When the user selects something via the taxonomic filter that doesn't have a preloaded copy, mount the corresponding logic temporarily, wait for the dashboard/insight to load, then unmount.

The two new selectors (`compiledContextBlock` and `activeContextManifest`) derive from the same union of manual + scene context as `compiledContext` does today.

### 3.3 Compatibility with existing scene `maxContext` selectors

**Recommendation: preserve the selector name and contract verbatim.** Day-one outcome: every scene that currently exposes `maxContext` keeps working with zero changes.

Concretely:

- The new `posthogAiContextLogic.rawSceneContext` selector reads `sceneLogic.selectors.activeSceneLogic` and looks for `'maxContext' in activeSceneLogic.selectors` — identical to [`maxContextLogic.ts:494-516`](../../posthog/frontend/src/scenes/max/maxContextLogic.ts).
- The `MaxContextInput` / `MaxContextItem` / `MaxContextType` / `MaxUIContext` / `createMaxContextHelpers` types in [`maxTypes.ts`](../../posthog/frontend/src/scenes/max/maxTypes.ts) are **re-exported** from a new file `frontend/src/scenes/posthog-ai/contextTypes.ts` so scenes can migrate their imports at their own pace.
- `scenes/max/maxTypes.ts` becomes a thin re-export of `scenes/posthog-ai/contextTypes.ts` during the transition window (Phase 2 → Phase 5).

The scenes that expose `maxContext` today, enumerated for the migration checklist:

| Scene | File | Selector | Action |
|---|---|---|---|
| Dashboard | [`frontend/src/scenes/dashboard/dashboardLogic.tsx:1665-1674`](../../posthog/frontend/src/scenes/dashboard/dashboardLogic.tsx) | `maxContext: [(s) => [s.dashboard], ...]` | No change (Phase 2). Later: switch import from `scenes/max/maxTypes` to `scenes/posthog-ai/contextTypes`. |
| Insight | [`frontend/src/scenes/insights/insightSceneLogic.tsx:352-365`](../../posthog/frontend/src/scenes/insights/insightSceneLogic.tsx) | `maxContext: [(s) => [s.insight, s.filtersOverride, s.variablesOverride], ...]` | No change. |
| Project homepage | [`frontend/src/scenes/project-homepage/projectHomepageLogic.tsx:56-60`](../../posthog/frontend/src/scenes/project-homepage/projectHomepageLogic.tsx) | `maxContext: [() => [], () => []]` (empty stub) | No change. |
| Revenue analytics | [`products/revenue_analytics/frontend/revenueAnalyticsLogic.ts:378-425`](../../posthog/products/revenue_analytics/frontend/revenueAnalyticsLogic.ts) | `maxContext: [...]` (multiple insight inputs) | No change. |
| Error tracking issue | [`products/error_tracking/frontend/scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic.ts:390-410`](../../posthog/products/error_tracking/frontend/scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic.ts) | `maxContext: [(s) => [s.issue, s.issueId], ...]` | No change. |
| LLM evaluations | [`products/llm_analytics/frontend/evaluations/llmEvaluationLogic.ts:769-784`](../../posthog/products/llm_analytics/frontend/evaluations/llmEvaluationLogic.ts) | `maxContext: [...]` | No change. |

Six scenes total today. (The "25+" estimate in the prompt was generous — the actual fan-out is small. Most scenes don't expose context; they rely on the `@`-context taxonomic filter for manual attachment.)

**Why preserving the contract is the right call:**

- Renaming the selector to `posthogAiContext` would force every product team to make a coordinated change for zero functional benefit.
- Scene logics are not internal to Max — they're owned by the respective product teams. Asking them to re-import for cosmetic reasons risks creating churn around the flag flip.
- The selector name has been stable since the feature shipped; tooling (autocomplete, search, references) all expects it.

**If we were to change it:** the only candidate would be `posthogAiContext` to align with the new scene name. The exit strategy would be (a) add a *new* selector that the new logic prefers, (b) keep the old one as a fallback for one release, (c) emit a console warning when only the old selector is present, (d) remove the fallback in the release after that.

---

## 4. The `posthog-context` MCP server (if recommended)

Adopted per § 2.2 (Hybrid). This server provides on-demand detail for entities that are too large or rarely-needed to fit in the per-turn text block.

### 4.1 Tool definitions

The server exposes tools named with the `posthog_context_*` convention. The per-entity assignment (which channel — B or C — owns each shape) is:

| Entity | Per-turn block (channel B) | MCP tool (channel C) | Rationale |
|---|---|---|---|
| Insight | `id` + `name` + `description` + brief query kind label | `posthog_context_get_insight(short_id) -> { query, filters_override, variables_override, executed_result? }` | The query DSL is ~50 lines; rarely needed unless the user asks "why does this insight show what it shows". |
| Dashboard | `id` + `name` + `insight_count` + `insight_summaries: [{id, name}]` | `posthog_context_get_dashboard(id) -> { name, description, filters, tiles: [{...full insight...}] }` | Full dashboard execution can run to multiple KB per tile. |
| Event | Full payload (id + name + description) | _none_ | Always small; fits in the block. |
| Action | Full payload | _none_ | Small. |
| Error-tracking issue | `id` + `name` only | `posthog_context_get_error_tracking_issue(id) -> { stacks, fingerprint, first_seen, last_seen, occurrences, sample_event_uuid }` | Stack traces and event samples are large. |
| Notebook | `short_id` + `title` only | `posthog_context_get_notebook(short_id) -> { content_json, content_text }` | Notebook bodies can be 100+ KB. |
| Evaluation | `id` + `name` + `evaluation_type` + (for hog) `hog_source_preview: first 500 chars` | `posthog_context_get_evaluation(id) -> { ...full evaluation, full hog_source... }` | Hog source can be long; most chats won't need it. |
| Form answers | Full payload in block | _none_ | Already in `MaxUIContext.form_answers`; small. |

Two utility tools cover the manifest layer:

- **`posthog_context_list_active(filter?: { type?: string })`** — returns the `ContextManifest` (see § 3.2). The agent can call this if it wasn't given context in the current user message but wants to know what's pinned.
- **`posthog_context_get_current_scene()`** — returns `{ scene_id, path, title }` for the active page in the browser. Useful when the user says "this dashboard" without naming it.

### 4.2 Where it runs (in-sandbox? piggyback on agent-server?)

The MCP server is **server-side at PostHog cloud, not in-sandbox**. It runs in the existing PostHog Django process and is reachable from the sandbox over an authenticated HTTP MCP transport, registered via `--mcpServers` ([`agent-server.ts` boot CLI](https://github.com/posthog/cloud-agents/agent-server.ts), see `CLOUD_AGENTS_FRONTEND_SPEC.md` § 10.1).

Why not in-sandbox:

- The sandbox is ephemeral. Tools that read PostHog data would need credentials forwarded into the sandbox — already a problem we partially solved for the agent itself via `POSTHOG_PERSONAL_API_KEY`, but doing it for an MCP server inside the same sandbox is redundant.
- The MCP tool is a thin wrapper around `posthog.api.*` viewsets — Django already has the auth, ORM, team scoping, and rate limiting. Reinventing in-sandbox is wasted work.
- A central MCP server serves all sandboxes, with no per-sandbox cold start.
- Future: customer-installed MCPs (see `00_OVERVIEW.md` § 2) can sit alongside, in the same registry.

Wire shape: standard MCP (HTTP/SSE transport), URL `https://{region}.posthog.com/api/projects/{team_id}/mcp/posthog-context/`. Auth: same project-scoped JWT the sandbox already holds — see `CLOUD_AGENTS_FRONTEND_SPEC.md` § 10.4 (`team_id` is in the JWT's `userDataSchema`).

### 4.3 Auth & scoping (must respect team_id)

Every MCP tool call carries the sandbox JWT. The Django endpoint validates the JWT, reads `team_id`, and constrains all queries to that team:

- `posthog_context_get_dashboard(id)` → `Dashboard.objects.filter(team_id=jwt.team_id, id=id).first()`
- `posthog_context_get_insight(short_id)` → equivalent filter by team.
- All entities have a `team_id` (see CLAUDE.md project guidelines on tenant isolation).

The viewset must enforce *both* `team_id` and the caller's user permissions — e.g., if the user pinned a private dashboard they had access to, but the JWT user no longer has that access (revoked between pin and call), the tool must respond with `"access denied"`, not silently leak.

Implementation: reuse the existing DRF viewsets (`DashboardViewSet`, `InsightViewSet`, etc.) — the tool handlers call into them. This guarantees the same permission model. The wrapping layer is a thin MCP-to-DRF adapter.

The `posthog_context_list_active` tool reads from Redis (the channel browser→sandbox uses to push the manifest — see § 5.2). Key shape: `posthog_ai:active_context:{team_id}:{user_id}:{run_id}`. Scoped to `(team, user, run)` so two browser tabs for the same user on different Runs don't collide.

---

## 5. Per-turn vs per-Run context

### 5.1 What triggers a new Run

A new Run is needed when **state.systemPrompt** would change, i.e., when team-scope information (channel A) changes. In practice, that's almost never during a chat:

- Change of `agent_mode` — handled differently per `00_OVERVIEW.md` § 9 / `04_PROMPTS.md` § 4 (may not require a new Run if mode is a `set_config_option` toggle).
- Change of team (user switched projects) — yes, new Run (the JWT and `team_id` differ).
- Change of `core_memory` — no, not for current Run; picked up on next.

**Scene navigation is NOT a Run-restart trigger.** That's the whole reason channel B + C exist.

### 5.2 Refresh via `set_config_option` / `refresh_session`

Two PostHog-cloud command-channel methods are available (`CLOUD_AGENTS_FRONTEND_SPEC.md` § 6.6, § 6.7):

- **`set_config_option(configId, value)`** — agent-server treats it as a config update. We register `posthog_active_context` as a custom config option: when set, the agent-server writes the value to the Redis key `posthog_ai:active_context:{team_id}:{user_id}:{run_id}` (above). The MCP server reads from this key. **Cheap, no session restart, no model wake-up.**
- **`refresh_session(mcpServers)`** — heavy: re-initializes the session with a new MCP server list. We use this only when the *set* of available MCPs needs to change (e.g., a contextual tool registers via `useMaxTool` during a chat) — not for context payload changes.

So: scene-change inside an active chat triggers `pushActiveContextToRun → set_config_option("posthog_active_context", JSON.stringify(manifest))`. The MCP server's `posthog_context_list_active()` returns the new value immediately. The model wakes on the next turn; it sees the same systemPrompt but freshly-pinned context.

### 5.3 What goes into `state.pending_user_message` vs systemPrompt

For each user message:

```
pending_user_message = compiledContextBlock || '' + '\n\n' + userPromptText
```

…or, in cloud-prompt multi-block form ([`packages/shared/src/cloud-prompt.ts`](../../Twig/packages/shared/src/cloud-prompt.ts)):

```typescript
const blocks: ContentBlock[] = [
    ...(compiledContextBlock ? [{ type: 'text', text: compiledContextBlock }] : []),
    { type: 'text', text: userPromptText },
    ...artifactBlocks,
]
const wireString = serializeCloudPrompt(blocks)
```

The `compiledContextBlock` matches today's `_format_ui_context` output: the same `<attached_context>...</attached_context>` structure (or close to it) so the prompts in `04_PROMPTS.md` keep referencing it idiomatically.

What does NOT go into `pending_user_message`:

- Group types — already in systemPrompt.
- Core memory — already in systemPrompt.
- Billing context — already in systemPrompt.
- Full insight queries — fetchable via `posthog_context_get_insight`.
- Full dashboard execution — fetchable via `posthog_context_get_dashboard`.
- Notebook body — fetchable via `posthog_context_get_notebook`.

The agent's tool-use cadence will be: read the per-turn block to see what's pinned, then call MCP tools selectively for the entities that need depth. This is identical to how PostHog Code reads the repo today — a brief "you're in this codebase with these files in the working tree" block and then `Read`/`Grep` for specifics.

---

## 6. Type system changes

### 6.1 What stays in maxTypes.ts (rename target)

[`maxTypes.ts`](../../posthog/frontend/src/scenes/max/maxTypes.ts) gets renamed/moved to `frontend/src/scenes/posthog-ai/contextTypes.ts`. All exports survive:

- `MaxContextType` enum
- `MaxInsightContext`, `MaxDashboardContext`, `MaxEventContext`, `MaxActionContext`, `MaxErrorTrackingIssueContext`, `MaxEvaluationContext`, `MaxNotebookContext`
- `MaxUIContext`
- `MaxContextItem`, `MaxContextInput` unions
- `MaxContextTaxonomicFilterOption`
- `createMaxContextHelpers`
- `InsightWithQuery`

The names keep the `Max` prefix during the transition window — renaming them to `PosthogAi*` is a follow-up cleanup task. The reason for keeping the prefix is the same as keeping the scene `maxContext` selector name: every product team's imports break if we rename.

In the meantime, `scenes/max/maxTypes.ts` becomes a re-export shim:

```typescript
export * from 'scenes/posthog-ai/contextTypes'
```

When `scenes/max/` is deleted in Phase 5, the shim goes with it. By then product teams have had time to update their imports.

### 6.2 What changes

- `isAgentMode` (helper at end of [`maxTypes.ts:233-235`](../../posthog/frontend/src/scenes/max/maxTypes.ts)) — moves to `scenes/posthog-ai/modeUtils.ts`, since agent-mode handling is owned by `04_PROMPTS.md`. Out of this spec.

### 6.3 New types

```typescript
// scenes/posthog-ai/contextTypes.ts

/** Snapshot of currently-attached entities for the in-sandbox MCP server. */
export interface ContextManifest {
    scene: { id: string; path: string } | null
    dashboards: Array<{ id: number; name: string }>
    insights: Array<{ id: string; name: string }>
    events: Array<{ id: string; name: string }>
    actions: Array<{ id: number; name: string }>
    error_tracking_issues: Array<{ id: string; name: string | null }>
    notebooks: Array<{ short_id: string; name: string | null }>
    evaluations: Array<{ id: string; name: string | null; type: 'hog' | 'llm_judge' }>
    updated_at: string
}

/** Output of compileContextBlock — the XML-tagged text block for pending_user_message. */
export type CompiledContextBlock = string
```

---

## 7. Backend changes

### 7.1 Pre-interpolation hook in Task creation

When a Run is created (`POST /tasks/{id}/run/` — `CLOUD_AGENTS_FRONTEND_SPEC.md` § 4.3), the backend resolves the systemPrompt server-side and writes it to a place the agent-server reads at session init. The architecture for this is owned by `04_PROMPTS.md`. This spec only defines the `{{ui_context_static}}` slot:

```python
# In the to-be-built build_posthog_ai_system_prompt(team, user) (see 04_PROMPTS.md):

format_args = {
    # ... existing slots (role, tone, basic functionality, mode prompt, …) ...
    "groups_prompt": …,                # already exists today
    "core_memory": …,                  # already exists today
    "billing_context": …,              # already exists today

    # NEW: the static, team-scoped context that doesn't change per turn
    "ui_context_static": format_static_ui_context(team, user),
}
```

`format_static_ui_context` includes:

- Project name + URL slug.
- A canonical list of group type display names (today's `ROOT_GROUPS_PROMPT`).
- A brief description of available MCP context tools so the agent knows it can fetch.

The bulk of `_format_ui_context` (dashboards, insights, events, …) does **not** move to the systemPrompt — it moves to either the per-turn block (browser-rendered, see § 5.3) or the MCP server's tool responses (server-rendered on demand).

There is one subtle migration: `_format_ui_context` today *executes* dashboards and insights inline ([`context.py:174-235`](../../posthog/ee/hogai/context/context.py)). In the new world, that execution moves into `posthog_context_get_dashboard` / `posthog_context_get_insight` — the agent only pays the execution cost if it actually fetches.

For the per-turn block (browser-rendered), we want to mirror the existing `<attached_context>` shape so prompts don't change semantically. A small Django endpoint can render this if we don't want to duplicate Mustache templating in the browser:

- **`POST /api/projects/{team_id}/posthog_ai/context/render_block/`** — body: `MaxUIContext` minus heavy fields. Response: `{ block: string }` containing the formatted XML.
- Alternatively (recommended): port `_format_ui_context`'s string-template logic to TypeScript in `frontend/src/scenes/posthog-ai/contextRenderer.ts`. This eliminates one round-trip per turn at the cost of duplicating template logic. Trade-off: the prompt format is intentionally stable (the agent has to parse it), so duplicating it is low-risk.

**Recommendation: render the per-turn block in the browser.** The template is small (~30 lines of `_format_ui_context` work), removing a network hop per turn is worth more than the duplication.

### 7.2 (If MCP route chosen) the new MCP endpoint

Endpoint root: `/api/projects/{team_id}/mcp/posthog-context/` (or whatever URL the existing MCP framework — see `services/mcp/` — produces; we register a new tool group).

The tools listed in § 4.1 are implemented as Django views that:

1. Validate the sandbox JWT (already a middleware concern in the existing MCP setup).
2. Resolve `team_id` from the JWT and check `team_id == path team_id`.
3. Dispatch to the existing DRF viewset for the corresponding entity (e.g. `DashboardViewSet.retrieve`).
4. Return MCP-shaped JSON.

For `posthog_context_list_active`, the implementation reads from the Redis key set by `set_config_option` (§ 5.2):

```python
def list_active(team_id: int, user_id: int, run_id: str) -> ContextManifest:
    key = f"posthog_ai:active_context:{team_id}:{user_id}:{run_id}"
    raw = redis_client.get(key)
    return json.loads(raw) if raw else empty_manifest()
```

The browser pushes manifest updates via `set_config_option("posthog_active_context", json.dumps(manifest))`; the agent-server's `set_config_option` handler writes that to Redis (or proxies directly if the MCP server runs in the same Django process — even cheaper).

### 7.3 Permissions and team isolation

Three rules:

1. **JWT scope.** The sandbox JWT contains `team_id` and `user_id` ([`packages/agent/src/server/jwt.ts`](../../Twig/packages/agent/src/server/jwt.ts), see `CLOUD_AGENTS_FRONTEND_SPEC.md` § 10.4). Every MCP tool extracts both. Mismatched `team_id` between JWT and URL path → 403.
2. **Object-level access checks.** Each `posthog_context_get_*` tool delegates to the existing DRF viewset's `get_object()` / `check_object_permissions()` so private dashboards, restricted insights, and team-scoped notebooks all check the same way they do in the UI.
3. **Active-context manifest is per-Run, not per-team.** Two Runs from the same user have different keys. This prevents (a) accidentally leaking pinned context across chats and (b) keeping stale entries forever.

The CLAUDE.md tenant-isolation rules apply directly: any new Django model touched by this work must have `team_id` and any new query path must scope. The MCP tools wrap DRF viewsets, so they inherit the existing `TeamScopedRootMixin` behavior — no new models.

---

## 8. Migration checklist (concrete line-by-line)

**Phase 2: Context (per `00_OVERVIEW.md` § 7).** Order matters — checklist runs top-to-bottom.

### Code moves

- [ ] Create `frontend/src/scenes/posthog-ai/contextTypes.ts` — copy [`frontend/src/scenes/max/maxTypes.ts`](../../posthog/frontend/src/scenes/max/maxTypes.ts) verbatim. Re-export everything.
- [ ] Convert `frontend/src/scenes/max/maxTypes.ts` to a re-export shim: `export * from 'scenes/posthog-ai/contextTypes'`. Keep `isAgentMode` here (it's owned by 04_PROMPTS, not this spec).
- [ ] Create `frontend/src/scenes/posthog-ai/contextRenderer.ts` — TypeScript port of `_format_ui_context` ([`ee/hogai/context/context.py:160-335`](../../posthog/ee/hogai/context/context.py)). Output: a single XML-tagged string (the `<attached_context>` body). Drop dashboard execution and insight execution — those move to MCP tools.
- [ ] Create `frontend/src/scenes/posthog-ai/posthogAiContextLogic.ts` — port [`frontend/src/scenes/max/maxContextLogic.ts`](../../posthog/frontend/src/scenes/max/maxContextLogic.ts):
  - [ ] Preserve all reducer + action signatures (manual add/remove for each of the seven entity types).
  - [ ] Preserve `rawSceneContext` selector → `sceneLogic.selectors.activeSceneLogic` reflection ([`:494-516`](../../posthog/frontend/src/scenes/max/maxContextLogic.ts)).
  - [ ] Preserve `sceneContext` selector — map MaxContextInput → MaxContextItem via existing converters in [`utils.ts`](../../posthog/frontend/src/scenes/max/utils.ts).
  - [ ] Preserve `compiledContext` selector — same dedup + merge semantics ([`:631-760`](../../posthog/frontend/src/scenes/max/maxContextLogic.ts)).
  - [ ] Preserve `contextOptions` selector — feeds the TaxonomicPopover ([`:544-604`](../../posthog/frontend/src/scenes/max/maxContextLogic.ts)).
  - [ ] Preserve `mainTaxonomicGroupType` + `taxonomicGroupTypes` selectors.
  - [ ] Preserve `locationChanged` listener — reset on path/search-param change, ignore `chat` and `panel` keys ([`:222-276`](../../posthog/frontend/src/scenes/max/maxContextLogic.ts)).
  - [ ] Preserve `loadAndProcessDashboard` + `loadAndProcessInsight` listeners ([`:277-354`](../../posthog/frontend/src/scenes/max/maxContextLogic.ts)).
  - [ ] Preserve `handleTaxonomicFilterChange` listener ([`:355-488`](../../posthog/frontend/src/scenes/max/maxContextLogic.ts)).
  - [ ] **NEW:** Add `compiledContextBlock` selector — derive from `compiledContext`, call `renderContextBlock(compiledContext)` from `contextRenderer.ts`.
  - [ ] **NEW:** Add `activeContextManifest` selector — a structurally-flat snapshot (IDs + names only, no queries / bodies).
  - [ ] **NEW:** Add `pushActiveContextToRun({ taskId, runId })` action + listener that issues `POST /command/` with `set_config_option`. Debounce ~250 ms in the listener via `cache.disposables.add` (per the kea-disposables rule in CLAUDE.md).
  - [ ] **NEW:** Wire `pushActiveContextToRun` to fire on every successful state change (after any add/remove action) — but only when there's an active Run.
- [ ] Move `frontend/src/scenes/max/Context.tsx` → `frontend/src/scenes/posthog-ai/Context.tsx` (or split into smaller components). Replace import of `maxContextLogic` with `posthogAiContextLogic`; replace import of `maxThreadLogic` with `posthogAiThreadLogic` (the latter is owned by `02_CORE.md`).
- [ ] Move `frontend/src/scenes/max/utils.ts` *context converters only* (`insightToMaxContext`, `dashboardToMaxContext`, `eventToMaxContextPayload`, `actionToMaxContextPayload`, `errorTrackingIssueToMaxContextPayload`, `notebookToMaxContextPayload`, `evaluationToMaxContextPayload`, `convertToMaxUIContext`, `MaxOpenContext`) → `frontend/src/scenes/posthog-ai/contextConverters.ts`. The rest of `utils.ts` (`isAssistantMessage`, etc.) stays in `02_CORE.md` / `03_RICH_UI.md` territory.

### Backend additions

- [ ] Create `posthog/api/posthog_ai/context.py` — new DRF view module exposing `/api/projects/{team_id}/posthog_ai/context/` for any browser-side context endpoints (e.g., active-context push if we go via cloud rather than direct sandbox command).
- [ ] Add MCP tool group `posthog-context` under `services/mcp/` (per the `implementing-mcp-tools` skill convention referenced in CLAUDE.md). Tools defined in § 4.1.
- [ ] Implement `format_static_ui_context(team, user)` per § 7.1. Add a slot in the new `build_posthog_ai_system_prompt` (owned by `04_PROMPTS.md`).
- [ ] Wire `set_config_option("posthog_active_context", value)` → write to Redis key `posthog_ai:active_context:{team_id}:{user_id}:{run_id}`. This may live in the agent-server (`agent-server.ts`) or in the cloud relay; decision belongs to `02_CORE.md`. From this spec's perspective the contract is just "browser pushes a manifest, MCP server reads it".

### Scene compatibility

- [ ] Verify `dashboard/dashboardLogic.tsx` `maxContext` still works against `posthogAiContextLogic` (no code change expected).
- [ ] Verify `insights/insightSceneLogic.tsx` `maxContext` still works.
- [ ] Verify `project-homepage/projectHomepageLogic.tsx` `maxContext` still works.
- [ ] Verify `revenue_analytics/frontend/revenueAnalyticsLogic.ts` `maxContext` still works.
- [ ] Verify `error_tracking/.../errorTrackingIssueSceneLogic.ts` `maxContext` still works.
- [ ] Verify `llm_analytics/frontend/evaluations/llmEvaluationLogic.ts` `maxContext` still works.
- [ ] Update the documentation: copy [`frontend/src/scenes/max/README.md`](../../posthog/frontend/src/scenes/max/README.md) to `frontend/src/scenes/posthog-ai/README.md` and adjust import paths in code examples.

### Teardown (Phase 5)

- [ ] Delete `frontend/src/scenes/max/maxContextLogic.ts`, `Context.tsx`, `utils.ts` (the context converter half), `maxTypes.ts` shim.
- [ ] Remove the shim re-export once no consumer remains.

### Sanity-test list

- [ ] Open a dashboard, open Max, send a message → manifest contains the dashboard ID/name.
- [ ] Same, but navigate to an insight inside that dashboard → manifest updates without restarting the Run.
- [ ] Open an error-tracking issue → manual `@`-add another error issue → both appear; remove one → only the kept one remains.
- [ ] Multi-tab: open two Max chats in two tabs on different scenes → each chat's active-context manifest is isolated by `run_id`.
- [ ] Verify MCP server's `posthog_context_get_dashboard(id)` denies access to a dashboard the calling user can't see (private dashboard owned by another user).
- [ ] Verify the per-turn block has the same `<attached_context>` shape as today's `_format_ui_context` output for at least one canonical dashboard + insight combination (snapshot test).
- [ ] Verify `pushActiveContextToRun` debounces — rapid scene navigation produces one `set_config_option` after the user settles.
- [ ] Verify scene resets — navigating away from a dashboard scene clears the dashboard from `compiledContext`.

---

## 9. Open questions

1. **Per-turn block: browser-rendered or server-rendered?** Recommendation in § 7.1 is browser-rendered. The trade-off is duplicating ~30 lines of templated XML across Python and TypeScript. If the team prefers a single source of truth, switch to a `POST /api/projects/{tid}/posthog_ai/context/render_block/` endpoint. *Owner: AI + frontend.*
2. **Active-context push channel: `set_config_option` vs custom `_posthog/active_context` notification?** `set_config_option` is generic and already understood by the agent-server (`CLOUD_AGENTS_FRONTEND_SPEC.md` § 6.6). Defining a custom command would be cleaner but requires agent-server changes. Recommendation: start with `set_config_option`; reserve a custom command if instrumentation needs grow. *Owner: AI + agent-server.*
3. **MCP server: in the existing Django MCP framework, or a new microservice?** The existing MCP framework (under `services/mcp/`) is the obvious home. Confirm. *Owner: backend.*
4. **Dashboard execution lazy-fetch performance.** Today's `_format_ui_context` executes dashboards inline; we're proposing the agent will fetch on demand via `posthog_context_get_dashboard`. For chats that *always* need a dashboard's numbers, this adds one MCP round-trip vs. today's zero. Do we want a "warm" mode where the per-turn block opts into inlining for small dashboards? *Owner: AI.*
5. **Cap on per-turn block size.** Today's `ui_context` has no enforced limit; in practice it's bounded by serializer constraints. We should pick a soft cap (say, 64 KB) for the rendered text block and degrade gracefully (skip large entities, point the agent at MCP). *Owner: AI.*
6. **Privacy / sensitive data.** The current `_format_ui_context` does not filter personally-identifying data out of dashboard execution results — same fields that appear in the dashboard appear in the prompt. In the cloud-agent model, execution moves to MCP, so the same data flows through the tool result. Do we need any new redaction layer for sensitive person properties (e.g., `email`, `name`)? *Owner: privacy + AI.* Note: current dashboards rendered as context can leak person.properties; if that's a known acceptable behavior today, the cloud-agent model preserves it. If it isn't acceptable today, we should fix the inline path first.
7. **Form answers.** `MaxUIContext.form_answers` ([`maxTypes.ts:87`](../../posthog/frontend/src/scenes/max/maxTypes.ts)) is populated when the user fills out a `create_form` tool response. It's an in-chat artifact, not a scene-derived one. The migration plan above doesn't touch it; confirm with `03_RICH_UI.md` that form answers ride a separate channel in the new world (likely an ACP `tool_call_update` carrying user input). *Owner: AI.*
8. **Selector name evolution.** Recommendation in § 3.3 is to keep `maxContext`. If product teams strongly prefer `posthogAiContext`, add a fallback path (prefer new, fall back to old, warn). Either way, decide once. *Owner: product + AI.*
9. **Revenue analytics special-case.** Today, `revenueAnalyticsLogic` exposes synthetic insights with `REVENUE_ANALYTICS_QUERY_TO_SHORT_ID` short IDs that don't correspond to a real `Insight` row ([`maxContextLogic.ts:317-328`](../../posthog/frontend/src/scenes/max/maxContextLogic.ts)). The MCP `posthog_context_get_insight(short_id)` tool would need a special branch for these (look up the live revenue analytics query rather than the DB row). *Owner: revenue analytics team.*
10. **Scene-derived vs manual differentiation.** Today, the UI surfaces tool-context items differently from manual tags. We should preserve the visual distinction in the new world (auto-included vs user-pinned). Confirm with `03_RICH_UI.md`'s rendering plan. *Owner: AI design.*
