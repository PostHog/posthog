# MCP tool contracts

Per-tool input/output JSON shapes for the inner tools spec'd in [`04_PROMPTS.md`](./04_PROMPTS.md) § 5.
Renderer adapters in [`03_RICH_UI.md`](./03_RICH_UI.md) § 4 reference these shapes via `rawInput` / `rawOutput`.

Without this file, the inner-tool implementer and the renderer-adapter implementer can't work in parallel — one has to wait on the other to invent shapes.
With it, both lanes work off the same contract from Day 1.

---

## Conventions

- **Single-exec `posthog` MCP server with inner tools**: there is ONE single-exec `posthog` MCP server (`services/mcp/`) exposing ONE outer `exec` tool (`services/mcp/src/tools/exec.ts:120`). The names below (e.g. `read_dashboard`) are **inner tool** names invoked through that one `exec` tool — they are NOT `posthog-data.read_dashboard` across multiple servers. Inner tools are enabled per-yaml (`enabled: true` in `services/mcp/definitions/*.yaml`) and filtered at runtime by scopes + feature flags + version, NOT by consumer (`services/mcp/src/hono/tool-catalog.ts:170`). The renderer keys on the inner tool name returned inside the `exec` result.
- **Consumer identity**: PostHog AI declares itself via the `x-posthog-mcp-consumer: posthog-ai` header (read at `services/mcp/src/lib/request-properties.ts:74`; PostHog Code's `POSTHOG_CODE_CONSUMER` is defined at `services/mcp/src/lib/client-detection.ts:72`); PostHog Code uses `posthog-code`. The header does not gate inner tools — it identifies the consumer for telemetry and client-detection.
- **Input shape**: JSONSchema-shaped object passed as the inner tool's `arguments` (carried inside the `exec` call). Surfaces in the ACP frame as `tool_call.rawInput`.
- **Output shape**: the structured value the inner tool returns. Surfaces in `tool_call_update` frames as either `rawOutput` (structured) or as `content[]` text frames (streamed). Tools that emit progress mid-call use `content[]`; tools that return a single artifact use `rawOutput`.
- **Permission mode**: `read` tools never trigger `permission_request`. `write` tools surface a `permission_request` under `state.initial_permission_mode = "default"` (per [`02_CORE.md`](./02_CORE.md) § 6.1) and block until the user responds.
- **Error shape**: per cloud spec § 5.6 — `{ errorTitle, errorMessage, retryable }`. Tools should map domain errors into this envelope rather than surfacing raw stack traces.
- **All tools team-scope** via the sandbox JWT's `team_id` claim (per [`04_PROMPTS.md`](./04_PROMPTS.md) § 5.2). No tool accepts `team_id` in its input — it's always implicit from auth.

---

## Data inner tools

**Note:** "Data" is a _grouping category_ for inner tools on the single `posthog` server — not a separate server. All names below are inner tool names invoked through the one `exec` tool.

**Scope:** taxonomy reads, ad-hoc data queries, insight / dashboard / alert CRUD, error tracking, session replay search, surveys, flags, LLM analytics, ephemeral query tools.

**Auth:** sandbox JWT → DRF middleware extracts `team_id` + `user_id` (per `services/mcp/` convention).

### `read_dashboard`

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
    "tiles": [{ "id": 1, "insight_id": 456, "name": "Signups", "type": "trends", "query_summary": "..." }],
    "filters": { "date_from": "-30d", "...": "..." },
    "url": "https://us.posthog.com/dashboard/123"
  }
  ```

- **Errors:** 404 → `{ errorTitle: "Dashboard not found", errorMessage: "Dashboard 123 doesn't exist or you don't have access", retryable: false }`.
- **Renderer adapter:** Fallback card with `name` + `url`. **TODO — confirm** if we want an inline dashboard preview component.

### `read_insight`

- **Permission:** read.
- **Input:**

  ```json
  { "id": "<insight_short_id: string>" }
  ```

- **Output (`rawOutput`):** `VisualizationArtifactContent` shape (`{ query, source, artifact_id }`) so the existing `VisualizationArtifactAnswer` renderer can consume it directly.
- **Renderer adapter:** `CreateInsightAdapter` reused (per [`03_RICH_UI.md`](./03_RICH_UI.md) § 4 — `create_insight` / `edit_insight` row).

### `execute_sql`

- **Permission:** read.
- **Input:**

  ```json
  { "query": "<hogql: string>" }
  ```

- **Output:** mixed — `rawOutput` carries `VisualizationArtifactContent` when results are tabular; `content[]` text frames carry result blobs otherwise. **TODO — confirm** the cutoff.
- **MCP resources:** `schema://hogql/functions`, `schema://hogql/aggregations`, `schema://hogql/expressions` — the long-form HogQL reference docs (per [`04_PROMPTS.md`](./04_PROMPTS.md) § 5.3 / row for `HOGQL_GENERATOR_SYSTEM_PROMPT`).
- **Renderer adapter:** `ExecuteSqlAdapter` (new).

### `create_insight` / `edit_insight`

- **Permission:** **write** (`acceptEdits` equivalent — surfaces `permission_request`).
- **Input:**

  ```json
  { "query": "<query_shape>", "name": "<string>", "artifact_id": "<insight_short_id?>" }
  ```

  (`artifact_id` present on `edit_insight`, absent on `create_insight`.)

- **Output (`rawOutput`):** `VisualizationArtifactContent` (`{ query, source: ArtifactSource.Insight, artifact_id }`).
- **Renderer adapter:** `CreateInsightAdapter` (single adapter handles both create + edit; discriminates on presence of `artifact_id`).

### Read-style siblings (one tool per sub-kind — see [`03_RICH_UI.md`](./03_RICH_UI.md) § 4 row for `read_data`)

Per the resolved open question in [`03_RICH_UI.md`](./03_RICH_UI.md) § 10 #2, the single `posthog` MCP server exposes each sub-kind as a first-class inner tool. List grows as new entity types are added; each row below is the minimum contract:

| Inner tool name              | Input                           | Output                    | Renderer |
| ---------------------------- | ------------------------------- | ------------------------- | -------- |
| `read_data_warehouse_schema` | `{ table_name?: string }`       | `content[]` text frames   | Fallback |
| `read_actions`               | `{ id?: int }`                  | `content[]`               | Fallback |
| `read_event_definition`      | `{ event_name: string }`        | `content[]`               | Fallback |
| `read_evaluation`            | `{ id: string }`                | `content[]`               | Fallback |
| `list_data`                  | `{ kind: enum, offset?: int }`  | `content[]` list excerpts | Fallback |
| `search`                     | `{ kind: enum, query: string }` | `content[]` list excerpts | Fallback |

**TODO — enumerate the full sub-kind set** by walking the single `posthog` MCP server's inner-tool registry. The list above is non-exhaustive.

### Write-style siblings (require `permission_request`)

| Inner tool name               | Input                                                | Output                             | Renderer                       |
| ----------------------------- | ---------------------------------------------------- | ---------------------------------- | ------------------------------ |
| `upsert_dashboard`            | `{ action: 'create' \| 'update', dashboard: {...} }` | `rawOutput: { dashboard_id, url }` | `UpsertDashboardAdapter` (new) |
| `upsert_alert`                | `{ action, alert: {...} }`                           | `rawOutput: { alert_id, url }`     | Fallback                       |
| `create_user_interview_topic` | `{ name, questions: [...] }`                         | `rawOutput: { topic_id, url }`     | Fallback                       |

### Specialized read tools

| Inner tool name                | Input                              | Output                                                                                                                              | Renderer                           |
| ------------------------------ | ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| `search_session_recordings`    | `{ query, filters: {...} }`        | `rawOutput: { filters: RecordingUniversalFilters }`                                                                                 | `SearchSessionRecordingsAdapter`   |
| `filter_session_recordings`    | `{ recordings_filters: {...} }`    | `rawOutput: { filters }`                                                                                                            | `FilterSessionRecordingsAdapter`   |
| `summarize_sessions`           | `{ session_ids?, summary_title? }` | Streamed `content[]` text frames carrying `SessionSummarizationUpdate` JSON; final `rawOutput: { session_group_summary_id, title }` | `SummarizeSessionsAdapter`         |
| `search_error_tracking_issues` | `{ search_query, status?, ... }`   | `rawOutput: MaxErrorTrackingSearchResponse`                                                                                         | `SearchErrorTrackingIssuesAdapter` |
| `filter_error_tracking_issues` | `{ filters }`                      | `rawOutput: MaxErrorTrackingSearchResponse`                                                                                         | Same as above                      |
| `experiment_results_summary`   | `{ experiment_id }`                | `content[]` text                                                                                                                    | Fallback                           |
| `analyze_user_interviews`      | `{ topic_id }`                     | `content[]` themes                                                                                                                  | Fallback                           |
| `search_llm_traces`            | `{ query, period? }`               | `content[]` list + `rawOutput.url`                                                                                                  | Fallback (CTA)                     |
| `web_analytics_doctor`         | `{}`                               | `content[]` text                                                                                                                    | Fallback                           |
| `diagnose_proxy`               | `{}`                               | `content[]` text                                                                                                                    | Fallback                           |
| `filter_revenue_analytics`     | `{ filters }`                      | `rawOutput: { url }`                                                                                                                | Fallback (CTA)                     |
| `filter_web_analytics`         | `{ filters }`                      | `rawOutput: { url }`                                                                                                                | Fallback (CTA)                     |

**Dropped from this catalog** (per resolved open questions):

- `fix_hogql_query` — tool dropped; replaced by an in-UI trigger ([`TODO.md`](./TODO.md) "Insight editor → Max 'fix this query' trigger").
- `create_form` — deferred ([`TODO.md`](./TODO.md) "MultiQuestionForm answer channel").

---

## Notebook inner tools

**Note:** "Notebook" is a _grouping category_ for inner tools on the single `posthog` server — not a separate server. All names below are inner tool names invoked through the one `exec` tool.

**Scope:** notebook + message-template CRUD.

| Inner tool name           | Input                    | Output                                                                                                                                                                  | Renderer                                               | Permission |
| ------------------------- | ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ | ---------- |
| `create_notebook`         | `{ title, prompt }`      | `rawOutput: { blocks: DocumentBlock[], title, artifact_id }` (single delivery on completion — streaming deferred per [`TODO.md`](./TODO.md) "Notebook block streaming") | `CreateNotebookAdapter` → `NotebookArtifactAnswer`     | write      |
| `update_notebook`         | `{ notebook_id, patch }` | `rawOutput: { blocks, title, artifact_id }`                                                                                                                             | Same                                                   | write      |
| `get_notebook`            | `{ notebook_id }`        | `rawOutput: { blocks, title }`                                                                                                                                          | Fallback or reuse `NotebookArtifactAnswer` (read-only) | read       |
| `list_notebooks`          | `{}`                     | `content[]` text list                                                                                                                                                   | Fallback                                               | read       |
| `create_message_template` | `{ name, prompt }`       | `rawOutput: { template_id }`                                                                                                                                            | Fallback                                               | write      |

---

## PostHog AI → PostHog Code integration (deferred)

**Status:** Deferred. There is **no separate `posthog-code` MCP server** — PostHog Code is a _consumer_ of the same single-exec `posthog` MCP server (via `x-posthog-mcp-consumer: posthog-code` header), not a producer.

The legacy LangGraph `TaskTool` family (`posthog/ee/hogai/tools/task.py`, `products/tasks/backend/max_tools.py`) routes PostHog AI → PostHog Code by manipulating `products/tasks/` Django models directly. None of these have inner-tool equivalents in `services/mcp/definitions/*.yaml` today. If migrated, they become additional inner tools on the same `posthog` server (e.g. `tasks-create`, `tasks-run`, `tasks-get-run-logs`) and ship behind `has_phai_tasks` via per-inner-tool yaml + `phai-sandbox-tool-{slug}` flags.

Tracked in [`TODO.md`](./TODO.md) "PostHog AI → PostHog Code integration".

Shapes the inner tools would have, once added — for the renderer-adapter table to reference:

| Likely inner tool name    | Input                           | Output                        | Renderer       | Permission |
| ------------------------- | ------------------------------- | ----------------------------- | -------------- | ---------- |
| `tasks-create`            | `{ title, repository, prompt }` | `rawOutput: { task_id, url }` | Fallback (CTA) | write      |
| `tasks-run`               | `{ task_id }`                   | `rawOutput: { run_id, url }`  | Fallback (CTA) | write      |
| `tasks-get-run`           | `{ run_id }`                    | `content[]` status text       | Fallback       | read       |
| `tasks-get-run-logs`      | `{ run_id }`                    | `content[]` logs (truncated)  | Fallback       | read       |
| `tasks-list`              | `{ repository?, status? }`      | `content[]` text list         | Fallback       | read       |
| `tasks-list-runs`         | `{ task_id }`                   | `content[]` text list         | Fallback       | read       |
| `tasks-list-repositories` | `{}`                            | `content[]` text list         | Fallback       | read       |

---

## Claude Code SDK built-ins (no MCP server)

Some tools are provided by the Claude Code SDK directly and don't require a PostHog-side MCP server:

| Tool name       | Notes                                                                                                                                                                                  |
| --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `TodoWrite`     | SDK built-in (per [`04_PROMPTS.md`](./04_PROMPTS.md) § 5.1 — resolved decision). Renderer adapter: `TodoWriteAdapter` → `PlanningAnswer` (per [`03_RICH_UI.md`](./03_RICH_UI.md) § 4). |
| `WebSearch`     | SDK built-in. Bedrock-routed sandboxes must disable it ([`TODO.md`](./TODO.md) "Web search tool placement").                                                                           |
| `EnterPlanMode` | SDK built-in. No renderer — surfaces as a mode badge via `current_mode_update` (per [`03_RICH_UI.md`](./03_RICH_UI.md) § 6).                                                           |

---

## User-installed MCPs

Pass-through. The frontend uses the fallback renderer (`FallbackMcpToolRenderer.tsx`) for any inner tool name not in the registry — see [`03_RICH_UI.md`](./03_RICH_UI.md) § 3.4.

No spec needed per tool — the user's own MCP server is the source of truth.

---

## Authoring this file as tools land

Every PR that enables an inner tool (bundled into the consuming PR per `00_OVERVIEW.md` § 10's parallel-streams note) must add or update the relevant grouping section here with the actual shapes shipped (all enabling inner tools on the single `posthog` server). Renderer-adapter PRs (`UI-A`, `UI-B`) read shapes from here as their input.

When a tool changes shape mid-rollout (input/output evolves), update this file in the same PR. Treat it as the **contract** between MCP and frontend — no out-of-band changes.
