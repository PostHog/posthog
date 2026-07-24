# Importing local MCP servers into cloud task runs

Status: client side implemented behind the `posthog-code-local-mcp-import`
feature flag. The Django side (spec below) is not implemented; until it lands,
the backend ignores the extra creation-payload field and cloud runs behave as
before.

## Problem

A local task run gets all of the user's MCP servers: the PostHog MCP plus
`MCPServerInstallation` records (built by `AgentAuthAdapter.buildMcpServers` in
`packages/workspace-server/src/services/agent/auth-adapter.ts`), and — for the
Claude adapter — the user's own servers from `~/.claude.json`
(`loadUserClaudeJsonMcpServers` in
`packages/agent/src/adapters/claude/session/mcp-config.ts`).

A cloud run's sandbox only gets what the backend bakes into the agent server's
`--mcpServers` flag at spawn (`remoteMcpServerSchema` in
`packages/agent/src/server/schemas.ts`: `http`/`sse` + `url` + `headers`). The
sandbox never reads `~/.claude.json`, so tasks that need the user's own MCP
servers (Grafana, Sentry, internal tools, ...) force the user back to local
runs.

This document covers **import**: forwarding url-based servers that are
reachable from the public internet. Servers that are not importable (stdio, or
private-network URLs) need the desktop **relay** — see
[cloud-mcp-relay.md](./cloud-mcp-relay.md).

## What the client does

1. **Read** — `LocalMcpService`
   (`packages/workspace-server/src/services/local-mcp/local-mcp.ts`) reads
   `~/.claude.json` through `loadUserClaudeJsonMcpServerEntries` (extracted
   from the Claude adapter's loader so both share one parser) and normalizes
   each entry to a `LocalMcpServerDescriptor` (`@posthog/shared`). stdio `env`
   values are dropped at this boundary — they routinely hold secrets the
   renderer has no use for.

2. **Classify** — `LocalMcpImportService`
   (`packages/core/src/local-mcp/localMcpImport.ts`) classifies each server:

   | Server | Availability | Why |
   | --- | --- | --- |
   | `http`/`sse` with a public URL | `importable` | The sandbox can reach it directly. |
   | `http`/`sse` on localhost, RFC1918, CGNAT (100.64/10, incl. Tailscale IPs), link-local, IPv6 ULA, `.local`/`.internal`/`.lan`/`.home`/`.home.arpa`/`.ts.net`, or a dotless intranet name | `requires_desktop` | Only reachable from the user's machine or network. |
   | `stdio` | `requires_desktop` | A local process; nothing to forward. |
   | Unparseable URL / non-http(s) scheme / unrecognized shape | `unsupported` | Can't run anywhere. |

   The heuristic errs toward private: a public server misclassified as private
   just stays desktop-only, while the reverse would ship an unreachable server
   (or leak headers) to the sandbox.

3. **Show** — the MCP servers view rail renders `LocalMcpRailSection`
   (`packages/ui/src/features/local-mcp/LocalMcpRailSection.tsx`), listing the
   user's local servers annotated "Available in cloud" / "Relayed via your
   machine" / "Built into cloud runs" / "Not available in cloud".

4. **Send** — importable servers are included in the run-creation payload
   (`imported_mcp_servers` in `buildCloudRunRequestBody`,
   `packages/api-client/src/posthog-client.ts`) in exactly the shape the agent
   server's `remoteMcpServerSchema` accepts, so the backend can pass them
   through to `--mcpServers` without transformation.

Project-scoped (`projects[cwd].mcpServers`) entries are currently only picked
up when a `cwd` is passed; cloud task creation selects a GitHub repository
rather than a local checkout, so cloud runs import user-scoped servers only.
Mapping repository → local checkout to include project-scoped servers is a
follow-up.

## Wire format

`POST /api/projects/{project_id}/tasks/{task_id}/runs/` gains one optional
field:

```json
{
  "imported_mcp_servers": [
    {
      "type": "http",
      "name": "grafana",
      "url": "https://mcp.grafana.example.com/mcp",
      "headers": [{ "name": "Authorization", "value": "Bearer ..." }]
    }
  ]
}
```

`type` is `"http" | "sse"`. `headers` may be empty.

## Django-side spec (not implemented in this repo)

The `posthog/posthog` repo owns run creation and sandbox provisioning. To
support the field:

**Validation** (reject the run creation with 400 on violation):

- ≤ 20 servers; `name` non-empty, ≤ 64 chars, unique within the list.
- `url` must parse, scheme `http`/`https`, host must not be loopback /
  RFC1918 / link-local / CGNAT / IPv6 ULA (re-validate server-side; the
  client's classification is a UX aid, not a security boundary). This matters
  because the sandbox egresses from PostHog infrastructure: a private URL
  here is a user-controlled SSRF vector against whatever the sandbox network
  can reach.
- Each header value ≤ 4 KB; whole field ≤ 32 KB serialized.
- Names must not collide with the reserved `posthog` server or with the names
  of the project's `MCPServerInstallation`-derived servers; on collision the
  imported server is dropped (installations win) and the run is still created.

**Storage**: header values are credentials (`Authorization: Bearer ...`).
Store them like other run secrets — encrypted at rest, write-only (never
echoed back from the run detail API), and excluded from logs/analytics.

**Spawn**: append the validated list to the `--mcpServers` array after the
PostHog MCP and installation-derived servers. No other transformation — the
payload shape is already `remoteMcpServerSchema`.

**Adapter caveat (resolved for Codex via the relay)**: codex-acp hard-fails a
session when any configured MCP server is unreachable, and the sandbox agent
server does no reachability pruning. So imported (direct-URL) servers only go
into the sandbox config for the Claude adapter — the backend gates
`get_imported_mcp_server_configs` on `runtime_adapter in {claude, unset}` as
belt-and-braces. For Codex runs the client instead routes importable servers
through the **relay** (`partitionLocalMcpServersForRun` in
`packages/core/src/local-mcp/localMcpImport.ts` puts them in
`relayed_mcp_servers` when the run's adapter is codex): the loopback relay
endpoint always answers codex's reachability probe, and the desktop executes
the server from local config — public-URL servers included. Desktop-only
servers relay for every adapter. Net effect: a GPT user keeps all their local
servers, at the cost of one desktop hop per call. `relayed_mcp_servers` is
capped at 20 (matching the backend), and desktop-only servers are kept ahead
of importables when the cap bites, since they have no other transport.

## Auth: header staleness and rotation

Headers are captured at launch. For servers whose tokens expire mid-run, the
rotation mechanism already exists on the sandbox side: the `refresh_session`
command (`refreshSessionParamsSchema`,
`packages/agent/src/server/schemas.ts`) pushes a fresh `mcpServers` list into
a running session, and the Claude adapter tears down and rebuilds the query
with the new list (`refreshSession` in
`packages/agent/src/adapters/claude/claude-agent.ts`).

What's missing is the client half — today the desktop never sends
`refresh_session` for cloud runs (`sendCommandInput` in
`packages/core/src/cloud-task/schemas.ts` stops at `set_config_option`).
Design:

1. Add `refresh_session` to the core cloud-task command schema and a
   `CloudTaskService` method that posts it through the existing
   `/runs/{run}/command/` endpoint with the full replacement `mcpServers`
   list (the agent server treats the list as authoritative; an empty list is
   a no-op by design, so "remove every imported server" cannot be expressed —
   acceptable for rotation).
2. Django: allow `refresh_session` through the command endpoint's method
   allowlist, apply the same validation as `imported_mcp_servers`, forward
   verbatim, and do not persist the params (they contain fresh credentials).
3. Desktop trigger: re-read `~/.claude.json` when it changes (the
   workspace-server already has file watchers) and push the updated list to
   active cloud runs.

**Why this ships as a documented follow-up rather than code**: static headers
in `~/.claude.json` carry no expiry metadata, and OAuth-backed servers
managed by Claude Code keep their tokens in Claude's credential store — not
in `mcpServers.headers` — so those servers aren't importable this way at all
(they surface as headerless imports that 401 in the sandbox; the relay in
[cloud-mcp-relay.md](./cloud-mcp-relay.md) covers them properly). For the
static-header servers we can import, there is nothing to watch except the
file itself, which is the trigger described above.

## Follow-ups

- Codex local config (`~/.codex/config.toml` `mcp_servers`) as a second
  source; needs a TOML parser, skipped for now.
- Project-scoped `~/.claude.json` servers for cloud runs (repository → local
  checkout mapping).
- `${VAR}` environment-variable expansion in header values (Claude Code
  expands these at session start; the import currently forwards them
  literally, so such servers will 401 until expanded).
- The `refresh_session` client path described above.
