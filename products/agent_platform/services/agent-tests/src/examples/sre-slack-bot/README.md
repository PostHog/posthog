# SRE Slack bot — alert triage assistant

First-iteration ("infant") SRE assistant.
Fires on Grafana alertmanager webhook calls and on `@mentions` from
Slack, gathers context using PostHog data + runbook URLs + Slack
thread history, posts a structured triage report back in the thread,
and ends the session.

## Status

**Infant.** Buildable today on shipped primitives — no platform
work blocks it.
Several value-loops are duct-taped because the proper primitive
doesn't exist yet; see [Gaps](#gaps-that-constrain-this-version) below.

## What it does

| Capability                                 | How                                                                                                                                                                                                                                             |
| ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Auto-triggered by incident.io webhooks** | `webhook` trigger at `/agents/<slug>/webhook` — point incident.io's webhook config here for hands-off alert response.                                                                                                                           |
| Triggered by Grafana / alertmanager        | Same `webhook` endpoint, different payload shape — auto-detected by the agent.                                                                                                                                                                  |
| Triggered by Slack `@mention`              | `slack` trigger, `mention_only: true`                                                                                                                                                                                                           |
| **DM the bot directly**                    | `slack` trigger, `allow_direct_messages: true` — on-call asks it privately; one rolling session per DM, idle-reset by the sweep                                                                                                                 |
| Chattable from the agent console           | `chat` trigger — open the agent in the console and use the playground dock                                                                                                                                                                      |
| Calls the Slack Web API directly           | `@posthog/http-request` + `SLACK_BOT_TOKEN` secret (bring-your-own bot, no integration)                                                                                                                                                         |
| **Reads + writes incident.io via its MCP** | `mcps[incident-io]` tools (`incident_list` / `incident_show` / `incident_update` / `incident_create`) — lists active incidents, posts triage updates onto the timeline. See [MCP servers](#mcp-servers--two-auth-models).                       |
| Queries PostHog event data **and logs**    | `@posthog/query` (HogQL against `events` + the `logs` table — schema documented in `agent.md`)                                                                                                                                                  |
| Fetches runbook URLs                       | `@posthog/http-request`                                                                                                                                                                                                                         |
| Remembers prior incident outcomes          | `@posthog/table-query`, `@posthog/table-append` on the `incidents` table (now with optional `incident_io_id` column)                                                                                                                            |
| **Consults a runbook corpus on triage**    | `@posthog/memory-search` / `-read` over `runbooks/` (alert / system / procedure runbooks) — see [Runbook memory](#runbook-memory)                                                                                                               |
| **Proposes runbook updates for users**     | `@posthog/memory-write` / `-update`, **approval-gated** — queues the change and links the user to approve it                                                                                                                                    |
| Follows a structured triage flow           | `skills/triage-playbook/SKILL.md`                                                                                                                                                                                                               |
| Follows a consistent Slack message format  | `skills/slack-thread-protocol/SKILL.md`                                                                                                                                                                                                         |
| Follows a consistent incident.io flow      | `skills/incident-io-playbook/SKILL.md`                                                                                                                                                                                                          |
| Knows how to build good memory             | `skills/runbook-memory/SKILL.md`                                                                                                                                                                                                                |
| **incident.io as an agent-level MCP**      | `mcps[incident-io]` with `connection` — one shared incident.io credential the owner links once; every asker reuses it. Per-tool approval set per agent (`default_tool_approval` + overrides). See [MCP servers](#mcp-servers--two-auth-models). |
| **PostHog as a per-asker MCP**             | `mcps[posthog]` with `auth.provider: posthog` — each asker links their own PostHog identity and the agent acts AS them. See [MCP servers](#mcp-servers--two-auth-models).                                                                       |

## What it cannot do

- Take **any** remediation action. No restarts, no scaling, no
  rollbacks. Output is information only.
- Query Grafana dashboards or run `kubectl` directly. Asks a human
  for screenshots / `kubectl` output when needed.
- Page anyone. Surfaces who to `cc` and lets a human decide.

## Bundle layout

```text
sre-slack-bot/
├── README.md                              # this file
├── spec.json                              # AgentSpec — triggers, tools, skills, limits
├── agent.md                               # system prompt
└── skills/
    ├── triage-playbook/SKILL.md           # how to investigate
    ├── slack-thread-protocol/SKILL.md     # how to reply in Slack
    ├── incident-io-playbook/SKILL.md      # how to work incident.io through its MCP
    └── runbook-memory/SKILL.md            # the runbook corpus: taxonomy, quality bar, approval-gated writes
```

## Runbook memory

Beyond the tabular `incidents` table (fast "signature → outcome"
lookups), the bot maintains a **runbook corpus** in prose memory
(`@posthog/memory-*`). This is the institutional knowledge that makes
it faster over time — it consults the corpus at the start of triage
and proposes additions after a resolution.

Three folders, each a distinct job (full detail in the
[`runbook-memory`](skills/runbook-memory/SKILL.md) skill):

```text
runbooks/
├── alerts/<signature>.md      # what to do when a specific alert fires (grows per incident)
├── systems/<area>.md          # how a subsystem works — architecture, deps, dashboards, owners
└── procedures/<task>.md       # reusable ops procedures (rollback, scale, drain)
```

**Reads are open; writes are gated.** `@posthog/memory-search` /
`-list` / `-read` need no approval. `@posthog/memory-write` /
`-update` are **approval-gated** (`type: "agent"`,
`allow_edit: true`): when the bot proposes a runbook change it gets a
synthetic `queued` envelope back instead of a write, surfaces the
`approval_url` to the user, and the change only lands once a human
approves (and optionally edits) it. The bot curates runbooks **on
behalf of** the team — a person signs off on what enters the corpus.
This is the same gate the [agent-approval-demo](../agent-approval-demo/)
bundle showcases, applied to a real curation loop.

## MCP servers — two auth models

The bundle declares two MCP servers under `spec.mcps[]`, one of each auth
model, so this bot doubles as the reference for **how an agent reaches an MCP**.
Open them in the agent config UI (`mcps` → `incident-io` / `posthog`); each
renders differently and the in-UI descriptions spell out the setup.

### `incident-io` — agent-level (one shared connection)

```jsonc
{
  "id": "incident-io",
  "url": "https://mcp.incident.io/mcp",
  "connection": "00000000-…",
  "default_tool_approval": "approve",
}
```

The owner connects incident.io **once** (OAuth incl. dynamic client
registration, or an API key) and stores it as a native MCP connection;
**every asker reuses that one credential** and never signs in. The agent acts
as a single team/service identity.

- **Set it up:** open the `incident-io` MCP in the config UI → pick (or
  "Connect new") a connection. The shipped spec points at a placeholder
  connection id, so a fresh project shows _"Referenced connection isn't in this
  project — reconnect it or pick another."_ Connect incident.io once and select
  it; from then on it's shared.
- **Tool permissions are per agent, right here:** a connection-wide default
  (`default_tool_approval`, here `approve` = ask before every call) plus
  per-tool overrides (allow / approve / deny). The runner loads the shared
  bearer from the connection row and applies these. This is the **only** way
  the bot touches incident.io — `incident_list` / `incident_show` /
  `incident_update` / `incident_create` are the typed runtime tools, so e.g.
  "open new incident" (`incident_create`) can be marked `approve` (or `deny`)
  right on the agent.

### `posthog` — principal-level (per-asker identity)

```jsonc
{ "id": "posthog", "url": "http://localhost:8787/mcp", "auth": { "provider": "posthog" } }
```

References the `posthog` entry in `identity_providers[]`. There is **no shared
credential** — **each asker authenticates as themselves** the first time they
hit a tool that needs it (an auth-required link is surfaced; they complete the
OAuth and the agent then acts AS that user). Use it when the agent must act as
the person asking — querying PostHog as the requesting user.

|             | `incident-io` (agent-level)                | `posthog` (principal-level)                   |
| ----------- | ------------------------------------------ | --------------------------------------------- |
| Credential  | one shared, owner connects once            | per-asker, each links their own               |
| Acts as     | a team/service identity                    | the individual asking                         |
| Setup       | owner picks a connection in the UI         | declare a provider; askers OAuth on first use |
| Tool gating | `default_tool_approval` + per-tool `level` | (per the tool's own approval)                 |

## Prerequisites for deploying

Two secrets, one MCP connection, two webhooks. The recommended way to
set the secrets is the **Agent Builder walkthrough** below, which uses
the console's `set_secret` punch-out so the values never transit the
model's tool-call history. The list:

1. **Your own Slack app** registered at api.slack.com — see "Slack
   setup" below. Two values flow from this:
   - `SLACK_BOT_TOKEN` (the `xoxb-…` token) — used as `Authorization:
Bearer ${SLACK_BOT_TOKEN}` on every Slack Web API call.
   - `SLACK_SIGNING_SECRET` — the signing secret from your Slack
     app's "Basic Information" page. Required by the slack trigger
     to verify event payloads.
2. **Connect the incident.io MCP once.** Open the `incident-io` MCP in
   the agent config UI and pick (or "Connect new") a connection — OAuth
   or an API key. This is an agent-level connection: connect it once and
   every asker reuses it; the MCP carries its own auth, so there's no
   per-deploy incident.io secret to set. The shipped spec points at a
   placeholder connection id, so a fresh project shows _"Referenced
   connection isn't in this project"_ until you connect. See
   [MCP servers](#mcp-servers--two-auth-models).
3. **`spec.triggers[].slack.trusted_workspaces`** updated from the
   placeholder `T0XXXXXXX` to your actual Slack team id.
4. **A webhook shared secret.** The bundle's `spec.auth.modes`
   includes `{ type: "shared_secret", header: "X-Webhook-Secret" }`
   — incident.io, Grafana alertmanager, and anything else POSTing to
   `/webhook` must send this exact value in the `X-Webhook-Secret`
   header. Set it via the Agent Builder punch-out (no env var needed —
   the value is stored as a shared-secret integration on the agent
   and matched by the ingress per request). Without it the webhook
   401s, which is what we want; the chat / MCP paths still work via
   PAT.
5. **PostHog API access** for `@posthog/query` — the standard
   team-level token, no special scopes.

## Agent Builder walkthrough — recommended setup flow

This bundle is the showcase example for the
[agent-builder](../agent-builder/) flow. End-to-end, from a
fresh PostHog org:

1. **Open the agent console** at `console.agents.posthog.com`,
   start a chat with the Agent Builder.
2. **Ask the Agent Builder to clone this bundle.** Something like:
   _"Build me an SRE triage bot — clone from the sre-slack-bot
   reference, replace the placeholder Slack workspace id with
   `<T0YOUR>`, and walk me through setting the secrets."_
   The Agent Builder resolves to `agent-applications-revisions-clone-from-create`
   pointing at this bundle, edits `spec.triggers[].slack.trusted_workspaces`
   via `agent-applications-revisions-partial-update`, and freezes the
   draft.
3. **Punch out for each secret.** The Agent Builder calls
   [`set_secret`](../agent-builder/spec.json) twice — once
   for `SLACK_BOT_TOKEN`, once for `SLACK_SIGNING_SECRET`. Each call
   renders an inline form in the console; paste the value, hit save.
   Values are encrypted via the `agent-applications-set-env-create`
   API; the Agent Builder sees only `{ key, action: "set" }`. (incident.io
   has no secret here — connect its MCP once in the config UI, per the
   prerequisites above.)
4. **Promote.** The Agent Builder calls
   `agent-applications-revisions-promote-create`. Promote is
   approval-gated (see the Agent Builder's spec) so you approve it
   inline; this is the safety net against the Agent Builder promoting
   uninitiated.
5. **Read back the public endpoints.** The agent-retrieve response
   includes `slack_events_url` / `slack_interactivity_url` /
   `webhook_url` derived from `AGENT_INGRESS_PUBLIC_URL`. The
   Agent Builder surfaces these in chat — paste them into your Slack
   app's Event Subscriptions page and incident.io's webhook config
   respectively.
6. **Smoke-test.** `@mention` the bot in a test Slack channel; it
   should react with `:eyes:` and reply. **DM the bot** from its
   Messages tab (enabled by `allow_direct_messages`) and confirm it
   answers in the 1:1 — a follow-up DM continues the same session
   until it goes idle. Fire a synthetic incident.io webhook
   (`curl <webhook_url> -d @sample.json`) and confirm a timeline
   update lands on the test incident.

The point of doing this through the Agent Builder — rather than the
janitor REST API below — is that every step is gated, logged, and
takes the user's principal. The "raw" path is fine for CI and
scripted deploys; the Agent Builder path is the one to demo.

### Local-dev variant

Wire `bin/agent-tunnel` (Cloudflare Tunnel) to expose your local
agent-ingress publicly:

```bash
./bin/agent-tunnel               # prints e.g. https://random.trycloudflare.com
export AGENT_INGRESS_PUBLIC_URL=https://random.trycloudflare.com
./bin/start                       # restart so Django picks up the env
```

`AGENT_INGRESS_PUBLIC_URL` makes the agent-retrieve response echo
the tunnel-prefixed `slack_events_url` / `webhook_url`, so the
Agent Builder can read those back to you without you having to splice
the hostname by hand.

### A note on auth

`spec.auth.modes` is `[{ type: "posthog_internal" }, { type: "pat" }]` —
closed by default. Direct chat / run requests from outside the platform
will 401 unless the caller presents a PostHog PAT (the console + MCP do
this transparently via the connected user's principal).

> **About `public`.** Public exposure is opt-in and intentionally noisy:
> the schema requires `{ type: "public", acknowledge_public_exposure: true }`
> and the Agent Builder will pause to confirm before adding it. Real
> auto-trigger paths (Slack signing secret, incident.io webhook secret,
> Grafana alertmanager shared secret) verify the request before any
> handler runs, so the agent itself never needs `public` to receive
> alerts — only a genuinely-anonymous chat endpoint (docs embed,
> marketing bot) does.

## Deploying

Through the authoring MCP (preferred):

```text
# In an MCP-aware client (Claude Desktop, Claude Code, MCP Inspector):
agent-applications-create slug=sre-slack-bot name="SRE triage bot"
agent-applications-revisions-create application_id=<id>
# upload bundle files via agent-applications-revisions-bundle-put
agent-applications-revisions-spec-patch revision_id=<rid> spec=<contents of spec.json>
agent-applications-revisions-freeze revision_id=<rid>
agent-applications-revisions-promote revision_id=<rid>
```

See [`docs/local-dev.md`](../../../../../docs/local-dev.md)
§"Local MCP — end-to-end via an MCP client" for the full flow.

Directly via the janitor's REST API:

```bash
# Substitute <janitor-url>, <application-id>, etc.
curl -X POST <janitor-url>/revisions \
  -H 'x-internal-secret: <secret>' \
  -d '{ "application_id": "<id>", "spec": <contents of spec.json> }'
# then bundle-put per file, freeze, promote.
```

## Regression test

[`services/agent-tests/src/cases/example-sre-bot.test.ts`](../../cases/example-sre-bot.test.ts)
loads this bundle from disk, deploys it through the e2e harness,
and drives a realistic alert flow with the faux model. Run with:

```bash
pnpm --filter @posthog/agent-tests test cases/example-sre-bot
```

## Gaps that constrain this version

Each one is a follow-up that would make the bot meaningfully more
useful:

- ~~**incident.io as a typed runtime MCP** rather than raw HTTP calls.~~
  **Done** — see [MCP servers](#mcp-servers--two-auth-models). The
  `incident-io` MCP is an agent-level shared connection with per-tool
  approval (`default_tool_approval` + overrides), so "open new incident"
  (`incident_create`) can be marked `approve` (or `deny`) right on the agent.
  This is the only path the bot uses to reach incident.io — there is no raw
  HTTP fallback.
- **Private-network MCP support (Grafana / k8s).** Public MCPs work
  today via the `kind: 'external'` McpRef;
  Grafana and Kubernetes typically aren't publicly reachable.
  Cloudflare Tunnel is the planned v1 path; `kind: 'tailscale'`
  is parked.
- **Runbook corpus retrieval** — `@posthog/http-request` works for a
  single URL but the bot needs an index over the whole runbook
  tree. Could mirror periodically into the `memory-*` store via a
  loader job; not yet built.
- **Dedicated `@posthog/logs` native tool.** Logs query through
  `@posthog/query` HogQL today; a typed wrapper around the `logs`
  table (with structured args for service / severity / time-window)
  would be cheaper for the model than spelling out HogQL each call.

## Tuning notes

- The system prompt is intentionally opinionated about formatting
  (`slack-thread-protocol.md`) — channel signal-to-noise matters
  more than terseness. Adjust per team taste.
- `reasoning: high` is set because the triage step benefits from
  long deliberation. If you're cost-sensitive, drop to `medium`
  and re-evaluate against real traffic.
- `limits.max_turns: 30` is generous; most healthy investigations
  finish in 5-10 turns. The higher cap protects against pathological
  loops (each turn still counts against `max_tool_calls` and
  `max_wall_seconds`).
