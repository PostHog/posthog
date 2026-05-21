# MCP tool contracts

Per-tool input/output JSON shapes for the MCP servers spec'd in [`04_PROMPTS.md`](./04_PROMPTS.md) § 5.
Renderer adapters in [`03_RICH_UI.md`](./03_RICH_UI.md) § 4 reference these shapes via `rawInput` / `rawOutput`.

Without this file, the MCP-server implementer and the renderer-adapter implementer can't work in parallel — one has to wait on the other to invent shapes.
With it, both lanes work off the same contract from Day 1.

---

## Conventions

- **Qualified name**: `{server}.{tool}` (e.g. `posthog-data.read_dashboard`).
- **Input shape**: JSONSchema-shaped object passed as the MCP tool call's `arguments`. Surfaces in the ACP frame as `tool_call.rawInput`.
- **Output shape**: the structured value the tool returns. Surfaces in `tool_call_update` frames as either `rawOutput` (structured) or as `content[]` text frames (streamed). Tools that emit progress mid-call use `content[]`; tools that return a single artifact use `rawOutput`.
- **Permission mode**: `read` tools never trigger `permission_request`. `write` tools surface a `permission_request` under `state.initial_permission_mode = "default"` (per [`02_CORE.md`](./02_CORE.md) § 6.1) and block until the user responds.
- **Error shape**: per cloud spec § 5.6 — `{ errorTitle, errorMessage, retryable }`. Tools should map domain errors into this envelope rather than surfacing raw stack traces.
- **All tools team-scope** via the sandbox JWT's `team_id` claim (per [`04_PROMPTS.md`](./04_PROMPTS.md) § 5.2). No tool accepts `team_id` in its input — it's always implicit from auth.

---

## posthog-data

**Scope:** taxonomy reads, ad-hoc data queries, insight / dashboard / alert CRUD, error tracking, session replay search, surveys, flags, LLM analytics, ephemeral query tools.

**Auth:** sandbox JWT → DRF middleware extracts `team_id` + `user_id` (per `services/mcp/` convention).

### `posthog-data.read_dashboard`

- **Permission:** read.
- **Input:**
  ```json
  { "id": "<dashboard_id: int>" }
  ```
- **Output (`rawOutput`):**
  ```json
  {
    "id": 123,
    "name": "Marketing Funnel",
    "description": "...",
    "tiles": [
      { "id": 1, "insight_id": 456, "name": "Signups", "type": "trends", "query_summary": "..." }
    ],
    "filters": { "date_from": "-30d", "...": "..." },
    "url": "https://us.posthog.com/dashboard/123"
  }
  ```
- **Errors:** 404 → `{ errorTitle: "Dashboard not found", errorMessage: "Dashboard 123 doesn't exist or you don't have access", retryable: false }`.
- **Renderer adapter:** Fallback card with `name` + `url`. **TODO — confirm** if we want an inline dashboard preview component.

### `posthog-data.read_insight`

- **Permission:** read.
- **Input:**
  ```json
  { "id": "<insight_short_id: string>" }
  ```
- **Output (`rawOutput`):** `VisualizationArtifactContent` shape (`{ query, source, artifact_id }`) so the existing `VisualizationArtifactAnswer` renderer can consume it directly.
- **Renderer adapter:** `CreateInsightAdapter` reused (per [`03_RICH_UI.md`](./03_RICH_UI.md) § 4 — `create_insight` / `edit_insight` row).

### `posthog-data.execute_sql`

- **Permission:** read.
- **Input:**
  ```json
  { "query": "<hogql: string>" }
  ```
- **Output:** mixed — `rawOutput` carries `VisualizationArtifactContent` when results are tabular; `content[]` text frames carry result blobs otherwise. **TODO — confirm** the cutoff.
- **MCP resources:** `schema://hogql/functions`, `schema://hogql/aggregations`, `schema://hogql/expressions` — the long-form HogQL reference docs (per [`04_PROMPTS.md`](./04_PROMPTS.md) § 5.3 / row for `HOGQL_GENERATOR_SYSTEM_PROMPT`).
- **Renderer adapter:** `ExecuteSqlAdapter` (new).

### `posthog-data.create_insight` / `posthog-data.edit_insight`

- **Permission:** **write** (`acceptEdits` equivalent — surfaces `permission_request`).
- **Input:**
  ```json
  { "query": "<query_shape>", "name": "<string>", "artifact_id": "<insight_short_id?>" }
  ```
  (`artifact_id` present on `edit_insight`, absent on `create_insight`.)
- **Output (`rawOutput`):** `VisualizationArtifactContent` (`{ query, source: ArtifactSource.Insight, artifact_id }`).
- **Renderer adapter:** `CreateInsightAdapter` (single adapter handles both create + edit; discriminates on presence of `artifact_id`).

### Read-style siblings (one tool per sub-kind — see [`03_RICH_UI.md`](./03_RICH_UI.md) § 4 row for `read_data`)

Per the resolved open question in [`03_RICH_UI.md`](./03_RICH_UI.md) § 10 #2, the existing PostHog MCP server exposes each sub-kind as a first-class tool. List grows as new entity types are added; each row below is the minimum contract:

| Tool name | Input | Output | Renderer |
|-----------|-------|--------|----------|
| `posthog-data.read_data_warehouse_schema` | `{ table_name?: string }` | `content[]` text frames | Fallback |
| `posthog-data.read_actions` | `{ id?: int }` | `content[]` | Fallback |
| `posthog-data.read_event_definition` | `{ event_name: string }` | `content[]` | Fallback |
| `posthog-data.read_evaluation` | `{ id: string }` | `content[]` | Fallback |
| `posthog-data.list_data` | `{ kind: enum, offset?: int }` | `content[]` list excerpts | Fallback |
| `posthog-data.search` | `{ kind: enum, query: string }` | `content[]` list excerpts | Fallback |

**TODO — enumerate the full sub-kind set** by walking the existing PostHog MCP server's tool registry. The list above is non-exhaustive.

### Write-style siblings (require `permission_request`)

| Tool name | Input | Output | Renderer |
|-----------|-------|--------|----------|
| `posthog-data.upsert_dashboard` | `{ action: 'create' \| 'update', dashboard: {...} }` | `rawOutput: { dashboard_id, url }` | `UpsertDashboardAdapter` (new) |
| `posthog-data.upsert_alert` | `{ action, alert: {...} }` | `rawOutput: { alert_id, url }` | Fallback |
| `posthog-data.create_user_interview_topic` | `{ name, questions: [...] }` | `rawOutput: { topic_id, url }` | Fallback |

### Specialized read tools

| Tool name | Input | Output | Renderer |
|-----------|-------|--------|----------|
| `posthog-data.search_session_recordings` | `{ query, filters: {...} }` | `rawOutput: { filters: RecordingUniversalFilters }` | `SearchSessionRecordingsAdapter` |
| `posthog-data.filter_session_recordings` | `{ recordings_filters: {...} }` | `rawOutput: { filters }` | `FilterSessionRecordingsAdapter` |
| `posthog-data.summarize_sessions` | `{ session_ids?, summary_title? }` | Streamed `content[]` text frames carrying `SessionSummarizationUpdate` JSON; final `rawOutput: { session_group_summary_id, title }` | `SummarizeSessionsAdapter` |
| `posthog-data.search_error_tracking_issues` | `{ search_query, status?, ... }` | `rawOutput: MaxErrorTrackingSearchResponse` | `SearchErrorTrackingIssuesAdapter` |
| `posthog-data.filter_error_tracking_issues` | `{ filters }` | `rawOutput: MaxErrorTrackingSearchResponse` | Same as above |
| `posthog-data.experiment_results_summary` | `{ experiment_id }` | `content[]` text | Fallback |
| `posthog-data.analyze_user_interviews` | `{ topic_id }` | `content[]` themes | Fallback |
| `posthog-data.search_llm_traces` | `{ query, period? }` | `content[]` list + `rawOutput.url` | Fallback (CTA) |
| `posthog-data.web_analytics_doctor` | `{}` | `content[]` text | Fallback |
| `posthog-data.diagnose_proxy` | `{}` | `content[]` text | Fallback |
| `posthog-data.filter_revenue_analytics` | `{ filters }` | `rawOutput: { url }` | Fallback (CTA) |
| `posthog-data.filter_web_analytics` | `{ filters }` | `rawOutput: { url }` | Fallback (CTA) |

**Dropped from this catalog** (per resolved open questions):

- `fix_hogql_query` — tool dropped; replaced by an in-UI trigger ([`TODO.md`](./TODO.md) "Insight editor → Max 'fix this query' trigger").
- `create_form` — deferred ([`TODO.md`](./TODO.md) "MultiQuestionForm answer channel").

---

## posthog-notebook

**Scope:** notebook + message-template CRUD.

| Tool name | Input | Output | Renderer | Permission |
|-----------|-------|--------|----------|-----------|
| `posthog-notebook.create_notebook` | `{ title, prompt }` | `rawOutput: { blocks: DocumentBlock[], title, artifact_id }` (single delivery on completion — streaming deferred per [`TODO.md`](./TODO.md) "Notebook block streaming") | `CreateNotebookAdapter` → `NotebookArtifactAnswer` | write |
| `posthog-notebook.update_notebook` | `{ notebook_id, patch }` | `rawOutput: { blocks, title, artifact_id }` | Same | write |
| `posthog-notebook.get_notebook` | `{ notebook_id }` | `rawOutput: { blocks, title }` | Fallback or reuse `NotebookArtifactAnswer` (read-only) | read |
| `posthog-notebook.list_notebooks` | `{}` | `content[]` text list | Fallback | read |
| `posthog-notebook.create_message_template` | `{ name, prompt }` | `rawOutput: { template_id }` | Fallback | write |

---

## posthog-code

**Scope:** PostHog Code integration — exposes Code's task/run primitives so the agent can spin up Code tasks from chat. Gated by `has_phai_tasks` feature flag.

| Tool name | Input | Output | Renderer | Permission |
|-----------|-------|--------|----------|-----------|
| `posthog-code.create_task` | `{ title, repository, prompt }` | `rawOutput: { task_id, url }` | Fallback (CTA) | write |
| `posthog-code.run_task` | `{ task_id }` | `rawOutput: { run_id, url }` | Fallback (CTA) | write |
| `posthog-code.get_task_run` | `{ run_id }` | `content[]` status text | Fallback | read |
| `posthog-code.get_task_run_logs` | `{ run_id }` | `content[]` logs (truncated) | Fallback | read |
| `posthog-code.list_tasks` | `{ repository?, status? }` | `content[]` text list | Fallback | read |
| `posthog-code.list_task_runs` | `{ task_id }` | `content[]` text list | Fallback | read |
| `posthog-code.list_repositories` | `{}` | `content[]` text list | Fallback | read |

---

## Claude Code SDK built-ins (no MCP server)

Some tools are provided by the Claude Code SDK directly and don't require a PostHog-side MCP server:

| Tool name | Notes |
|-----------|-------|
| `TodoWrite` | SDK built-in (per [`04_PROMPTS.md`](./04_PROMPTS.md) § 5.1 — resolved decision). Renderer adapter: `TodoWriteAdapter` → `PlanningAnswer` (per [`03_RICH_UI.md`](./03_RICH_UI.md) § 4). |
| `WebSearch` | SDK built-in. Bedrock-routed sandboxes must disable it ([`TODO.md`](./TODO.md) "Web search tool placement"). |
| `EnterPlanMode` | SDK built-in. No renderer — surfaces as a mode badge via `current_mode_update` (per [`03_RICH_UI.md`](./03_RICH_UI.md) § 6). |

---

## User-installed MCPs

Pass-through. The frontend uses the fallback renderer (`FallbackMcpToolRenderer.tsx`) for any qualified name not in the registry — see [`03_RICH_UI.md`](./03_RICH_UI.md) § 3.4.

No spec needed per tool — the user's own MCP server is the source of truth.

---

## Authoring this file as tools land

Every MCP-server PR (`MCP-A`, `MCP-B`, `MCP-C` in `00_OVERVIEW.md` § 10) must add or update its server's section here with the actual shapes shipped. Renderer-adapter PRs (`UI-A`, `UI-B`) read shapes from here as their input.

When a tool changes shape mid-rollout (input/output evolves), update this file in the same PR. Treat it as the **contract** between MCP and frontend — no out-of-band changes.
