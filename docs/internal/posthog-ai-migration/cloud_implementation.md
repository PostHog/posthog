# Cloud Agents — Frontend Specification

A complete spec for building a new frontend (web, mobile, or otherwise) that talks to the existing PostHog Code "cloud agents" backend. Reverse-engineered from the current Electron desktop client at `apps/code/` plus the in-sandbox agent server at `packages/agent/`.

All file references are absolute paths in this repo, with line numbers, so claims can be verified against source.

---

## 1. Architecture in one breath

The cloud-agent system spans three layers:

1. **PostHog cloud REST API** — `/api/projects/{teamId}/tasks/...`. Source of truth. Hosts tasks, runs, logs, artifacts. Exposes an SSE stream and a JSON-RPC command channel per run.
2. **Desktop main-process `CloudTaskService`** — owns long-lived SSE connections, fans out typed events to the renderer over tRPC. **A web/mobile frontend can skip this entirely** — talk REST + SSE directly.
3. **In-sandbox `agent-server`** — runs alongside the agent process (Claude Code / Codex) inside each cloud sandbox. JWT-authenticated. Bridges the agent's ACP protocol back to PostHog. Persists every notification into the run log via `append_log`.

```
┌───────────────┐    REST + SSE + POST /command/         ┌──────────────────┐    ACP    ┌──────────────┐
│  new client   │ ──────────────────────────────────────▶│ PostHog cloud    │ ◀───────▶ │ agent-server │
│  (web/mobile) │ ◀──────────────────────────────────────│ (relay + DB +    │           │ in sandbox   │
└───────────────┘   task_run_state, log entries,         │ object storage)  │           └──────────────┘
                    permission_request, keepalive        └──────────────────┘
```

The most direct integration target is layer 1. Everything in layer 2 (tRPC `cloudTask.*`) is just a proxy over SSE + REST plus a small subscriber-counting reconnect manager. Layer 3 is reached only via the relay.

---

## 2. Core domain model

### 2.1 `TaskRunStatus`

`/Users/georgiy/Projects/posthog/Twig/apps/code/src/shared/types.ts:57-75`, mirrored in `/Users/georgiy/Projects/posthog/Twig/packages/agent/src/types.ts:78-84`:

```ts
type TaskRunStatus =
  | "not_started"
  | "queued"
  | "in_progress"
  | "completed"
  | "failed"
  | "cancelled";

const TERMINAL_STATUSES = ["completed", "failed", "cancelled"] as const;
function isTerminalStatus(status): boolean { ... }
```

Observed transitions (no enum guards exist client-side — backend is authority):

- `not_started` → `queued` when `POST /tasks/{id}/run/` is accepted.
- `queued` → `in_progress` when the sandbox's agent-server initializes the session (`packages/agent/src/server/agent-server.ts:1031-1038` issues `updateTaskRun({ status: "in_progress" })`).
- `in_progress` → `completed | failed | cancelled` — terminal. Watchers stop after emitting a final `status` event.
- `failed` also set by the agent-server when `signalTaskComplete(stopReason="error")` runs (`agent-server.ts:1766-1803`) with an `error_message`.

There is no explicit `initializing` state. Treat the gap between `queued` and `in_progress` as a loading state.

### 2.2 `TaskRun` (REST representation)

`apps/code/src/shared/types.ts:77-95`:

```ts
interface TaskRun {
  id: string
  task: string // Task UUID
  team: number // PostHog team/project id
  branch: string | null // current git branch (synced by agent each turn)
  runtime_adapter?: 'claude' | 'codex' | null
  model?: string | null
  reasoning_effort?: 'low' | 'medium' | 'high' | 'xhigh' | 'max' | null
  stage?: string | null // free text: 'research' | 'plan' | 'build' | ...
  environment?: 'local' | 'cloud'
  status: TaskRunStatus
  log_url: string // S3 URL where the canonical NDJSON log lives
  error_message: string | null
  output: Record<string, unknown> | null // pr_url, head_branch, commit SHA, …
  state: Record<string, unknown> // see § 2.5 — soft schema
  created_at: string
  updated_at: string
  completed_at: string | null
}
```

`packages/agent/src/types.ts:89-105` adds `artifacts?: TaskRunArtifact[]` — REST payloads also return this.

### 2.3 `Task`

`apps/code/src/shared/types.ts:37-55`:

```ts
interface Task {
  id: string
  task_number: number | null
  slug: string
  title: string
  title_manually_set?: boolean
  description: string
  created_at: string
  updated_at: string
  created_by?: UserBasic | null
  origin_product: string // "user_created" | "error_tracking" | "session_summaries" | ...
  repository?: string | null // "owner/repo"
  github_integration?: number | null
  github_user_integration?: string | null
  json_schema?: Record<string, unknown> | null
  signal_report?: string | null
  internal?: boolean
  latest_run?: TaskRun
}
```

### 2.4 `TaskRunArtifact`

`packages/agent/src/types.ts:59-76`:

```ts
type ArtifactType = 'plan' | 'context' | 'reference' | 'output' | 'artifact' | 'user_attachment'

interface TaskRunArtifact {
  id?: string
  name: string
  type: ArtifactType
  source?: string
  size?: number
  content_type?: string
  storage_path?: string // backend-owned object-storage key
  uploaded_at?: string
}
```

### 2.5 The `state` bag — soft schema between client and agent-server

Not enforced anywhere. Keys are conventions; clients write via `PATCH /runs/{rid}/` with optional `state_remove_keys: string[]` for deletion.

| Key                         | Writer                        | Reader                      | Purpose                                                                                                  |
| --------------------------- | ----------------------------- | --------------------------- | -------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- | ---- | ----------------- | ---- | --------- | ------------- |
| `resume_from_run_id`        | client (`POST /run/`)         | `agent-server.ts:1515-1527` | Resume: load conversation + checkpoint from prior run. Env var `POSTHOG_RESUME_RUN_ID` takes precedence. |
| `slack_notified_pr_url`     | backend                       | `agent-server.ts:849-853`   | Pre-existing PR; agent reuses it instead of creating a new one.                                          |
| `initial_permission_mode`   | client                        | `agent-server.ts:940-945`   | One of `default                                                                                          | acceptEdits                                                                  | plan | bypassPermissions | auto | read-only | full-access`. |
| `initial_prompt_override`   | backend                       | `agent-server.ts:1299-1308` | Substitute prompt instead of `task.description`.                                                         |
| `pending_user_message`      | client (`/run/` or `/start/`) | `agent-server.ts:1310-1334` | First user message for the new run. Cleared by `state_remove_keys` after consumption.                    |
| `pending_user_artifact_ids` | client                        | same                        | UUIDs of artifacts to attach to the initial prompt.                                                      |
| `pending_user_message_ts`   | client                        | (cleared with the above)    | Ordering.                                                                                                |
| `pr_authorship_mode`        | client                        | renderer                    | `"user"` or `"bot"`. Affects PR attribution.                                                             |
| `run_source`                | client                        | renderer + agent-server     | `"manual"                                                                                                | "signal_report"`. Affects cloud system prompt (`agent-server.ts:1572-1578`). |
| `signal_report_id`          | client                        | renderer                    | Cross-link to a signal report row.                                                                       |

The `output` map is a parallel, smaller bag for downstream UIs:

- `output.head_branch` — branch the agent last pushed (synced each `end_turn`, `agent-server.ts:1750-1754`).
- `output.pr_url` — set by `extractCreatedPrUrl` parsing `gh pr create` output (`agent-server.ts:2159-2192`).

### 2.6 Cloud-specific shared types

`apps/code/src/shared/types/cloud.ts:1-3`:

```ts
type PrAuthorshipMode = 'user' | 'bot'
type CloudRunSource = 'manual' | 'signal_report'
```

### 2.7 `SandboxEnvironment`

```ts
type NetworkAccessLevel = 'trusted' | 'full' | 'custom'

interface SandboxEnvironment {
  id: string
  name: string
  network_access_level: NetworkAccessLevel
  allowed_domains: string[]
  include_default_domains: boolean
  repositories: string[]
  has_environment_variables: boolean
  private: boolean
  effective_domains: string[]
  created_by?: UserBasic | null
  created_at: string
  updated_at: string
}

interface SandboxEnvironmentInput {
  name: string
  network_access_level: NetworkAccessLevel
  allowed_domains?: string[]
  include_default_domains?: boolean
  repositories?: string[]
  environment_variables?: Record<string, string>
  private?: boolean
}
```

### 2.8 Live update payload — `CloudTaskUpdatePayload`

`apps/code/src/shared/types.ts:124-188`. This is the shape that the current desktop renderer consumes — the new frontend should keep the same union when parsing SSE:

```ts
interface CloudTaskUpdateBase {
  taskId: string
  runId: string
}

interface CloudTaskLogsUpdate extends CloudTaskUpdateBase {
  kind: 'logs'
  newEntries: StoredLogEntry[]
  totalEntryCount: number
}

interface CloudTaskStatusUpdate extends CloudTaskUpdateBase {
  kind: 'status'
  status?: TaskRunStatus
  stage?: string | null
  output?: Record<string, unknown> | null
  errorMessage?: string | null
  branch?: string | null
}

interface CloudTaskSnapshotUpdate extends CloudTaskUpdateBase {
  kind: 'snapshot'
  newEntries: StoredLogEntry[]
  totalEntryCount: number
  status?: TaskRunStatus
  stage?: string | null
  output?: Record<string, unknown> | null
  errorMessage?: string | null
  branch?: string | null
}

interface CloudTaskErrorUpdate extends CloudTaskUpdateBase {
  kind: 'error'
  errorTitle: string
  errorMessage: string
  retryable: boolean
}

interface CloudPermissionOption {
  kind: string // "allow_once" | "allow_always" | "reject" | "reject_with_feedback" | ...
  optionId: string
  name: string
  _meta?: Record<string, unknown>
}

interface CloudTaskPermissionRequestUpdate extends CloudTaskUpdateBase {
  kind: 'permission_request'
  requestId: string
  toolCall: {
    toolCallId: string
    title: string
    kind: string
    content?: unknown[]
    rawInput?: Record<string, unknown>
    _meta?: Record<string, unknown>
  }
  options: CloudPermissionOption[]
}

type CloudTaskUpdatePayload =
  | CloudTaskLogsUpdate
  | CloudTaskStatusUpdate
  | CloudTaskSnapshotUpdate
  | CloudTaskErrorUpdate
  | CloudTaskPermissionRequestUpdate
```

`StoredLogEntry` (`apps/code/src/shared/types/session-events.ts:71-81`):

```ts
interface StoredLogEntry {
  type: string // typically "notification"
  timestamp?: string
  notification?: {
    id?: number
    method?: string // "session/update", "_posthog/run_started", ...
    params?: unknown
    result?: unknown
    error?: unknown
  }
}
```

Structurally compatible with `StoredNotification` in the agent package (`packages/agent/src/types.ts:11-26`) — the format `agent-server` emits.

---

## 3. Authentication

Two distinct token paths exist in the existing system:

1. **Client → PostHog REST API.** `Authorization: Bearer <token>`. The desktop currently uses OAuth-derived tokens via `AuthService.authenticatedFetch` (auto-refresh on 401). A new web frontend can use either OAuth or a personal API key with project scope.
2. **Sandbox JWT.** Used internally between PostHog's relay and the in-sandbox agent server. Not relevant for a frontend — the public API hides this behind the REST + SSE proxy.

Both `projectId` (numeric team ID) and `cloudRegion` (e.g. `"us"`, `"eu"`, `"dev"`) must be known before opening any subscription. Map region → API host via `getCloudUrlFromRegion(region)` (e.g. `https://us.posthog.com`).

The agent-server uses `Authorization: Bearer <POSTHOG_PERSONAL_API_KEY>` with `User-Agent: posthog/agent.hog.dev; version: <pkg.version>` (`packages/agent/src/posthog-api.ts:72-84`). On 401/403 it calls `refreshApiKey()` once and retries (`posthog-api.ts:99-110`).

---

## 4. REST API surface

Every endpoint lives under `/api/projects/{teamId}/tasks/...`.

### 4.1 Task-level

| Method + path                                                                  | Purpose                                                                                                                                                                                               |
| ------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `POST /api/projects/{teamId}/tasks/`                                           | Create a task. Body: `{ title, description, repository, github_integration?, github_user_integration?, origin_product, signal_report?, signal_report_task_relationship?, json_schema? }`.             |
| `GET  /api/projects/{teamId}/tasks/{taskId}/`                                  | Fetch a single `Task`. Returns `Task` with `latest_run`. (`packages/agent/src/posthog-api.ts:144-147`)                                                                                                |
| `POST /api/projects/{teamId}/tasks/{taskId}/run/`                              | **Kick off a fresh cloud run.** See body in § 4.3. Returns `Task` with `latest_run` populated. (`renderer/api/posthogClient.ts:1073-1098`)                                                            |
| `POST /api/projects/{teamId}/tasks/{taskId}/staged_artifacts/prepare_upload/`  | Two-step S3 upload (step 1) for files attached **before** a run exists. Returns `{ artifacts: [{ id, name, type, content_type, storage_path, upload_url, fields }] }`. (`posthogClient.ts:1100-1131`) |
| `POST /api/projects/{teamId}/tasks/{taskId}/staged_artifacts/finalize_upload/` | Step 2 — tell backend the upload completed; returns persisted artifact records. (`posthogClient.ts:1133-1173`)                                                                                        |

### 4.2 Run-level

| Method + path                                                                          | Purpose                                                                                                                                                                                    |
| -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------- |
| `GET  /api/projects/{teamId}/tasks/{taskId}/runs/`                                     | Paginated list. Returns either `{ results: TaskRun[] }` or a bare array. (`posthogClient.ts:1266-1283`)                                                                                    |
| `GET  /api/projects/{teamId}/tasks/{taskId}/runs/{runId}/`                             | Fetch single `TaskRun`. (`posthog-api.ts:149-154`, `cloud-task/service.ts:1219-1257`)                                                                                                      |
| `POST /api/projects/{teamId}/tasks/{taskId}/runs/`                                     | Create a run **without** starting it (defaults `environment: "local"`, `mode: "background"`). (`posthogClient.ts:1303-1331`)                                                               |
| `POST /api/projects/{teamId}/tasks/{taskId}/runs/{runId}/start/`                       | Start a previously created run. Body `{ pending_user_message, pending_user_artifact_ids }`. (`posthogClient.ts:1333-1359`)                                                                 |
| `POST /api/projects/{teamId}/tasks/{taskId}/runs/{runId}/resume_in_cloud/`             | Spin up a cloud sandbox for an existing run (used by handoff-to-cloud). Returns updated `TaskRun`. (`posthog-api.ts:156-162`, `posthogClient.ts:1248-1264`)                                |
| `PATCH /api/projects/{teamId}/tasks/{taskId}/runs/{runId}/`                            | Update run fields. Body `Partial<{ status, branch, stage, error_message, output, state, environment } & { state_remove_keys: string[] }>`. (`posthog-api.ts:164-177`)                      |
| `PATCH /api/projects/{teamId}/tasks/{taskId}/runs/{runId}/set_output/`                 | Convenience: set just `output`. Body is the output map itself. Used when the agent emits structured output. (`posthog-api.ts:179-191`)                                                     |
| `POST /api/projects/{teamId}/tasks/{taskId}/runs/{runId}/append_log/`                  | Append `StoredNotification[]` entries to the persisted log. Body `{ entries: StoredEntry[] }`. (`posthog-api.ts:193-206`)                                                                  |
| `POST /api/projects/{teamId}/tasks/{taskId}/runs/{runId}/relay_message/`               | Agent relays its assistant response back to Slack/whatever origin. Body `{ text }`. Returns `{ status: string }`. (`posthog-api.ts:208-221`)                                               |
| `POST /api/projects/{teamId}/tasks/{taskId}/runs/{runId}/artifacts/`                   | Inline (base64) artifact upload. Body `{ artifacts: [{ name, type, content, content_type }] }`. Returns `{ artifacts: TaskRunArtifact[] }` (full run manifest). (`posthog-api.ts:223-246`) |
| `POST /api/projects/{teamId}/tasks/{taskId}/runs/{runId}/artifacts/download/`          | Download artifact bytes via backend. Body `{ storage_path }`. Returns raw bytes. (`posthog-api.ts:248-275`)                                                                                |
| `POST /api/projects/{teamId}/tasks/{taskId}/runs/{runId}/artifacts/prepare_upload/`    | Direct-to-storage variant of artifact upload (step 1). (`posthogClient.ts:1175-1205`)                                                                                                      |
| `POST /api/projects/{teamId}/tasks/{taskId}/runs/{runId}/artifacts/finalize_upload/`   | Finalize step for direct-to-storage. (`posthogClient.ts:1207-1245`)                                                                                                                        |
| `GET  /api/projects/{teamId}/tasks/{taskId}/runs/{runId}/logs`                         | Whole-log NDJSON dump from object storage. Newline-delimited `StoredEntry` JSON; `404` = empty. (`posthog-api.ts:277-314`)                                                                 |
| `GET  /api/projects/{teamId}/tasks/{taskId}/runs/{runId}/session_logs/?limit=&offset=` | Paginated log fetch. Body: `StoredLogEntry[]`. Header `X-Has-More: true                                                                                                                    | false`to paginate. Limit cap`5_000` (`SESSION_LOG_PAGE_LIMIT`). (`cloud-task/service.ts:1145-1194`) |
| `GET  /api/projects/{teamId}/tasks/{taskId}/runs/{runId}/stream/?start=latest`         | **SSE live stream** (see § 5). Resumable via `Last-Event-ID` header. (`cloud-task/service.ts:583-691`)                                                                                     |
| `POST /api/projects/{teamId}/tasks/{taskId}/runs/{runId}/command/`                     | **JSON-RPC command to the agent** (see § 6). Body `{ jsonrpc: "2.0", method, params, id }`. Returns JSON-RPC response. (`cloud-task/service.ts:298-374`, `posthogClient.ts:1016-1071`)     |

### 4.3 `POST /tasks/{taskId}/run/` body

Built by `buildCloudRunRequestBody` (`posthogClient.ts:187-254`). Every field optional except `mode`:

```ts
{
  mode: "interactive" | "background",          // default "interactive" for /run/; "background" for /runs/
  branch?: string | null,                       // git branch to base the run on
  runtime_adapter?: "claude" | "codex",
  model?: string,                               // requires runtime_adapter
  reasoning_effort?: "low" | "medium" | "high" | "xhigh" | "max" | "minimal",
                                                // requires model; validated via isSupportedReasoningEffort
  resume_from_run_id?: string,                  // chain new run after a prior run; writes state.resume_from_run_id
  pending_user_message?: string,                // initial prompt; writes state.pending_user_message
  pending_user_artifact_ids?: string[],         // initial attachments; writes state.pending_user_artifact_ids
  sandbox_environment_id?: string,              // pick a SandboxEnvironment
  pr_authorship_mode?: "user" | "bot",          // writes state.pr_authorship_mode
  run_source?: "manual" | "signal_report",      // writes state.run_source
  signal_report_id?: string,                    // writes state.signal_report_id
  initial_permission_mode?:
    "default" | "acceptEdits" | "plan" | "bypassPermissions" | "auto" | "read-only" | "full-access",
                                                // writes state.initial_permission_mode
}
```

`POST /tasks/{taskId}/runs/` (the collection endpoint) takes the same body plus `environment: "local" | "cloud"`, default `"local"`.

### 4.4 Sandbox-environment CRUD

`GET/POST/PATCH/DELETE /api/projects/{teamId}/sandbox_environments[/{id}]/` (`posthogClient.ts:2736-2817`).

---

## 5. SSE stream protocol

### 5.1 Connect

```
GET /api/projects/{teamId}/tasks/{taskId}/runs/{runId}/stream/
Accept: text/event-stream
Authorization: Bearer <token>
Last-Event-ID: <id from last received event, if reconnecting>
```

Optional `?start=latest` requests "only new events from now". On bootstrap, the current desktop client opens with `start=latest` _while concurrently_ paginating `GET /session_logs/` to backfill history (see § 9.2). This eliminates a race window.

### 5.2 Framing

Standard SSE: `event:`, `id:`, `data:`, `\r\n`, comments (`:`), multi-line `data:`. Each event's `data:` is JSON. Parser at `apps/code/src/main/services/cloud-task/sse-parser.ts` and dispatch at `cloud-task/service.ts:693-762`.

### 5.3 Event-data shapes

Five recognized types:

1. **Error frame** — `event: error` with `data: { error: string }`, or any data with `type: "error"`. Triggers reconnect.
2. **Keepalive** — `event: keepalive` or `data.type === "keepalive"`. Silently ignored. Agent-server sends these every `SSE_KEEPALIVE_INTERVAL_MS = 25_000` ms (`agent-server.ts`).
3. **`task_run_state` event** — `{ type: "task_run_state", status, stage, output, error_message, branch, updated_at, completed_at }`. Emit as `kind:"status"`. Terminal status is **deferred** until the stream completes (see § 5.5).
4. **`permission_request` event** — `{ type: "permission_request", requestId, toolCall, options }`. Re-emit as `kind:"permission_request"`.
5. **Anything else** — treated as a `StoredLogEntry`. Batch into `pendingLogEntries`. Current desktop flushes when batch reaches 50 entries or after a 16 ms debounce. Frontends should batch similarly.

### 5.4 `Last-Event-ID`

Track from any event carrying an `id:` field. Send on reconnect via the `Last-Event-ID` header so the relay can replay missed events.

### 5.5 Reconnect / backoff

When the SSE stream ends or errors, refetch the run state via REST:

- If non-terminal: schedule a reconnect with capped exponential backoff. Current desktop uses **5 attempts max**, base 2s, cap 30s (`MAX_SSE_RECONNECT_ATTEMPTS = 5`, `SSE_RECONNECT_BASE_DELAY_MS = 2_000`, `SSE_RECONNECT_MAX_DELAY_MS = 30_000`, `cloud-task/service.ts:21-26`).
- If terminal: emit a final `kind:"status"` with the new state. Stop.

### 5.6 Failure surface — `CloudTaskConnectionError`

Five distinct error shapes (`cloud-task/service.ts:33-204`) constructed by `createStreamStatusError`:

| HTTP  | Title                          | Retryable | Auto-retry |
| ----- | ------------------------------ | --------- | ---------- |
| 401   | "Cloud authentication expired" | yes       | no         |
| 403   | "Cloud access denied"          | yes       | no         |
| 404   | "Cloud run not found"          | **no**    | no         |
| 406   | "Cloud stream unavailable"     | yes       | no         |
| other | "Cloud stream failed"          | yes       | yes        |

`autoRetry === false` should surface a UI "Retry" affordance instead of silently looping.

---

## 6. Command channel — `POST /command/`

`POST /api/projects/{teamId}/tasks/{taskId}/runs/{runId}/command/`. Body is JSON-RPC 2.0:

```json
{
  "jsonrpc": "2.0",
  "method": "<method>",
  "params": { ... },
  "id": "posthog-code-<Date.now()>"
}
```

Response: `{ jsonrpc: "2.0", id, result }` or `{ ..., error: { code, message } }`.

### 6.1 Methods accepted

Methods are accepted both bare and with `posthog/` or `_posthog/` prefixes (`packages/agent/src/server/schemas.ts:105-119`):

- `user_message`
- `cancel`
- `close`
- `permission_response`
- `set_config_option`
- `refresh_session`

### 6.2 `user_message`

`params: { content: string | ContentBlock[], artifacts?: TaskRunArtifact[] }`.

- `content` is either a plain string (deserialized via § 7 cloud-prompt format) or an explicit ACP `ContentBlock[]`.
- `artifacts` are hydrated to ACP `resource_link` blocks (file:// URIs into `<repo>/.posthog/attachments/<runId>/<id>/<name>`).
- Validation (`server/schemas.ts:57-81`): either `content` or `artifacts` must be non-empty; whitespace-only content is rejected.
- Return: `{ stopReason: "end_turn" | "queued" | ..., assistant_message? }`.

### 6.3 `cancel`

`params: {}`. Returns `{ cancelled: true }`. Interrupts the current agent turn.

### 6.4 `close`

`params?: { localGitState?: HandoffLocalGitState }`.

`HandoffLocalGitState` (`packages/agent/src/server/schemas.ts:13-19`):

```ts
{
  head: string | null
  branch: string | null
  upstreamHead: string | null
  upstreamRemote: string | null
  upstreamMergeRef: string | null
}
```

Cleans up the session inside the sandbox. Returns `{ closed: true }`.

### 6.5 `permission_response`

`params: { requestId, optionId, customInput?, answers? }`. Validation: `requestId` + `optionId` required; `customInput?: string`; `answers?: Record<string, string>`.

Returns `{ resolved: true }` or throws `"No pending permission request found for id: <id>"`.

To cancel: send `optionId: "reject_with_feedback"`, `customInput: "User cancelled the permission request."` (matches desktop's `respondToPermission`).

### 6.6 `set_config_option`

`params: { configId: string, value: string }`. Returns `{ configOptions: result.configOptions }` (agent's current config snapshot — e.g. mode, model, reasoning effort).

### 6.7 `refresh_session`

`params: { mcpServers: RemoteMcpServer[] }`. Reinitializes the agent session with new MCP servers without losing conversation history.

### 6.8 Error envelope

Network non-2xx: parse JSON body for `error.message` / `error`, falling back to raw text. Inner `result.error` collapses to `{ success: false, error }` in the desktop's wrapper.

---

## 7. Cloud-prompt wire format

Why it exists: `POST /command/` carries arbitrary `params` JSON, but agents historically accept prompts as plain strings. Multi-block (text + attachments) prompts must round-trip via a JSON wrapper.

`packages/shared/src/cloud-prompt.ts:8-49`:

```ts
const CLOUD_PROMPT_PREFIX = '__twig_cloud_prompt_v1__:'

function serializeCloudPrompt(blocks: ContentBlock[]): string {
  if (blocks.length === 1 && blocks[0].type === 'text') {
    return blocks[0].text.trim() // plain string for single text block
  }
  return `${CLOUD_PROMPT_PREFIX}${JSON.stringify({ blocks })}`
}

function deserializeCloudPrompt(value: string): ContentBlock[] {
  const trimmed = value.trim()
  if (!trimmed) return []
  if (!trimmed.startsWith(CLOUD_PROMPT_PREFIX)) {
    return [{ type: 'text', text: trimmed }]
  }
  try {
    const parsed = JSON.parse(trimmed.slice(CLOUD_PROMPT_PREFIX.length))
    if (Array.isArray(parsed.blocks) && parsed.blocks.length > 0) return parsed.blocks
  } catch {}
  return [{ type: 'text', text: trimmed }] // graceful fallback
}
```

Invariants (tested in `packages/shared/src/cloud-prompt.test.ts`):

- Plain string input → single `text` block.
- Single-text-block content serializes to a trimmed plain string (no prefix).
- Multi-block content serializes to `__twig_cloud_prompt_v1__:` + `JSON.stringify({ blocks })`.
- Empty/whitespace → `[]`.
- Malformed JSON after prefix → falls back to one text block containing the raw payload.

Agent-server normalizes via `normalizeCloudPromptContent` (`packages/agent/src/server/cloud-prompt.ts:6-13`) — accepts either the wire string or pre-deserialized `ContentBlock[]`.

---

## 8. Artifacts / attachments

### 8.1 Two upload modes

**Inline (small):** `POST /tasks/{tid}/runs/{rid}/artifacts/` with base64. Limited by request size.

**Direct-to-storage (preferred for files):**

1. `POST /tasks/{tid}/runs/{rid}/artifacts/prepare_upload/` → `{ artifacts: [{ id, name, type, content_type, storage_path, upload_url, fields }] }`.
2. Build `FormData` from `presigned_post.fields`, append file as `file`, POST to `presigned_post.url`. Expect 2xx.
3. `POST /tasks/{tid}/runs/{rid}/artifacts/finalize_upload/` with the IDs from step 1.

For attachments staged **before** a run exists (e.g. during resume): use `staged_artifacts/{prepare,finalize}_upload/` on the task instead.

### 8.2 Client-side limits

Enforced in `apps/code/src/renderer/features/sessions/utils/cloudArtifacts.ts:19-20` and `features/editor/utils/cloud-prompt.ts:68-69`:

- 30 MB per attachment
- 10 MB for PDFs
- 5 MB for **embedded** images inside a cloud prompt (vs an artifact upload)
- 100 000 chars for an embedded text attachment

### 8.3 Embedded vs uploaded — content type allowlist

Cloud prompts support embedding short text & images directly (`cloud-prompt.ts:13-66`):

- **Text extensions:** `c, cc, cfg, conf, cpp, cs, css, csv, env, gitignore, go, h, hpp, html, ini, java, js, json, jsx, log, md, mjs, py, rb, rs, scss, sh, sql, svg, toml, ts, tsx, txt, xml, yaml, yml, zsh`
- **Text filenames:** `.env, .gitignore, Dockerfile, LICENSE, Makefile, README, README.md`
- **Embedded images:** `png, jpg, jpeg, gif, webp` (anything else throws "Cloud image attachments currently support PNG, JPG, GIF, and WebP")
- Embedded text truncated at 100 000 chars with a banner.

### 8.4 Upload request shapes

```ts
interface TaskArtifactUploadRequest {
  name: string
  type: 'user_attachment'
  size: number
  content_type?: string
  source?: string // "posthog_code" for desktop
}

interface DirectUploadPresignedPost {
  url: string
  fields: Record<string, string>
}

interface PreparedTaskArtifactUpload extends TaskArtifactUploadRequest {
  id: string
  storage_path: string
  expires_in: number
  presigned_post: DirectUploadPresignedPost
}

interface FinalizedTaskArtifactUpload {
  id: string
  name: string
  type: string
  source?: string
  size?: number
  content_type?: string
  storage_path: string
  uploaded_at?: string
}
```

---

## 9. Bootstrapping a run (the merge of REST + SSE)

This is the single trickiest part of the implementation. The agent-server has already published events to the SSE relay before the client connects; the client needs to backfill missed history without double-counting live events.

Reference: `apps/code/src/main/services/cloud-task/service.ts:440-556`.

### 9.1 Initial REST fetch

`GET /runs/{runId}/`. If it fails:

- 401/403/404 → emit non-retryable `kind:"error"` and stop (`shouldFailWatcherForFetchStatus`, `service.ts:207-209`).
- Other → schedule retry.

Apply returned `status / stage / output / error_message / branch` to local state.

### 9.2 If terminal at boot

Fetch the entire log via `session_logs/` pagination (`limit=5000`, until `X-Has-More: false`). Emit **one** `kind:"snapshot"` with everything. The status/stage/output/errorMessage/branch all go into the snapshot. Do **not** open SSE.

### 9.3 If non-terminal at boot

1. Open SSE with `start=latest` (server emits only events from now onward).
2. Concurrently paginate `GET /session_logs/`.
3. Live entries that arrive during the fetch go into `bufferedLogBatches` — they're held back.
4. Once history is loaded, emit **one** `kind:"snapshot"` with the historical entries.
5. `drainBufferedLogBatches()` content-dedupes (by serialized JSON) the buffered live entries against the just-emitted history. Non-duplicates emit as `kind:"logs"`.
6. Verify status once more via REST (`verifyPostBootstrapStatus()`, `service.ts:558-581`) in case it changed during bootstrap.

### 9.4 Why deduping must be by JSON content

The SSE event IDs are Redis stream IDs that don't exist in the S3-backed historical log. You can't reconcile by ID. Use serialized JSON equality.

---

## 10. The agent-server (in-sandbox HTTP service)

Not directly hit by a frontend, but understanding what it emits explains every event the SSE stream carries.

`packages/agent/src/server/agent-server.ts` (~2,400 lines). Started by cloud infra via `bin.ts`.

### 10.1 Boot CLI flags (`bin.ts:73-180`)

- `--port` (default `3001`)
- `--mode` `"interactive" | "background"` (default `"interactive"`)
- `--repositoryPath` — workspace root
- `--taskId`, `--runId` (required)
- `--mcpServers` — JSON array of `{ type: "http"|"sse", name, url, headers: [{name, value}] }`
- `--createPr` — boolean
- `--baseBranch` — base branch for PRs
- `--claudeCodeConfig` — JSON, `claudeCodeConfigSchema` (`server/schemas.ts:32-46`)
- `--allowedDomains` — comma-separated for `WebFetch`/`WebSearch`

### 10.2 Env vars (`bin.ts:8-35`)

- `JWT_PUBLIC_KEY` (RS256 PEM) — validates incoming JWTs
- `POSTHOG_API_URL`, `POSTHOG_PERSONAL_API_KEY`, `POSTHOG_PROJECT_ID` (numeric string)
- `POSTHOG_CODE_RUNTIME_ADAPTER` `"claude" | "codex"`
- `POSTHOG_CODE_MODEL`
- `POSTHOG_CODE_REASONING_EFFORT` `"low" | "medium" | "high" | "xhigh" | "max"`
- `POSTHOG_RESUME_RUN_ID`
- `POSTHOG_CODE_INTERACTION_ORIGIN` / `CODE_INTERACTION_ORIGIN` / `TWIG_INTERACTION_ORIGIN` — `"slack" | "signal_report" | ...` — affects publish/relay behavior
- `LLM_GATEWAY_URL`

### 10.3 HTTP endpoints (sandbox-internal)

- `GET /health` — `{ status: "ok", hasSession: boolean }`. No auth.
- `GET /events` — JWT-authenticated SSE. First event: `{ "type": "connected", "run_id": <run_id> }`. Subsequent frames are `{ type: "notification", timestamp, notification: <JSON-RPC notification> }` and `{ type: "permission_request", requestId, options, toolCall }`.
- `POST /command` — JWT-authenticated JSON-RPC. Methods dispatched through `executeCommand` (§ 6). 400 if no active session matches the JWT's `run_id`.

### 10.4 JWT (`packages/agent/src/server/jwt.ts`)

```ts
const SANDBOX_CONNECTION_AUDIENCE = 'posthog:sandbox_connection'

const userDataSchema = z.object({
  run_id: z.string(),
  task_id: z.string(),
  team_id: z.number(),
  user_id: z.number(),
  distinct_id: z.string(),
  mode: z.enum(['interactive', 'background']).optional().default('interactive'),
})
```

RS256, audience-validated. Mismatched `run_id` → 400.

### 10.5 Session initialization (`agent-server.ts:809-1041`)

1. Cleanup prior session.
2. Fetch `Task` and `TaskRun` in parallel.
3. `configureEnvironment` writes env vars for the agent process (POSTHOG/ANTHROPIC/OPENAI keys, `LLM_GATEWAY_URL`).
4. If `taskRun.state.slack_notified_pr_url` present, store as `detectedPrUrl`.
5. Build system prompt via `buildSessionSystemPrompt` — large contextual prompt (`agent-server.ts:1529-1726`) covering:
   - "Push to existing PR" if `detectedPrUrl` + `shouldAutoCreatePr === true`
   - "No Repository Mode" if no `repositoryPath` configured
   - Default: create `posthog-code/*` branch, draft PR, include `Closes #N`, `Generated-By: PostHog Code` and `Task-Id: <id>` trailers
6. `shouldAutoPublishCloudChanges()` returns true only for `interaction_origin === "slack" | "signal_report"` AND `config.createPr !== false`.
7. Construct `PostHogAPIClient` and `SessionLogWriter`.
8. Construct ACP `AcpConnection` (Claude or Codex adapter).
9. Tap the ACP streams (`createTappedReadableStream`/`createTappedWritableStream`, `agent-server.ts:90-188`). Every NDJSON message in either direction triggers `broadcastEvent({ type: "notification", timestamp, notification: <msg> })` and appends to the log.
10. `clientConnection.initialize` over the tapped stream.
11. `clientConnection.newSession({ cwd, mcpServers, _meta: { sessionId, taskRunId, systemPrompt, model?, allowedDomains, jsonSchema, permissionMode, claudeCode } })`. `permissionMode` defaults: `"bypassPermissions"` for Claude, `"auto"` for Codex; overridable via `state.initial_permission_mode`.
12. Emit `_posthog/run_started` notification with `{ sessionId, runId, taskId, agentVersion }`.
13. `updateTaskRun({ status: "in_progress" })`.
14. Send the initial task message (§ 10.6).

### 10.6 Initial task message (`agent-server.ts:1077-1297`)

Resolution order:

1. If `resume_from_run_id` set: load conversation history via `resumeFromLog`, apply git checkpoint from prior run's log via `HandoffCheckpointTracker.applyFromHandoff`, then send a `[system context, conversation history, user message?]` prompt.
2. Else read `state.pending_user_message` + `state.pending_user_artifact_ids`. Hydrate artifacts to `resource_link` blocks by downloading them and writing to `<repo>/.posthog/attachments/<runId>/<artifact_id>/<name>`.
3. Else `state.initial_prompt_override`.
4. Else `task.description`.
5. Else skip.

After: `clientConnection.prompt({ sessionId, prompt })`. On `stopReason === "end_turn"`:

- Refresh git branch and PATCH `output.head_branch`
- `POST /relay_message/` with the full assistant turn text

Broadcast `_posthog/turn_complete` with `{ sessionId, stopReason }`. Clear `pending_user_*` keys via `PATCH state_remove_keys: [...]`.

### 10.7 Permission relay (`agent-server.ts:1886-2022`, `:2357-2397`)

The cloud agent intercepts ACP `requestPermission` calls:

1. If `interactionOrigin === "slack"` and tool kind is `"question"`: relay question to Slack via `POST /relay_message/`, return `outcome: "cancelled"` with a `_meta.message` telling agent to wait.
2. **Plan approvals** (`toolCall.kind === "switch_mode"`) are **always** relayed to desktop. They buffer in `pendingEvents` until a client reconnects.
3. Questions + default/auto/read-only permission requests relay only if `hasDesktopConnected === true` (SSE client has ever connected).
4. If `createPr === false` and the agent tries `Bash` containing `git push` or `gh pr (create|edit|ready|merge)` → auto-`cancelled` with `_meta.message`.
5. Otherwise auto-allow.

Relay protocol: server broadcasts `permission_request`, awaits `pendingPermissions.set(requestId, { resolve })`. Desktop replies via `permission_response` command. If connection dies, broadcast buffers and replays on reconnect. **No timeout** — only `cleanupSession` force-rejects with `{ outcome: { outcome: "selected", optionId: "reject" }, _meta: { customInput: "Session is shutting down." } }`.

### 10.8 Lifecycle notifications (the names you'll see on the wire)

`packages/agent/src/acp-extensions.ts:15-72`:

```ts
POSTHOG_NOTIFICATIONS = {
  BRANCH_CREATED: '_posthog/branch_created',
  RUN_STARTED: '_posthog/run_started',
  TASK_COMPLETE: '_posthog/task_complete',
  TURN_COMPLETE: '_posthog/turn_complete',
  ERROR: '_posthog/error',
  CONSOLE: '_posthog/console',
  SDK_SESSION: '_posthog/sdk_session',
  GIT_CHECKPOINT: '_posthog/git_checkpoint',
  MODE_CHANGE: '_posthog/mode_change',
  SESSION_RESUME: '_posthog/session/resume',
  USER_MESSAGE: '_posthog/user_message',
  CANCEL: '_posthog/cancel',
  CLOSE: '_posthog/close',
  STATUS: '_posthog/status',
  PROGRESS: '_posthog/progress',
  TASK_NOTIFICATION: '_posthog/task_notification',
  COMPACT_BOUNDARY: '_posthog/compact_boundary',
  USAGE_UPDATE: '_posthog/usage_update',
  PERMISSION_RESPONSE: '_posthog/permission_response',
}

POSTHOG_METHODS = {
  REFRESH_SESSION: '_posthog/refresh_session',
}
```

Notification names use double-underscore-prefix tolerance: `_posthog/X` and `__posthog/X` resolve to the same handler.

### 10.9 Standard ACP notifications you'll see

`session/update` events (`agent-server.ts:1974-2019`) with these `sessionUpdate` kinds:

- `agent_message_chunk` — coalesced by the log writer into `agent_message`
- `agent_message`
- `current_mode_update` — `currentModeId` is one of `PermissionMode`; agent tracks this to gate future permission relays
- `tool_call`
- `tool_call_update` — when `_meta.claudeCode.toolName ∈ {Write, Edit, MultiEdit, Delete, Move}`, a `_posthog/git_checkpoint` is captured

### 10.10 Persistence — `SessionLogWriter` (`packages/agent/src/session-log-writer.ts`)

For every tapped ACP message:

1. Coalesces consecutive `agent_message_chunk` into one `agent_message` (`session-log-writer.ts:112-160`, `:275-306`).
2. Optionally writes to local NDJSON cache.
3. Buffers and debounces `POST /append_log/` (`FLUSH_DEBOUNCE_MS = 500`, max `FLUSH_MAX_INTERVAL_MS = 5_000`). Retries up to `MAX_FLUSH_RETRIES = 10` with capped exponential backoff (`MAX_RETRY_DELAY_MS = 30_000`).

Implication: **every notification on the SSE stream also ends up in the persisted log.** Bootstrapping = paginating the persisted log + reconciling with live SSE.

---

## 11. Handoff between local and cloud

The desktop supports two-way handoff. A new web/mobile frontend may not need this, but it's part of the data model.

### 11.1 Handoff to cloud (saga)

`apps/code/src/main/services/handoff/handoff-to-cloud-saga.ts`. Steps:

1. `capture_git_checkpoint` — writes a git pack + index, uploads both as run artifacts.
2. `persist_checkpoint_to_log` — emits `_posthog/git_checkpoint` log entry via `POST /append_log/`.
3. `start_cloud_run` — `POST /runs/{rid}/resume_in_cloud/`. Backend reads the latest checkpoint from the log and provisions a sandbox.
4. `stop_local_agent` — cancel local agent process.
5. `update_workspace` — flip workspace `mode` from `"local"` to `"cloud"`.

After success: stash remaining local changes (`"posthog-code: handoff backup (<branch>)"`), reset to default branch, delete local log cache.

Failure code `"github_authorization_required"` triggers a UI flow asking the user to reconnect GitHub.

### 11.2 What the cloud already has

When `resume_in_cloud/` is called, the cloud has:

- The most-recent `_posthog/git_checkpoint` notification in the log (with `artifactPath`/`indexArtifactPath` pointing at the pack/index)
- The full conversation history in the log (consumed by `resumeFromLog`)
- `state.resume_from_run_id` if the client chose to start a fresh run instead

Provisioning the sandbox (pulling source, applying the pack, starting the agent, generating the JWT, pointing SSE relay) is opaque to this codebase.

---

## 12. tRPC layer (desktop only — reference for behavior)

The desktop renderer talks to the main process via tRPC. A web/mobile client should skip this and use REST + SSE directly, but the procedure shapes document the contract the renderer relies on.

`apps/code/src/main/trpc/routers/cloud-task.ts`:

```ts
const cloudTaskRouter = router({
  watch:       publicProcedure.input(watchInput).mutation(...),         // start the SSE watcher
  unwatch:     publicProcedure.input(unwatchInput).mutation(...),       // teardown
  retry:       publicProcedure.input(retryInput).mutation(...),         // force reconnect
  sendCommand: publicProcedure.input(sendCommandInput).output(sendCommandOutput).mutation(...),
  onUpdate:    publicProcedure.input(onUpdateInput).subscription(...),  // AsyncIterable<CloudTaskUpdatePayload>
});
```

Inputs (`apps/code/src/main/services/cloud-task/schemas.ts:24-72`):

```ts
const watchInput = z.object({ taskId, runId, apiHost, teamId: z.number() })
const unwatchInput = z.object({ taskId, runId })
const retryInput = z.object({ taskId, runId })
const onUpdateInput = z.object({ taskId, runId })

const sendCommandInput = z.object({
  taskId,
  runId,
  apiHost,
  teamId: z.number(),
  method: z.enum(['user_message', 'cancel', 'close', 'permission_response', 'set_config_option']),
  params: z.record(z.string(), z.unknown()).optional(),
})

const sendCommandOutput = z.object({
  success: z.boolean(),
  result: z.unknown().optional(),
  error: z.string().optional(),
})
```

### 12.1 Procedure semantics

- **`watch`** — reference-counts subscribers per `(taskId, runId)`. First caller starts the watcher; subsequent callers increment `subscriberCount` and trigger a re-emission of the latest snapshot.
- **`unwatch`** — decrements; on zero, aborts SSE and tears down.
- **`retry`** — clears reconnect timers / pending batches / counters; restarts bootstrap or reconnects SSE.
- **`sendCommand`** — proxies a `POST /command/` call. Validates network status and JSON-RPC error envelope.
- **`onUpdate`** — `AsyncIterable<CloudTaskUpdatePayload>`. Filters the global emitter to events matching the subscriber's `taskId`/`runId`. `finally` block calls `unwatch` to decrement ref-count.

### 12.2 `WatcherState` (per `(taskId, runId)`)

`cloud-task/service.ts:73-99` — the state a new frontend needs to reproduce in some form:

```ts
interface WatcherState {
  taskId
  runId
  apiHost
  teamId
  subscriberCount: number
  sseAbortController: AbortController | null
  reconnectTimeoutId
  batchFlushTimeoutId
  pendingLogEntries: StoredLogEntry[]
  totalEntryCount: number
  reconnectAttempts: number
  lastEventId: string | null
  lastStatus: TaskRunStatus | null
  lastStage: string | null
  lastOutput: Record<string, unknown> | null
  lastErrorMessage: string | null
  lastBranch: string | null
  lastStatusUpdatedAt: string | null
  isBootstrapping: boolean
  hasEmittedSnapshot: boolean
  bufferedLogBatches: StoredLogEntry[][]
  emittedLogEntries: StoredLogEntry[]
  failed: boolean
  needsPostBootstrapReconnect: boolean
  needsStopAfterBootstrap: boolean
}
```

---

## 13. UI / UX patterns from the existing renderer

The existing renderer has the following user-facing patterns. Re-implement (or skip) as the new frontend requires.

### 13.1 "Is this task a cloud task?"

A task is cloud if **either**:

- `workspace.mode === "cloud"` (local workspace store), OR
- `task.latest_run.environment === "cloud"` (from API)

```ts
const isCloud = workspace?.mode === 'cloud' || task.latest_run?.environment === 'cloud'
```

(`renderer/features/workspace/hooks/useIsCloudTask.ts:3-6`, `renderer/features/task-detail/components/TaskDetail.tsx:172-173`)

### 13.2 Creating a cloud task — `TaskInput`

`renderer/features/task-detail/components/TaskInput.tsx:67-859`. Layout (top → bottom):

1. `WorkspaceModeSelect` dropdown (Local / Worktree / Cloud-with-environment).
2. `EnvironmentSelector` (worktree only — not used for cloud).
3. Repo picker — `GitHubRepoPicker` in cloud mode, `FolderPicker` in local.
4. `BranchSelector` (cloud variant — see § 13.4).
5. Dev region badge if `cloudRegion === "dev"`.
6. `PromptInput` with model / reasoning selectors.
7. Report-association strip (when arriving from inbox).
8. `CloudGithubMissingNotice` if cloud mode + no GitHub user integration.

Mode-selection guard (`TaskInput.tsx:191-211`): if user lands in cloud mode but loses access, collapse to the last-used local mode.

Submit gate (`useTaskCreation.ts:198-202`): authenticated + online + has repo (cloud) or directory (local) + editor not empty + not creating.

### 13.3 `WorkspaceModeSelect`

`renderer/features/task-detail/components/WorkspaceModeSelect.tsx:31-238`. Feature flag: `twig-cloud-mode-toggle` (always on in dev).

Cloud section content:

- "Default" entry → "Full network access"
- One entry per `SandboxEnvironment`. Description shows `network_access_level` summary: `Full network access` / `Trusted sources only` / `{n} allowed domains`.
- Top-right "+" opens settings → `cloud-environments` with `initialAction: "create"`.

Trigger label: `"Cloud · {envName}"` or `"Cloud"`.

### 13.4 Branch selector — cloud variant

`renderer/features/git-interaction/components/BranchSelector.tsx:41-71`. Cloud props:

```ts
workspaceMode?: "worktree" | "local" | "cloud";
cloudBranches?: string[];
cloudBranchesHasMore?: boolean;
cloudBranchesLoading?: boolean;
cloudBranchesFetchingMore?: boolean;
cloudSearchQuery?: string;
onCloudPickerOpen?: () => void;
onCloudPickerClose?: () => void;
onCloudSearchChange?: (value: string) => void;
onCloudLoadMore?: () => void;
onCloudBranchCommit?: () => void;
onRefresh?: () => void;
isRefreshing?: boolean;
```

In cloud mode: never runs git checkout (selection-only). Server-side search via debounced `cloudSearchQuery`. Combobox sets `filter={null}` to disable local fuzzy filter. Default branch auto-selected once.

### 13.5 GitHub-missing notice

`renderer/features/task-detail/components/CloudGithubMissingNotice.tsx:10-57`. Rendered when `workspaceMode === "cloud" && !hasGithubIntegration`. Amber Radix `Callout` with copy: "Connecting your personal GitHub is required to run cloud tasks." `Connect GitHub` button calls `useGithubConnect().connect()`.

### 13.6 Task creation saga

`renderer/sagas/task/task-creation.ts:75-435`. Input:

```ts
interface TaskCreationInput {
  taskId?: string
  content?: string
  taskDescription?: string
  filePaths?: string[]
  repoPath?: string
  repository?: string | null
  workspaceMode?: WorkspaceMode
  branch?: string | null
  githubIntegrationId?: number
  githubUserIntegrationId?: string
  executionMode?: ExecutionMode
  adapter?: 'claude' | 'codex'
  model?: string
  reasoningLevel?: string
  environmentId?: string
  sandboxEnvironmentId?: string
  cloudPrAuthorshipMode?: PrAuthorshipMode
  cloudRunSource?: CloudRunSource
  signalReportId?: string
}
```

Cloud steps (`task-creation.ts:169-288`):

1. `cloud_workspace_creation` — register in-memory workspace `mode: "cloud"`, empty paths. Rollback deletes.
2. `cloud_run` — `createTaskRun({ environment: "cloud", mode: "interactive", branch, adapter, model, reasoningLevel, sandboxEnvironmentId, prAuthorshipMode, runSource, signalReportId, initialPermissionMode })`. If attachments: `getCloudPromptTransport(content, filePaths)` + `uploadRunAttachments(...)` + `startTaskRun(taskId, runId, { pendingUserMessage, pendingUserArtifactIds })`. Rollback for `cloud_run` is a no-op.
3. **No** ACP session connection — the watcher takes over on navigation.

Failure step → toast (`useTaskCreation.ts:159-169`):

```ts
{
  repo_detection: "Failed to detect repository",
  task_creation: "Failed to create task",
  workspace_creation: "Failed to create workspace",
  cloud_prompt_preparation: "Failed to prepare cloud attachments",
  cloud_run: "Failed to start cloud execution",
  agent_session: "Failed to start agent session",
}
```

### 13.7 Watching a run — extra `AgentSession` fields

`renderer/features/sessions/stores/sessionStore.ts:43-113`:

```ts
isCloud?: boolean;
cloudStatus?: TaskRunStatus;
cloudStage?: string | null;
cloudOutput?: Record<string,unknown>;
cloudErrorMessage?: string | null;
initialPrompt?: ContentBlock[];        // for retry of failed-before-start runs
cloudBranch?: string | null;
handoffInProgress?: boolean;
skipPolledPromptCount?: number;
agentVersion?: string;
agentIdleForRunId?: string;            // tracks turn_complete for queue dispatching
```

Setter `sessionStoreSetters.updateCloudStatus(taskRunId, { status?, stage?, output?, errorMessage?, branch? })` is called for every `status` / `snapshot` payload.

### 13.8 Watcher trigger conditions

`useSessionConnection.ts:68-111`:

```ts
if (!isCloud || !task.latest_run?.id) return
if (cloudAuthState.status !== 'authenticated') return
if (!cloudAuthState.bootstrapComplete) return
if (!cloudAuthState.projectId || !cloudAuthState.cloudRegion) return
```

On window focus, `retryUnhealthyCloudSessions` (`service.ts:3191-3206`) iterates every cloud session with `status === "error"` and auto-retries.

### 13.9 `CloudInitializingView` — early-life loading screen

`renderer/features/sessions/components/CloudInitializingView.tsx:7-81`. Shown when `isInitializing && isCloud`:

- 2-second delay before any content — just a centered spinner.
- After 2s: 160px floating zen hedgehog image with `zen-float` animation, plus copy:
  - `cloudStatus === "queued"` → "Waiting in the queue…" / "Reserving a cloud sandbox — this can take a few seconds."
  - `cloudStatus === "in_progress"` → "Starting the sandbox…" / "Connecting to your cloud runner."
  - Otherwise → "Getting things ready…" / "Connecting to your cloud runner."

`isInitializing` for cloud: `!hasError && (!session || (events.length === 0 && isCloudRunNotTerminal))`. `isCloudRunNotTerminal = isCloud && (!cloudStatus || cloudStatus === "queued" || cloudStatus === "in_progress")`.

### 13.10 `SessionView` — conversation pane (cloud branches)

`renderer/features/sessions/components/SessionView.tsx:47-699`. Cloud props:

```ts
isRunning, isPromptPending, promptStartedAt,
onBeforeSubmit, onSendPrompt, onBashCommand,
onCancelPrompt, repoPath, cloudBranch,
isSuspended, onRestoreWorktree, isRestoring,
hasError, errorTitle, errorMessage,
onRetry, onNewSession,
isInitializing,
isCloud, cloudStatus,
slackThreadUrl, compact, isActiveSession, hideInput,
```

Cloud-specific behavior:

- `enableBashMode={!isCloudRun}` — `!`/`bash` mode is local-only
- `onBashCommand={isCloud ? undefined : ...}`
- `onNewSession={isCloud ? undefined : ...}`
- Skip auto-revert of `bypassPermissions` mode (sandbox makes it safe)
- Error overlay shows `errorTitle` (red bold) + `errorMessage` + Retry button + optional New Session

### 13.11 Sending a follow-up — `sendCloudPrompt`

`renderer/features/sessions/service/service.ts:1671-1837`. High-level state machine:

1. `getCloudPromptTransport(prompt)` → `{ filePaths, messageText, promptText }`.
2. If `isTerminalStatus(cloudStatus)`:
   - If `failed && session.status !== "connected"` and `cloudErrorMessage` set: throw to surface boot failure
   - Otherwise call `resumeCloudRun(session, prompt)` (§ 13.13)
3. If `cloudStatus !== "in_progress"`: enqueue and return `{ stopReason: "queued" }`.
4. If sandbox booted but no `run_started`: also enqueue. If session is `"disconnected" | "error"`, fire `retryCloudTaskWatch`.
5. If `isPromptPending`: enqueue.
6. Else:
   - Bring watcher up if not running
   - Upload attachments via `uploadRunAttachments` (returns `artifactIds`)
   - Optimistically push a `user_message` item (`pinToTop: false`) and set `isPromptPending = true`
   - `cloudTask.sendCommand({ method: "user_message", params: { content?, artifact_ids? } })`
   - On `result.queued === true`: server-side queue → `stopReason: "queued"`

Queue draining: `scheduleCloudQueueFlush(taskId, reason)` runs after every `_posthog/turn_complete`. `sendQueuedCloudMessages` (line 1851-1892) acquires a per-task re-entrance guard, dequeues, merges via `combineQueuedCloudPrompts`, sends as one prompt with `skipQueueGuard: true`, prepends back on failure.

### 13.12 Cancel — `cancelCloudPrompt`

`service.ts:2041-2087`. Skips for terminal status. `cloudTask.sendCommand({ method: "cancel" })`. Tracks `task_run_cancelled` analytics.

### 13.13 Resume a terminal run — `resumeCloudRun`

`service.ts:1894-2039`. Pre-condition: prior run is terminal. Steps:

1. Upload attachments via `uploadTaskStagedAttachments` (task-level, since no new run exists yet).
2. Fetch previous run. Pick branch in order: `previousOutput.head_branch`, `previousRun.branch`, `previousState.pr_base_branch`, `session.cloudBranch`.
3. Read `pr_authorship_mode` from prior `state` (fallback: `bot` for signal_report, else `user`).
4. Read prior `model` / `adapter` / `reasoning_effort` from session config options (fallback to previous run).
5. `runTaskInCloud(taskId, previousBaseBranch, { resumeFromRunId, pendingUserMessage, pendingUserArtifactIds, prAuthorshipMode, runSource, signalReportId, adapter, model, reasoningLevel })`.
6. Replace session in store with new run id, preserve prior events, add an optimistic user-prompt event.
7. `watchCloudTask(...)` on new run id.
8. Return `{ stopReason: "queued" }`.

### 13.14 Permission responses

`service.ts:1387-1421` handles `permission_request` updates. The renderer stores `update.requestId` keyed by `toolCall.toolCallId` in `cloudPermissionRequestIds`. When user answers via `PermissionSelector`, `respondToPermission` (line 2148-2204) dispatches:

```ts
cloudTask.sendCommand({
  method: 'permission_response',
  params: { requestId, optionId, customInput, answers },
})
```

Cancellation: `optionId: "reject_with_feedback"`, `customInput: "User cancelled the permission request."`.

### 13.15 Mid-run config option changes

`setSessionConfigOption` (`service.ts:2260-2339`) — shared with local. Cloud variant: `sendCloudCommand("set_config_option", { configId, value })`. Optimistic, rolled back on error. Cloud-default options for `mode` (codex/claude variants) come from `buildCloudDefaultConfigOptions` (line 153-181) so the mode-toggle UI works pre-handshake. Live `config_option_update` events override.

### 13.16 PR URL resolution

`renderer/features/git-interaction/hooks/useCloudPrUrl.ts:1-29`:

```ts
function resolveCloudPrUrl(task: Task | undefined, session: AgentSession | undefined): string | null {
  const taskPrUrl = task?.latest_run?.output?.pr_url
  const sessionPrUrl = session?.cloudOutput?.pr_url
  if (typeof taskPrUrl === 'string' && taskPrUrl) return taskPrUrl
  if (typeof sessionPrUrl === 'string' && sessionPrUrl) return sessionPrUrl
  return null
}
```

Both task-level (persisted) and session-level (SSE-pushed) are consulted because a freshly-pushed PR may not have been written to the DB yet.

### 13.17 Reviewing the diff — `useCloudRunState` / `useCloudChangedFiles`

`renderer/features/task-detail/hooks/useCloudRunState.ts:9-48` returns:

```ts
{
  ;(freshTask, session, prUrl, effectiveBranch, repo, cloudStatus, isRunActive, fallbackFiles, toolCalls)
}
```

- `effectiveBranch = task.latest_run?.branch ?? session?.cloudBranch`
- `cloudStatus = session?.cloudStatus ?? task.latest_run?.status`
- `isRunActive = queued | in_progress | (cloudStatus === null && session != null)`
- `fallbackFiles` is computed from in-session ACP tool-call stream

`useCloudChangedFiles` (`useCloudChangedFiles.ts:11-54`):

- If `prUrl`: `usePrChangedFiles(prUrl)` (GitHub PR file list)
- Else if `effectiveBranch`: `useBranchChangedFiles(repo, branch)`
- Returns `{ ...cloudRunState, remoteFiles, reviewFiles, isLoading, hasError }`. `reviewFiles` is `remoteFiles` when populated, else `fallbackFiles`

### 13.18 Tool-call → ChangedFile derivation

`renderer/features/task-detail/utils/cloudToolChanges.ts:1-318`. Walks `session.events`, picks up `session/update` ACP notifications with `sessionUpdate === "tool_call" | "tool_call_update"`. Skips failed tool calls and `.claude/plans/` paths.

```ts
interface ParsedToolCall {
  toolCallId: string
  kind?: string | null // "write" | "edit" | "delete" | "move" | "read" | ...
  title?: string
  status?: string | null
  locations?: ToolCallLocation[]
  content?: ToolCallContent[] // may include `{ type: "diff", path, oldText, newText }`
}
```

- `inferKind(kind, title)` — derives from title prefix when kind is missing
- `extractCloudToolChangedFiles` — `ChangedFile[]` per path, deduped to last write. Counts via `getDiffStats` (bag-of-lines heuristic)
- `extractCloudFileDiff(toolCalls, filePath)` — `{ oldText, newText }`: oldText from first match, newText from last
- `extractCloudFileContent(toolCalls, filePath)` — `{ content, touched }`: rebuilds latest content for a file across read/write/delete/move events

### 13.19 `CloudReviewPage`

`renderer/features/code-review/components/CloudReviewPage.tsx:17-141`. Reads `isReviewOpen` from `reviewNavigationStore` and `showReviewComments` from `diffViewerStore`. Pulls files via `useCloudChangedFiles`. PR-comments only fetched if `isReviewOpen && showReviewComments`.

GitHub file URL: `{prUrl}/files#diff-{path-with-slashes-replaced-by-hyphens}`.

Empty states:

- `!prUrl && !effectiveBranch && reviewFiles.length === 0 && isRunActive` → "Waiting for changes..."
- Same condition but inactive → render nothing
- Otherwise: `ReviewShell` with line-counts, expand/collapse, per-file `PatchedFileDiff` (uses `toolCallFallbacks` only when `remoteFiles.length === 0`)

### 13.20 File tree / code editor — read-only cloud

`FileTreePanel.tsx:147-205`: file tree is **not** the live filesystem for cloud.

- `isRunActive && !hasFallbackChanges` → Spinner + "Running in cloud..." / "Files are in the cloud sandbox"
- Otherwise: "Files are in the cloud sandbox" + "View on GitHub" link (`{prUrl}/files` or `https://github.com/{repo}/tree/{branch}`)

`CodeEditorPanel.tsx:119-212`:

- `isCloudRun && isImage` → "Images not available for cloud runs"
- `isCloudRun && !cloudFile.touched` → "File content not available — the agent did not read or write this file"
- `isCloudRun && touched && content == null` → "This file was deleted by the agent"

### 13.21 Sidebar / task list

`renderer/features/sidebar/components/items/TaskIcon.tsx:26-204`. `CloudStatusIcon` maps `taskRunStatus`:

- `queued | in_progress` → animated cloud, tooltip "Cloud (running)"
- `completed` → green filled cloud, "Cloud (completed)"
- `failed` → red filled cloud, "Cloud (failed)"
- `cancelled` → red filled cloud, "Cloud (cancelled)"
- otherwise → plain cloud, "Cloud"

Priority cascade for the row icon (line 159-203):

1. `needsPermission` (blue hand-palm) — beats everything
2. Terminal cloud → `CloudStatusIcon`
3. `isGenerating` → animated dots spinner
4. Active cloud (queued/in_progress) → `CloudStatusIcon` (animated)
5. Suspended → pause icon
6. Unread → green dot
7. `prState || hasDiff` → PR icon
8. Pinned → push-pin
9. Default → chat-circle

### 13.22 Cloud environments settings

`renderer/features/settings/components/sections/environments/CloudEnvironmentsSettings.tsx:187-590`.

List screen:

- Intro copy explains scope (account-wide)
- "+ New environment" button
- Per row: name, colored Badge (`green` full / `blue` trusted / `orange` custom), optional "N domain(s)" line, edit pencil

Form screen:

- Header: "Creating cloud environment" or "Editing cloud environment {name}" (with "Changes take effect on next session" hint on edit)
- **Name** text input
- **Network access** dropdown:
  - `full` — "Full" / "Unrestricted internet access"
  - `trusted` — "Trusted" / "Downloads packages from verified sources"
  - `custom` — "Custom" / "Create a list of allowed domains"
- **Allowed domains** (custom only) textarea, one per line, validated against `DOMAIN_RE = /^(\*\.)?[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)*$/`
- **Include defaults** checkbox (custom only)
- **Environment variables** textarea, `KEY=value` per line, validated against `/^[A-Za-z_][A-Za-z0-9_]*$/`. On edit, existing values aren't shown back: "Environment variables are set. Enter new values to replace them."
- Footer: Cancel + Save. Disabled if name empty or validation errors. On edit: Archive (red trash) button bottom-left.

---

## 14. Empty / error states catalogue

| State                                                                                        | Where                                                        | Trigger                                         |
| -------------------------------------------------------------------------------------------- | ------------------------------------------------------------ | ----------------------------------------------- |
| "Reserving a cloud sandbox — this can take a few seconds."                                   | `CloudInitializingView`                                      | `cloudStatus === "queued"`                      |
| "Connecting to your cloud runner."                                                           | `CloudInitializingView`                                      | `cloudStatus === "in_progress"` or null         |
| "Getting things ready…"                                                                      | `CloudInitializingView`                                      | other non-terminal cloud status                 |
| Plain spinner (no copy)                                                                      | `CloudInitializingView`                                      | first 2s of initialization                      |
| "Waiting for changes..."                                                                     | `CloudReviewPage`, `CloudChangesPanel`, `CloudFileTreePanel` | `isRunActive && no files yet`                   |
| "No file changes yet"                                                                        | `CloudChangesPanel`                                          | not active, no files                            |
| "No file changes in pull request"                                                            | `CloudChangesPanel`                                          | PR exists but no diff                           |
| "Could not load file changes" + "View on GitHub"                                             | `CloudChangesPanel`                                          | PR fetch failed                                 |
| "Cloud runs are read-only"                                                                   | `LeafNodeRenderer` empty state                               | Empty panel in cloud mode                       |
| "Files are in the cloud sandbox" + "View on GitHub"                                          | `CloudFileTreePanel`                                         | post-run summary                                |
| "Images not available for cloud runs"                                                        | `CodeEditorPanel`                                            | Image file in cloud mode                        |
| "File content not available — the agent did not read or write this file"                     | `CodeEditorPanel`                                            | Untouched file in cloud mode                    |
| "This file was deleted by the agent"                                                         | `CodeEditorPanel`                                            | Touched but null content                        |
| "Lost connection to the cloud run. Retry to reconnect."                                      | `SessionView` error overlay                                  | `CloudTaskErrorUpdate` without explicit message |
| "Cloud run couldn't start. Check that GitHub is connected for this project, then try again." | `SessionView` error overlay                                  | terminal-failed with no agent connection        |
| "Connecting your personal GitHub is required to run cloud tasks." + "Connect GitHub"         | `CloudGithubMissingNotice`                                   | cloud mode + no integration                     |
| "No cloud environments configured yet…"                                                      | `CloudEnvironmentsSettings`                                  | empty list                                      |
| Toast "Fix validation errors before saving"                                                  | `CloudEnvironmentsSettings.handleSave`                       | invalid domain/env-var lines                    |

---

## 15. Feature flags

- `twig-cloud-mode-toggle` — gates the cloud option in `WorkspaceModeSelect`. Always on in dev.
- `phc-cloud-handoff` — gates the "Continue locally" / "Continue in cloud" buttons. Dev-on.

---

## 16. Analytics events emitted

- `TASK_CREATED` (`useTaskCreation.ts:134-153`) with `workspace_mode`, `has_sandbox_environment`, `cloud_run_source`, `cloud_pr_authorship_mode`.
- `PROMPT_SENT` (`service.ts:1800-1805, 2031-2036`) with `execution_type: "cloud"`, `is_initial`, `prompt_length_chars`.
- `TASK_RUN_CANCELLED` (`service.ts:2071-2076`) with `execution_type: "cloud"`.
- `PERMISSION_RESPONDED` / `PERMISSION_CANCELLED` / `SESSION_CONFIG_CHANGED` — shared.
- `TASK_VIEWED` (navigation store).

---

## 17. Settings store touchpoints

`renderer/features/settings/stores/settingsStore.ts:46-251`:

- `defaultRunMode: "last_used" | ...` — controls home-page default between local and cloud
- `lastUsedRunMode: "local" | "cloud"`
- `lastUsedLocalWorkspaceMode`, `lastUsedWorkspaceMode` — restore on next session
- `lastUsedCloudRepository: string | null` — `"org/repo"` lowercased
- `lastUsedEnvironments: Record<string,string>` — repo path or local folder path → environment id
- `debugLogsCloudRuns: boolean` — Advanced settings toggle that reveals `_posthog/console`/`_posthog/progress` notifications

---

## 18. End-to-end flow — quick checklist for a new frontend

The minimum order of operations to reproduce the desktop behavior:

1. **Authenticate**: obtain `projectId` + `cloudRegion` + API token. Map region to API host.
2. **Bootstrap data**: `GET /sandbox_environments/`, `GET /tasks/`, `GET /tasks/{id}/runs/`.
3. **Create a task**: collect prompt + repo + branch + optional `sandbox_environment_id`:
   - `POST /tasks/` (title, description, repository, optional `github_user_integration`)
   - `POST /tasks/{id}/runs/` with `environment: "cloud"`, `mode: "interactive"`, `branch`, `runtime_adapter`, `model`, `reasoning_effort`, `sandbox_environment_id`, `pr_authorship_mode`, `run_source`, `initial_permission_mode`
   - Per attachment: `prepare_upload` → S3 POST → `finalize_upload`
   - `POST /tasks/{id}/runs/{rid}/start/` with `pending_user_message` + `pending_user_artifact_ids`
4. **Stream updates**: open SSE `/stream/?start=latest` and `Last-Event-ID` header. Process `task_run_state`, `permission_request`, `keepalive`, `error`, plus arbitrary `StoredLogEntry` events. Reconnect with capped exponential backoff (5 attempts, base 2s, cap 30s). On 401/403/404 → fail non-retryable.
5. **Backfill on open**: in parallel with SSE, paginate `GET /session_logs/?limit=5000` until `X-Has-More: false`. Hold live events in a buffer during fetch. Emit one snapshot. Dedup live entries against history by serialized JSON.
6. **Render diff**: pull `output.pr_url`; otherwise use the GitHub branch via `effectiveBranch`; otherwise infer from `session/update` `tool_call` events.
7. **Surface PR**: deep-link to `output.pr_url`. File-level deep link: `${prUrl}/files#diff-${path.replaceAll("/","-")}`.
8. **Send follow-up**: `POST /command/` `{ method: "user_message", params: { content?: string | ContentBlock[], artifacts? } }`. Optimistic UI. Queue when status is `queued` or no `_posthog/run_started` yet.
9. **Mid-run controls**: same channel — `cancel`, `permission_response`, `set_config_option`, `refresh_session`.
10. **Resume**: when posting after a terminal run, hit `POST /tasks/{id}/run/` with `resume_from_run_id`, `pending_user_message`, `pending_user_artifact_ids`, carrying over `pr_authorship_mode`, `run_source`, `signal_report_id`, `adapter`, `model`, `reasoning_effort` from prior run's `state`.
11. **(Optional)** Sandbox-environment CRUD via `/sandbox_environments/`.
12. **(Optional)** Local↔cloud handoff is desktop-specific; skip for web/mobile.

---

## 19. Key file index

For verification or follow-up reading:

**Backend (PostHog cloud + desktop main process):**

- REST client (sandbox-side): `packages/agent/src/posthog-api.ts`
- REST client (desktop renderer): `apps/code/src/renderer/api/posthogClient.ts`
- tRPC router: `apps/code/src/main/trpc/routers/cloud-task.ts`
- Watcher service: `apps/code/src/main/services/cloud-task/service.ts`
- Watcher schemas: `apps/code/src/main/services/cloud-task/schemas.ts`
- SSE parser: `apps/code/src/main/services/cloud-task/sse-parser.ts`
- Handoff-to-cloud saga: `apps/code/src/main/services/handoff/handoff-to-cloud-saga.ts`
- Cloud-prompt wire format: `packages/shared/src/cloud-prompt.ts`

**Agent server (in-sandbox):**

- Main: `packages/agent/src/server/agent-server.ts`
- CLI entry: `packages/agent/src/server/bin.ts`
- JWT: `packages/agent/src/server/jwt.ts`
- Server schemas: `packages/agent/src/server/schemas.ts`
- Cloud prompt normalizer: `packages/agent/src/server/cloud-prompt.ts`
- Session log writer: `packages/agent/src/session-log-writer.ts`
- ACP extension constants: `packages/agent/src/acp-extensions.ts`

**Frontend (Electron renderer):**

- Types: `apps/code/src/shared/types.ts`, `apps/code/src/shared/types/cloud.ts`, `apps/code/src/shared/types/session-events.ts`
- Cloud-task watcher (renderer): `apps/code/src/renderer/features/sessions/service/service.ts` (`watchCloudTask`, `sendCloudPrompt`, `resumeCloudRun`, `cancelCloudPrompt`)
- Connection wiring: `apps/code/src/renderer/features/sessions/hooks/useSessionConnection.ts`
- Derived state: `apps/code/src/renderer/features/sessions/hooks/useSessionViewState.ts`
- View: `apps/code/src/renderer/features/sessions/components/SessionView.tsx`
- Initializing screen: `apps/code/src/renderer/features/sessions/components/CloudInitializingView.tsx`
- Diff page: `apps/code/src/renderer/features/code-review/components/CloudReviewPage.tsx`
- Diff helpers: `apps/code/src/renderer/features/task-detail/utils/cloudToolChanges.ts`
- Diff hooks: `apps/code/src/renderer/features/task-detail/hooks/useCloudRunState.ts`, `useCloudChangedFiles.ts`, `useCloudEventSummary.ts`
- PR URL: `apps/code/src/renderer/features/git-interaction/hooks/useCloudPrUrl.ts`
- File content shim: `apps/code/src/renderer/features/code-editor/hooks/useCloudFileContent.ts`
- Cloud-prompt utils (renderer): `apps/code/src/renderer/features/editor/utils/cloud-prompt.ts`, `apps/code/src/renderer/features/sessions/utils/cloudArtifacts.ts`
- Task input: `apps/code/src/renderer/features/task-detail/components/TaskInput.tsx`
- Workspace-mode dropdown: `apps/code/src/renderer/features/task-detail/components/WorkspaceModeSelect.tsx`
- Branch selector: `apps/code/src/renderer/features/git-interaction/components/BranchSelector.tsx`
- GitHub-missing notice: `apps/code/src/renderer/features/task-detail/components/CloudGithubMissingNotice.tsx`
- Task creation saga: `apps/code/src/renderer/sagas/task/task-creation.ts`
- Sandbox env settings: `apps/code/src/renderer/features/settings/components/sections/environments/CloudEnvironmentsSettings.tsx`
- Sandbox env hook: `apps/code/src/renderer/features/settings/hooks/useSandboxEnvironments.ts`
- Sidebar status icon: `apps/code/src/renderer/features/sidebar/components/items/TaskIcon.tsx`
- Inbox cloud-task launcher: `apps/code/src/renderer/features/inbox/stores/inboxCloudTaskStore.ts`
- Is-this-cloud hook: `apps/code/src/renderer/features/workspace/hooks/useIsCloudTask.ts`
- Existing high-level doc: `notes/CLOUD_ARCHITECTURE.md`
