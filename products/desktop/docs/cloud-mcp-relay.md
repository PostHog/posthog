# Design: relaying local MCP servers into cloud task runs

Status: **implemented** (same PR as the import work), behind the same
`posthog-code-local-mcp-import` flag as the import (one feature, one flag).
Follows
[cloud-mcp-import.md](./cloud-mcp-import.md) (which handles the easy case:
url-based servers on public hosts). Sandbox side: `McpRelayServer`
(`packages/agent/src/server/mcp-relay-server.ts`). Desktop execution:
`McpRelayService` (`packages/workspace-server/src/services/mcp-relay/`).
Client coordination: `CloudTaskService.handleMcpRelayRequest`
(`packages/core/src/cloud-task/cloud-task.ts`). Django broker: PR #68954.

Implementation notes where reality refined the design: relay designations are
held in memory by the creating client's main process — an app restart drops
them, and relayed servers stop working for in-flight runs (they 503 after the
liveness window) rather than surviving a handoff. Tool allowlisting for
relayed servers persists for the session lifetime, not to the backend.

## Problem

Two classes of local MCP servers cannot be imported into a cloud sandbox by
forwarding a URL:

- **stdio servers** — a process spawned on the user's machine
  (`npx @playwright/mcp`, a company-internal CLI, ...).
- **private-URL servers** — `http`/`sse` servers only reachable from the
  user's machine or network (localhost, RFC1918, tailnet, VPN).

Both classes are classified `requires_desktop` by
`LocalMcpImportService` (`packages/core/src/local-mcp/localMcpImport.ts`).
This design makes them usable from a cloud run by relaying MCP JSON-RPC over
the existing durable Django-brokered channel back to the desktop app, which
executes each request against the real server and returns the result.

## Prior art: the question relay

The exact shape already exists for permission requests / questions
(`packages/agent/src/server/agent-server.ts`):

- Sandbox → client: a `permission_request` **event** with a
  `requestId = crypto.randomUUID()` correlation id, broadcast over both the
  durable event stream (`TaskRunEventStreamSender` → Django ingest → client
  SSE) and the direct SSE connection.
- Client → sandbox: a `permission_response` **command** POSTed to
  `/api/projects/{team}/tasks/{task}/runs/{run}/command/`, which Django
  forwards to the sandbox's `/command` endpoint; the sandbox resolves the
  pending promise by `requestId`.
- Recovery: the request is also written to the session log as a
  `_posthog/permission_request` notification so a client that attaches later
  can re-surface it.

The MCP relay mirrors this with a new event/command pair.

## Architecture

```
sandbox                                          desktop
┌──────────────────────────────┐                 ┌──────────────────────────────┐
│ Claude/Codex adapter          │                 │ McpRelayService              │
│   │ plain http MCP call       │                 │  (workspace-server)          │
│   ▼                           │                 │   │ owns real connections:   │
│ McpRelayServer (loopback      │  mcp_request    │   │ spawns stdio processes,  │
│ 127.0.0.1, one route per      │  event ───────► │   │ dials private URLs       │
│ relayed server)               │  (event stream) │   ▼                          │
│   pendingRelayRequests        │                 │ executes JSON-RPC            │
│   Map<requestId, resolver>    │ ◄─────── mcp_response command                  │
└──────────────────────────────┘  (Django /command/)                            │
                                                  └──────────────────────────────┘
```

### Sandbox side (`packages/agent/src/server/`)

A new `McpRelayServer` starts one loopback HTTP MCP endpoint per
relay-designated server
(`http://127.0.0.1:<port>/relay/<serverName>`, guarded by a per-run bearer
secret) and registers each in the session's `mcpServers` list as a plain
`http` entry. **The Claude/Codex adapters need no changes** — they see an
ordinary streamable-HTTP MCP server.

Per incoming HTTP request:

1. Read the JSON-RPC payload; enforce the size cap (below).
2. `requestId = crypto.randomUUID()`; store a resolver in
   `pendingRelayRequests`.
3. `broadcastEvent({ type: "mcp_request", requestId, server, payload,
   expiresAt })` — same path as `permission_request`, so it reaches the
   desktop over the durable stream and direct SSE.
4. Await the resolver with a timeout (default 60 s). On timeout, delete the
   entry and answer the HTTP request with a JSON-RPC error
   (`-32001`, "MCP relay timed out waiting for the desktop app"). Late
   responses find no pending entry and are dropped.
5. On `mcp_response`, answer the HTTP request with the relayed JSON-RPC
   result or error verbatim.

JSON-RPC *notifications* (no `id`) are relayed fire-and-forget: emit the
event, answer 202 immediately.

Liveness: the relay endpoints use the permission relay's `hasReachableClient`
signal (a direct SSE viewer OR an active durable event stream) but must not
503 during the ~2 s startup window before the first client attaches — an MCP
client connects to each server once at session start, so a 503 there drops
the server for the whole run. So the endpoint tracks `everReachable` and only
503s once a client has been reachable and then went away (a genuine mid-run
desktop disconnect). Before the first client ever attaches, the request is
buffered — `broadcastEvent` already buffers-and-replays events until a
controller attaches — and resolves when the client arrives or the request
times out. (An earlier design gated purely on a `desktopSeenAt` timestamp,
which 503'd the startup handshake in the durable-ingest topology, where the
desktop reads the run's stream through the agent-proxy and never connects to
the sandbox directly; that's why the gate is `everReachable`-then-lost, not
"seen recently".) Relay endpoints only exist when a desktop designated
servers at creation, so a non-headless run is the precondition anyway. So:

- Claude gets a clean MCP error on a genuine mid-run disconnect, not a 60 s
  hang, and its session-start handshake is never dropped by a startup 503.
- Codex reachability probes treat any HTTP response (including the buffered
  200 or a 503) as reachable and connection failures as not — see
  `isMcpServerReachable` in
  `packages/workspace-server/src/services/agent/agent.ts` — so a loopback
  relay endpoint always probes as reachable and is never pruned from a Codex
  session.

Headless-started runs (web/mobile/Slack) have no desktop: those creation
paths never declare relayed servers, so the endpoints simply don't exist.

### Desktop side (`packages/workspace-server/`)

A new `McpRelayService`:

- Receives `mcp_request` events. Transport: the renderer already consumes
  the run's event stream in `packages/core/src/cloud-task/cloud-task.ts`;
  core forwards relay events to workspace-server through the existing tRPC
  seam (a `relayMcpRequest` procedure), keeping Node-only work (process
  spawn, private-network dial) in workspace-server per the architecture
  rules. Core owns the decision logic (which server, dedupe, run
  association); workspace-server owns execution.
- Owns one real MCP client connection per relayed server, created lazily
  from the *local* config (`LocalMcpService`): stdio configs spawn the
  process (with their configured `env`), url configs dial with their
  configured headers. **The wire never carries commands, args, env, or
  headers** — the desktop looks the server up by name in local config; a
  request naming an undesignated server is rejected.
- Executes the JSON-RPC request and POSTs the reply as an `mcp_response`
  command through the existing command path
  (`trpc.cloudTask.sendCommand` → Django `/command/` → sandbox).
- Dedupes by `requestId` (LRU of recently handled ids): the event stream is
  at-least-once, and reconnect replays must not re-execute tool calls.
- Drops requests whose `expiresAt` has passed (stale backlog after a long
  disconnect).

### Schemas

Zod, in `packages/agent/src/server/schemas.ts` (sandbox) and
`packages/core/src/cloud-task/schemas.ts` (client):

```ts
// Event: sandbox → desktop (event stream + SSE)
const mcpRequestEventSchema = z.object({
  type: z.literal("mcp_request"),
  requestId: z.uuid(),
  server: z.string().min(1),          // relayed server name
  payload: z.record(z.string(), z.unknown()), // JSON-RPC request/notification
  expiresAt: z.iso.datetime(),
});

// Command: desktop → sandbox (POST /command/)
const mcpResponseParamsSchema = z.object({
  requestId: z.uuid(),
  server: z.string().min(1),
  // Exactly one of:
  payload: z.record(z.string(), z.unknown()).optional(), // JSON-RPC response
  error: z
    .object({ code: z.number(), message: z.string() })
    .optional(),                       // desktop-side failure (server gone, spawn failed)
});
```

## Security posture

A sensitive relayed request is the cloud agent accessing something **on the
user's machine or network with the user's local privileges**. Decisions:

1. **Always-ask, enforced on the desktop.** The desktop allows only MCP
   lifecycle and discovery methods without approval. Every other request,
   including `tools/call`, `resources/read`, and `prompts/get`, waits for a
   desktop-owned prompt in `CloudTaskService.handleMcpRelayRequest`. This is
   the real trust boundary: the sandbox's own prompts and options cannot grant
   local execution, and codex has no per-MCP-call approval hook. A harness such
   as claude may therefore prompt before the desktop asks again; the second
   prompt is intentional because only the desktop controls local execution.
   "Always allow" is scoped to the run + server + tool or method and dropped
   when the run reaches a terminal status. A denial (with optional feedback)
   is returned to the sandbox as a JSON-RPC error rather than executed.
2. **No configuration crosses the wire.** The sandbox only ever names a
   server; what "grafana" means (command line, env, URL, headers) is resolved
   from local config on the desktop. A compromised sandbox cannot make the
   desktop spawn an arbitrary process or call an arbitrary URL.
3. **Designation is explicit per run.** Run creation declares
   `relayed_mcp_servers` (names only). The desktop refuses requests for
   servers not designated for that run, and refuses relay entirely for runs
   it did not create (the designating client is the only relay executor).
4. Relay endpoints in the sandbox are loopback-only and bearer-guarded, so
   other sandbox processes can't use them as an open proxy into the user's
   network beyond what the agent itself can do.

## Durability decision

`mcp_request` events flowing through the Django-brokered stream are
persisted with the run's other events by default. **Decision: keep them
persisted, with caps and the no-secrets rule above.**

- Request payloads are tool calls the agent made — the same content that
  already lands in the transcript as tool-call events; persisting them has
  audit value and keeps replay/late-attach semantics identical to the
  question relay. No separate ephemeral channel for v1 (a direct tunnel is a
  large infra project and defeats the "works through the existing durable
  broker" goal).
- Caps: request payload ≤ 64 KB (larger → immediate JSON-RPC error, no
  event emitted); response payload ≤ 256 KB (larger → desktop replies with a
  truncation error, agent sees a clear MCP error). These sit inside the
  event-stream sender's existing 900 KB per-event drop threshold with room
  to spare.
- Responses travel the command path, which Django forwards without
  persisting today; the spec below requires that to stay true (or, if
  command auditing is added, `mcp_response.payload` must be excluded —
  responses can contain data the user's private systems returned and never
  intended to store in PostHog).

## Django-side spec (not implemented in this repo)

- **Run creation** (`POST .../runs/`): optional
  `relayed_mcp_servers: [{ "name": "<string ≤ 64 chars>" }]`, ≤ 20 entries,
  names unique and disjoint from `imported_mcp_servers` names. Persisted on
  the run (names only — no secrets). Passed to sandbox provisioning so the
  agent server can start relay endpoints (e.g. a `--relayMcpServers` flag).
- **Command endpoint** (`POST .../runs/{run}/command/`): allow method
  `mcp_response`; validate params against the schema above; body ≤ 300 KB;
  forward to the sandbox verbatim; do not persist params. Only accept from
  the run's owning user (same auth as other commands).
- **Event ingest**: `mcp_request` is a new event type in the run's stream;
  no schema change needed if ingest is shape-agnostic, but if event types
  are allowlisted, add it. Persisted and returned over the client SSE like
  other events.

## Failure modes

| Failure | Behavior |
| --- | --- |
| Desktop never attaches (offline from session start) | Request buffers until it times out (60 s) → agent gets JSON-RPC `-32001`; the endpoint does **not** 503 during startup (that would drop the server for the whole run). |
| Desktop disconnects mid-run (was reachable, now gone) | Endpoint 503s (`everReachable && !reachable`); agent sees a clean "requires the desktop app" MCP error rather than a hang. |
| Desktop disconnects mid-call | Sandbox timeout fires (60 s), agent gets JSON-RPC `-32001`. |
| Desktop reconnects after backlog | Replayed `mcp_request` events past `expiresAt` are dropped; unexpired ones are deduped by `requestId`. |
| stdio process crashes | Desktop replies with `error`; next request lazily respawns. |
| Two desktops attached | First `mcp_response` per `requestId` wins; later ones are dropped by the pending-map lookup (same as double permission responses). |

## Testing plan

- Sandbox: unit tests for the correlation map — resolve, timeout, late
  response, oversized payload, notification fire-and-forget, startup
  buffering before any client attaches, and 503 only after a client was
  reachable and then went away (Vitest).
- Desktop: unit tests for `McpRelayService` — name designation enforcement,
  requestId dedupe, expiry drop, stdio spawn failure → error reply (faked
  MCP client).
- E2E behind the flag: local run of the agent server with a stub desktop
  executor exercising a full tool-call round trip.

## Rollout

1. This design doc (own PR, review gate).
2. Sandbox `McpRelayServer` + schemas + tests.
3. Desktop `McpRelayService` + core forwarding seam + tests.
4. Creation-payload plumbing (`relayed_mcp_servers`) + composer UX flips the
   "Requires your machine" annotation to "Relayed via your machine".
5. Enable `posthog-code-local-mcp-import` for staff once the Django side lands.
