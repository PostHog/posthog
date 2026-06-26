# Skill — the agent platform mental model

Load this first when you are explaining a structural concept to a
user, or when you catch yourself unsure what one of `spec`,
`bundle`, `revision`, `trigger`, `principal` actually means.

## The core nouns

An **agent application** (slug e.g. `weekly-digest`) is the
durable identity. Slugs are unique per project, human-readable,
url-safe. The application carries its `name`, `description`,
`live_revision_id`, and the team's encrypted env block.

A **revision** is one specific version of the agent — its spec and
its bundle, frozen together. Revisions are immutable once frozen.
Every production change is a new revision.

A revision moves through a small state machine:

```text
draft → ready → live → archived
```

- **draft** — mutable. Spec + bundle can be edited piecewise.
  Created via `revisions-create` (empty) or `revisions-new-draft-create`
  (branch from live) or `revisions-clone-from-create` (branch from
  any revision).
- **ready** — `freeze-create` stamps `bundle_sha256` and locks the
  revision. No further edits.
- **live** — `promote-create` flips this revision to live, archives
  whatever was live before. Only one live revision per application
  at a time.
- **archived** — terminal. Sessions started on this revision still
  finish, but no new triggers route here.

A **spec** (`AgentSpec`, in `services/agent-shared/src/spec/spec.ts`)
is the structural/queryable layer of a revision. Lives as JSONB on
the revision row. It declares:

- `model` — provider/model id
- `triggers[]` — which surfaces invoke the agent (`chat`, `webhook`,
  `slack`, `cron`, `mcp`)
- `tools[]` — what the agent can call (native / custom / client)
- `mcps[]` — runtime MCP servers the agent connects to at session
  start (these expose remote tools)
- `skills[]` — markdown skills the model can load on demand
- `secrets[]` — names of encrypted env keys the agent uses
- `limits` — per-session caps (`max_turns`, `max_tool_calls`,
  `max_wall_seconds`)
- `auth` — per-trigger (`triggers[].auth`); how a connecting client
  authenticates
- `reasoning` — provider-specific thinking level (`minimal` → `xhigh`)

This is the conceptual map. For the exact field shapes, enums, and
defaults, don't guess — run a candidate spec through
`posthog__agent-applications-revisions-validate-create` and read its
errors, and cross-check tool ids against
`posthog__agent-native-tools-list`. Those reflect what the API actually
validates against, not this prose.

A **bundle** is the content layer of a revision. A filesystem-like
tree stored in S3, with a manifest in Postgres. Always contains
`agent.md` (the system prompt). Usually contains `skills/*.md` and
sometimes `tools/*/source.ts` for custom tools.

A **session** is one invocation of one revision — one trigger
firing, one principal, one conversation, one finite lifetime.
Sessions hold the conversation log, the tool-call log, the events
emitted, the cost / token usage, and a `state` (`queued`, `running`,
`completed`, `closed`, `cancelled`, `failed`).

A **principal** is the identity acting through the session. For a
chat session opened by a human via OAuth, that's the human's user
id. For a webhook session, it's the webhook trigger's allowlisted
identity. For a slack session, it's the Slack user resolved through
the team's slack integration.

## How a request becomes a session

1. A trigger fires (`/agents/<slug>/run` for chat, alertmanager POST
   for webhook, Slack event for slack, scheduler tick for cron, MCP
   `tools/call` for mcp).
2. Ingress resolves auth against `spec.auth`, builds a
   `SessionPrincipal`, persists a new session row, enqueues.
3. A worker picks the session up, opens any `spec.mcps[]` clients,
   acquires a sandbox if there are custom tools, renders the system
   prompt (framework preamble + `agent.md` + skill index), runs the
   model loop.
4. Tool calls dispatch to native / custom / MCP / client (per their
   `kind`); each result feeds back into the next turn.
5. Session ends when the model calls `meta-end-session`, the wall
   clock runs out, `max_turns` is hit, or the model errors
   irrecoverably.

## How spec / bundle / sessions cross-reference

Read this whenever you find yourself reaching for "where does the
agent's prompt live?" or "where do I edit the model?":

- The **model** is in `spec.models` (auto level or manual
  list). Edit via `revisions-partial-update` on a draft.
- The **system prompt** is `bundle/agent.md`. Edit via
  `revisions-agent-md-update`.
- The **skills the model can load** are listed in `spec.skills[]`
  (id + path + description). The bodies live in `bundle/skills/*.md`.
- A **session's conversation** is on the session row (via
  `sessions-retrieve`). Not in the bundle — the bundle is the agent,
  not the agent's history.
- The **rendered system prompt** for a specific revision is fetched
  via `revisions-system-prompt`. Use this when you need to debug
  what the model actually saw.

## Triggers — what each one expects

| Trigger   | How it's invoked                                       | Identity model                                                                   |
| --------- | ------------------------------------------------------ | -------------------------------------------------------------------------------- |
| `chat`    | `POST /agents/<slug>/run`                              | Auth per `spec.auth`. Principal carries through.                                 |
| `webhook` | `POST /agents/<slug>/webhook`                          | Optional `secret` in spec. Principal is the webhook trigger itself.              |
| `slack`   | Slack Events API → ingress slack adapter               | Workspace must be in `trusted_workspaces`. Principal is the resolved Slack user. |
| `cron`    | Scheduler tick                                         | No external identity — principal is a synthetic `system:cron`.                   |
| `mcp`     | MCP JSON-RPC `tools/call` against `/agents/<slug>/mcp` | Auth per `spec.auth`. `Mcp-Session-Id` header scopes resources/list.             |

## Tools — three classes, three call sites

This is the most common source of confusion. Be precise.

| Class                 | Spec ref                                           | Where it runs            | Examples                                                                 |
| --------------------- | -------------------------------------------------- | ------------------------ | ------------------------------------------------------------------------ |
| **Native**            | `{ kind: "native", id: "@posthog/foo" }`           | In the runner process    | `@posthog/query`, `@posthog/http-request`, `@posthog/slack-post-message` |
| **Custom**            | `{ kind: "custom", id, path: "tools/x/" }`         | In a per-session sandbox | Anything the team writes themselves                                      |
| **MCP** (`spec.mcps`) | Not in `tools[]` — listed in `spec.mcps[]` instead | In a remote MCP server   | Anything any MCP exposes. Routed by prefix `<id>__<name>`.               |
| **Client**            | `{ kind: "client", id, description, args_schema }` | In the connecting client | `focus_revision`, `focus_session`, `focus_file`, `toast`                 |

Native tools are catalogued via `posthog__agent-native-tools-list`. MCP
tools are discoverable per server via the MCP `tools/list` call
made at session start. Client tools are declared in the spec; the
connecting client opts into the subset it implements.

## Skills — load-on-demand markdown

Every entry in `spec.skills[]` becomes one line in the system
prompt's skill index — `- <id>: <description>`. The model decides
whether to call `@posthog/load-skill` based on the description.

The skill body is in the bundle at the declared `path`. Skills can
be short (a few hundred lines) because the platform pays for them
only when loaded. Push depth into skills, keep `agent.md` lean.

Store skills are canonical. To edit a skill's body, use `skill-update`
(PATCH) and manage its bundled files with `skill-file-create` /
`skill-file-delete` / `skill-file-rename` — the inline
`skills/<id>/SKILL.md` you see in a revision's bundle is a snapshot,
not the editable source. Reference a store skill from a revision with
`agent-applications-revisions-skill-refs-set`; browse and read store
skills via `skill-list` / `skill-get`.

## Secrets and remote credentials

- **Secrets** (`spec.secrets[]`) are per-application encrypted env
  values the agent uses (e.g. a specific Stripe API key). Set via
  the punch-out flow — you never see the value.
- For a remote service the agent talks to, connect an MCP server and
  reference it with `mcps[].connection` (one shared credential the
  owner connects once), or wire an `identity_providers[]` entry for
  per-asker OAuth. There is no team-wide `integrations[]` spec field.

When you curate a connection-based MCP's per-agent tool permissions
(`spec.mcps[].tools[].level` + `default_tool_approval`), FIRST call
`mcp-connection-tools-list` with the connection id (discover ids via
`mcp-connections-list`) to load that connection's REAL tool names.
Never guess tool names from a past session or from skill prose — the
catalog is the only authority for what the server actually exposes.

## Revisions vs sessions — the lifetime distinction

A revision is a static artifact — the agent definition. A session
is a single invocation against one revision. Revisions live
forever (just `archived`); sessions live for minutes to hours and
are subject to the per-revision `limits`.

When the user asks "why is the agent doing X?" the answer is
almost always in a session's event log. When they ask "why is the
agent set up to do X?" the answer is in the revision's spec or
bundle. Don't mix them up.
