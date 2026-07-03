# MCP auth demo — shared connection vs per-asker identity

This agent exists to show the **two ways an agent reaches an MCP server**, side
by side. Open it in the agent config UI: each entry under `mcps[]` renders
differently and the descriptions spell out how each is set up.

## 1. Agent-level — one shared connection (`mcps[].connection`)

`incident` is an **agent-level** MCP. The agent owner connects the server
**once** (OAuth incl. dynamic client registration, or an API key) and stores it
as a native MCP connection; **every asker of this agent reuses that one
credential** and never signs in themselves.

- **Set it up:** in the agent config, open the `incident` MCP → pick (or
  "Connect new") a connection. The shipped spec points at a placeholder
  connection id, so a fresh project shows _"Referenced connection isn't in this
  project — reconnect it or pick another"_. Connect incident.io once and select
  it; from then on it's shared.
- **Tool permissions** are set per agent, right here: a connection-wide default
  (`default_tool_approval`, here `approve` = ask before every call) plus
  per-tool overrides (allow / approve / deny). The runner loads the shared
  bearer from the connection row and applies these.
- **Use it when:** the agent should act as _one team identity_ (a service
  account), not as the individual asking.

## 2. Principal-level — per-asker identity (`mcps[].auth.provider`)

`posthog` is a **principal-level** MCP. It references an entry in
`identity_providers[]` (here a `posthog` OAuth provider). There is **no shared
credential** — instead, **each asker authenticates as themselves** the first
time they hit a tool that needs it (an auth-required link is surfaced; they
complete the OAuth and the agent then acts _as that user_).

- **Set it up:** declare the provider in `identity_providers[]` and point the
  MCP's `auth.provider` at it. Askers link their own account on first use;
  nobody pre-connects anything.
- **Use it when:** the agent must act _as the person asking_ (their data, their
  permissions) — e.g. querying PostHog as the requesting user.

## TL;DR

|             | Agent-level (`connection`)                 | Principal-level (`auth.provider`)             |
| ----------- | ------------------------------------------ | --------------------------------------------- |
| Credential  | one shared, owner connects once            | per-asker, each links their own               |
| Acts as     | a team/service identity                    | the individual asking                         |
| Setup       | owner picks a connection in the UI         | declare a provider; askers OAuth on first use |
| Tool gating | `default_tool_approval` + per-tool `level` | (per the tool's own approval)                 |

Keep replies short; this agent is a reference, not a worker.
