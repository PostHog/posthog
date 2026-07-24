# @posthog/agent

The core runtime for PostHog cloud runs. Provides two things: an **Agent SDK** for running AI agents against PostHog tasks, and an **AgentServer** CLI that hosts the agent inside cloud sandboxes. Both are built on the [Agent Client Protocol (ACP)](https://github.com/anthropics/agent-client-protocol) for standardized agent ↔ client communication.

## Architecture

```text
┌──────────────────────────────────────────────────────────────────┐
│  Client (PostHog desktop app or local CLI)                                  │
│    connects via SSE/JSON-RPC (cloud) or in-process streams (local)│
└────────────────────┬─────────────────────────────────────────────┘
                     │
          ┌──────────▼──────────┐
          │    AgentServer      │  (cloud only — Hono HTTP server)
          │  GET /events (SSE)  │
          │  POST /command      │
          └──────────┬──────────┘
                     │
          ┌──────────▼──────────┐
          │   ACP Connection    │  createAcpConnection()
          │  (ndJson streams)   │
          │                     │
          │  ┌── tap ──┐        │  both directions intercepted for:
          │  │ logging │        │  • SessionLogWriter (OTEL / S3)
          │  │ SSE     │        │  • SSE broadcast to clients
          │  └─────────┘        │
          └──────────┬──────────┘
                     │
        ┌────────────┼────────────┐
        ▼                         ▼
  ┌─────────────┐         ┌─────────────┐
  │ Claude      │         │ Codex       │
  │ Adapter     │         │ Adapter     │
  │             │         │             │
  │ ClaudeAcp-  │         │ spawnCodex- │
  │ Agent       │         │ Process()   │
  │ (in-process)│         │ (subprocess)│
  └──────┬──────┘         └──────┬──────┘
         │                       │
         ▼                       ▼
  Claude Agent SDK        codex-acp binary
  query()                 stdin/stdout
```

## Design decisions

### Why ACP?

ACP is a standard protocol for agent ↔ client communication over ndJson streams. Using it gives us two things:

1. **Any ACP-compatible client can connect** — the protocol is the contract, not our code.
2. **Clean separation** — the agent adapter knows nothing about HTTP, and the server knows nothing about Claude/Codex. They communicate through typed streams.

### Cloud vs local

The same ACP agent runs in both contexts. The difference is how it's connected:

**Cloud (AgentServer):** The agent runs inside a sandbox. `AgentServer` is an HTTP server (Hono) that wraps the ACP connection. Clients connect via `GET /events` (SSE) and `POST /command` (JSON-RPC). Authentication uses JWT tokens (RS256) — the sandbox holds a public key, PostHog Django holds the private key. In background mode, the server auto-starts, prompts the agent with the task description, and signals completion via the PostHog API. In interactive mode, it stays open for conversation.

**Local (desktop):** The agent runs in-process. The desktop app calls `createAcpConnection()` directly — no HTTP server, no JWT. The bidirectional ACP streams connect client ↔ agent within the same process.

**HandoffCheckpointTracker** handles the bridge between these contexts: it captures git checkpoint state plus the object pack/index needed to restore the worktree across cloud and local. This enables the "hand off" flow — start locally, continue in cloud, or vice versa.

### Permission modes

Four modes defined in `src/execution-mode.ts`:

| Mode               | ID                  | Behavior                                                        |
| ------------------- | ------------------- | --------------------------------------------------------------- |
| Always ask          | `default`           | Prompts for permission on first use of each tool                |
| Accept edits        | `acceptEdits`       | Auto-approves file write tools for the session                  |
| Plan mode           | `plan`              | Read-only — the agent can analyze but not modify files          |
| Bypass permissions  | `bypassPermissions` | Auto-approves everything (hidden when running as root)          |

In cloud background mode, permissions are always auto-approved. In interactive mode, the permission system is active and configurable per session. Tool categorization lives in `src/adapters/claude/tools.ts` — each tool belongs to a group (read, write, bash, search, web, agent) and modes whitelist groups.

Cloud provisioning can pass `--posthogExecPermissionRegex <regex>` to require one-time client approval for matching PostHog MCP `exec` sub-tools in every interactive cloud Claude and Codex permission mode. Non-matching sub-tools never prompt. Locally, hands-off modes stay hands-off: Claude `auto` and `bypassPermissions`, and Codex `auto` and `full-access`, auto-approve matching sub-tools; other local modes prompt. Matching is case-insensitive against the delegated name in `call [--json] <sub-tool> ...`. These prompts offer Claude users an always-allow choice remembered in local repository settings; Codex approvals remain one-time. An invalid or empty regex is logged and falls back to the default. Background runs keep their existing auto-approval behavior. The default is `(^|-)(partial-update|update|patch|delete|destroy)(-|$)`.

## ACP connection layer

`createAcpConnection()` in `src/adapters/acp-connection.ts` is the heart of the package. It's a factory that returns a `{ clientStreams, cleanup }` object — a pair of ndJson `ReadableStream`/`WritableStream` that the caller uses to speak ACP.

Internally it does three things:

1. **Creates bidirectional streams** — two pairs of `(readable, writable)` using `createBidirectionalStreams()`. One pair for the agent side, one for the client side, cross-wired so writes on one appear as reads on the other.

2. **Taps both directions for logging** — if a `logWriter` and `taskRunId` are provided, both the agent→client and client→agent writables are wrapped with `createTappedWritableStream`. Every ndJson line that flows through is appended to the `SessionLogWriter` buffer. This is transparent to both ends.

3. **Connects the adapter** — for Claude, it instantiates `ClaudeAcpAgent` and wires it to the agent-side streams via `AgentSideConnection`. For Codex, it spawns a subprocess and pipes the client-side streams to the process's stdin/stdout.

The Claude and Codex paths differ significantly:

**Claude (in-process):** The `AgentSideConnection` calls methods on `ClaudeAcpAgent` directly. The agent implements the full ACP `Agent` interface: `initialize`, `newSession`, `prompt`, `cancel`, etc. Under the hood, `prompt()` creates a Claude Agent SDK `Query` and processes messages in a loop, converting between ACP and SDK formats using the `src/adapters/claude/conversion/` module.

**Codex (subprocess):** There's no `AgentSideConnection` — the `codex-acp` binary speaks ACP natively on stdin/stdout. The connection layer adds `TransformStream` filters on both directions to: suppress noisy `session/update` messages during session loading, inject `_posthog/sdk_session` notifications, filter model lists to allowed IDs, and sync reasoning effort config before prompts.

## AgentServer

`AgentServer` (`src/server/agent-server.ts`) wraps an ACP connection in an HTTP server for cloud sandbox execution. It manages a single `ActiveSession` at a time.

### Session initialization flow

```text
start()
  │
  ├─ Hono HTTP server starts on configured port
  │
  └─ autoInitializeSession()
       │
       ├─ Creates synthetic JwtPayload from CLI config
       ├─ configureEnvironment() — sets ANTHROPIC_BASE_URL, OPENAI_BASE_URL, etc.
       │    pointing at the PostHog LLM gateway
       ├─ Creates HandoffCheckpointTracker, SessionLogWriter, PostHogAPIClient
       ├─ createAcpConnection() — sets up ACP streams with log tapping
       │
       ├─ Wraps client streams with a SECOND tap layer (NdJsonTap)
       │    that broadcasts every ACP message to SSE clients
       │
       ├─ ClientSideConnection.initialize() — ACP handshake
       ├─ ClientSideConnection.newSession() — starts agent session
       │
       └─ sendInitialTaskMessage()
            ├─ Fetches task from PostHog API
            ├─ Sends task.description as first prompt
            └─ Background mode: signals completion/failure via API
               Interactive mode: stays open
```

The two tapping layers are distinct. The inner tap (from `createAcpConnection`) persists to logs. The outer tap (in `AgentServer`) broadcasts to SSE. This means log persistence works for both cloud and local, while SSE broadcast is cloud-only.

Adapters must remove provider notifications that do not belong to the active parent session before writing ACP updates. Persisted ACP updates do not retain enough provider-specific identity to separate a subagent transcript or completion from its parent safely during cloud replay.

### HTTP endpoints

| Method | Path       | Auth | Description                                              |
| ------ | ---------- | ---- | -------------------------------------------------------- |
| `GET`  | `/health`  | None | Returns `{ status: "ok", hasSession }`                   |
| `GET`  | `/events`  | JWT  | SSE stream — all ACP notifications broadcast in real time |
| `POST` | `/command` | JWT  | JSON-RPC commands: `user_message`, `cancel`, `close`     |

JWT validation (`src/server/jwt.ts`) uses RS256 with a configurable public key. The JWT payload carries `task_id`, `run_id`, `team_id`, `user_id`, `distinct_id`, and `mode`. The audience must be `posthog:sandbox_connection`.

### Commands flow through ACP

When `POST /command` receives a `user_message`, it doesn't handle it directly — it calls `clientConnection.prompt()` on the ACP `ClientSideConnection`, which sends a `session/prompt` message through the ACP streams to the agent. Similarly, `cancel` sends `session/cancel`. This means all commands follow the same path as in-process calls from the desktop app, with the HTTP layer just being a thin translation.

### Permission routing in cloud mode

The `AgentServer` provides the `requestPermission` callback to the `ClientSideConnection`. Background mode selects an allow option automatically. Interactive mode relays approvals that need a person over SSE and parks them until a client responds; other requests follow the selected permission mode.

### Checkpoint capture

After file-mutating tool calls, the server captures a git checkpoint via `HandoffCheckpointTracker` and broadcasts it as a `_posthog/git_checkpoint` SSE event. A final checkpoint is captured during session cleanup. This is how the client restores repo state for cloud↔local handoff.

### CLI

```bash
npx agent-server \
  --port 3001 \
  --mode interactive \
  --repositoryPath /path/to/repo \
  --posthogExecPermissionRegex '(^|-)(partial-update|update|patch|delete|destroy)(-|$)' \
  --taskId task_123 \
  --runId run_456
```

Required environment variables (validated by zod in `src/server/bin.ts`):

- `JWT_PUBLIC_KEY` — RS256 public key for sandbox auth
- `POSTHOG_API_URL` — PostHog API base URL
- `POSTHOG_PERSONAL_API_KEY` — API key for PostHog requests
- `POSTHOG_PROJECT_ID` — numeric project ID

Optional run telemetry (the logs pair must both be set, otherwise telemetry stays off):

- `POSTHOG_AGENT_OTEL_LOGS_URL` — full OTLP logs URL for run metadata, e.g. `https://us.i.posthog.com/i/v1/logs`
- `POSTHOG_AGENT_OTEL_LOGS_TOKEN` — project API key of the telemetry project
- `POSTHOG_AGENT_OTEL_TRACES_URL` — full OTLP traces URL, e.g. `https://us.i.posthog.com/i/v1/traces`; additionally enables one APM trace per run

When set, `AgentServer` ships an allowlisted metadata subset of the session log (run/turn/tool lifecycle, usage, error provenance — never message content, tool arguments, or raw error text; see `src/otel-telemetry.ts`) to PostHog Logs, tagged with `service.name=posthog-code-agent` and `run_id`/`task_id`/`team_id`/`user_id`/`distinct_id` resource attributes so cloud runs are filterable per user. With the traces URL set, each run also produces an APM trace (`task_run` root span, a `turn` span per prompt, a `tool_call:<kind>` span per tool call; see `src/otel-trace-builder.ts`), and log records carry the matching trace/span ids so Logs and APM cross-link.

The `task_run` root span is ended and exported at the run's in-process terminal point — a background run's prompt settling, a terminal failure, or session cleanup (`close`). It cannot wait for teardown: agent-server is an exec'd process inside the sandbox, so `docker stop` / Modal terminate kill it without SIGTERM ever arriving, and a span still open at that moment is lost. Interactive sessions that end via hard teardown (e.g. inactivity timeout) therefore lose the root span; turn/tool spans and logs still assemble under the same trace id.

## Agent SDK

The `Agent` class (`src/agent.ts`) is the entrypoint for local/programmatic usage. It handles LLM gateway configuration, log writer setup, and model filtering — then delegates to `createAcpConnection()`.

```typescript
import { Agent } from "@posthog/agent/agent"

const agent = new Agent({
  posthog: {
    apiUrl: "https://app.posthog.com",
    getApiKey: () => process.env.POSTHOG_PERSONAL_API_KEY!,
    projectId: 12345,
  },
})

// Run a task — returns an ACP connection with bidirectional streams
const connection = await agent.run(taskId, runId, {
  repositoryPath: "/path/to/repo",
  adapter: "claude", // or "codex"
})

// Attach a PR to the task run output
await agent.attachPullRequestToTask(taskId, prUrl)

// Cleanup: flush logs and release resources
await agent.cleanup()
```

Key difference from `AgentServer`: the SDK returns raw ACP streams for the caller to manage. There's no HTTP layer, no SSE broadcasting, and no auto-prompting. The caller is responsible for creating a `ClientSideConnection`, running the ACP handshake, and sending prompts. This is what the desktop app does when running agents locally.

For Codex adapters, `agent.run()` also fetches available models from the PostHog gateway and filters to OpenAI-compatible models, passing the allowed set to the ACP connection for model list filtering.

## Log pipeline and session resume

Logs serve two purposes: real-time observability and session resume. Every ACP message that flows through the tapped streams is persisted, creating a complete record of the conversation — user messages, agent responses, tool calls, tool results, git checkpoints, and metadata events. This record is the single source of truth for resuming a session from any point.

### Writing logs

`SessionLogWriter` (`src/session-log-writer.ts`) is a per-session multiplexer that buffers raw ndJson lines. On flush (auto-scheduled 500ms after writes, or explicit), it POSTs batched `StoredNotification` entries to the Django API via `PostHogAPIClient.appendTaskRunLog()`; the API stores them in S3 as the task run's `log_url`. This S3 log is the source of truth for the full transcript and for session resume.

Independently of that flush cycle, the writer tees every parsed non-chunk entry to optional `SessionLogSink`s at append time. In cloud, `OtelRunTelemetry` (`src/otel-telemetry.ts`) is wired as a sink and exports an allowlisted metadata subset (run/turn/tool lifecycle, usage, error provenance — never message content, tool arguments, or raw error text) to PostHog Logs, plus an APM trace per run when configured. See "Optional run telemetry" above for the env vars and behavior. Sink failures can never break S3 log persistence.

### Resuming from logs

When a session needs to continue (e.g. cloud↔local handoff, or recovering from a crash), `resumeFromLog()` in `src/resume.ts` reconstructs the agent's state from the persisted log. This is implemented as a `ResumeSaga` (`src/sagas/resume-saga.ts`) with the following steps:

```text
1. fetch_task_run   → GET /api/.../runs/{runId}/ to find the log_url
2. fetch_logs       → Download all StoredNotification entries
3. find_git_checkpoint → Scan backwards for latest _posthog/git_checkpoint
4. rebuild_conversation → Walk log entries to reconstruct conversation turns
5. find_device      → Scan backwards for last device info (local vs cloud)
```

The conversation rebuild (`rebuildConversation`) walks the log entries and reassembles turns from ACP `session/update` notifications:

- `user_message` / `user_message_chunk` → start a new user turn
- `agent_message_chunk` → accumulate into the current assistant turn (merging consecutive text blocks)
- `tool_call` / `tool_call_update` → track tool calls with their inputs
- `tool_result` → match results back to tool calls by `toolCallId`

The result is a `ResumeState` containing the conversation history as `ConversationTurn[]`, the latest git checkpoint, and metadata. This feeds into the ACP `session/load` or `_posthog/session/resume` methods on the Claude adapter, which initializes a new Claude SDK query with the rebuilt context.

## ACP extensions

ACP defines standard methods like `session/prompt`, `session/update`, and `session/cancel`. PostHog extends the protocol with custom notifications in the `_posthog/` namespace (`src/acp-extensions.ts`). These serve three purposes:

**Session lifecycle** — events that track the run from start to finish. Clients use these to update UI state (show progress, enable/disable controls, display completion). The Django API uses `task_complete` to mark the run as finished.

- `_posthog/run_started` — `{ sessionId, runId, taskId?, agentVersion }` — session initialized and ready. `agentVersion` is the agent's semver, used by clients to gate UI features against agent capabilities
- `_posthog/task_complete` — `{ sessionId, taskId }` — agent finished (success or end-turn)
- `_posthog/error` — `{ sessionId, message, error? }` — unrecoverable error
- `_posthog/status` — `{ sessionId, status, message? }` — progress updates
- `_posthog/sdk_session` — `{ taskRunId, sessionId, adapter }` — maps the ACP session to a task run and adapter type (emitted once per session, used by clients to know which adapter is active)

**State synchronization** — events that keep the client's view of the agent's state in sync. These are essential for the cloud↔local handoff flow and for the client to render accurate UI.

- `_posthog/branch_created` — `{ branch }` — agent created a git branch (client can update branch display)
- `_posthog/git_checkpoint` — `{ checkpointId, checkpointRef, branch, head, indexTree, worktreeTree, ... }` — git checkpoint captured for resume and handoff. This is the key event for session resume — the resume saga scans backwards for the latest checkpoint to restore files
- `_posthog/mode_change` — `{ mode, previous_mode }` — permission mode changed (client updates mode selector)
- `_posthog/compact_boundary` — `{ sessionId, timestamp }` — marks where context compaction occurred, so the client knows the conversation was summarized at this point
- `_posthog/task_notification` — `{ sessionId, type, message?, data? }` — generic extensible notification for adapter-specific events

**Client→agent commands** — notifications that flow from client to agent (via `POST /command` in cloud, or direct ACP in local). These are the "verbs" the client can send outside of `session/prompt`.

- `_posthog/user_message` — `{ content }` — user typed a message (translated to `session/prompt`)
- `_posthog/cancel` — cancel the current operation (translated to `session/cancel`)
- `_posthog/close` — close the session and clean up
- `_posthog/session/resume` — `{ sessionId }` — request to resume a previous session (triggers the resume flow on the Claude adapter)

**Debug** — operational visibility without polluting the ACP conversation.

- `_posthog/console` — `{ sessionId, level, message }` — structured debug/info/warn/error log from the agent internals
