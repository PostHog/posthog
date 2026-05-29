# Design — the agent concierge

**Status:** draft. **Owner:** ben.

> The console plan ([`agent-console-website.md`](agent-console-website.md))
> names a "concierge agent" and treats it as the canonical edit
> surface. This doc is the concierge itself — what it is, how it's
> deployed, what skills + tools it carries, how auth works in both
> the console and direct-MCP shapes, and what platform pieces are
> still missing for it to do a great job.

The reference bundle ships at
[`services/agent-tests/src/examples/agent-concierge/`](../../../services/agent-tests/src/examples/agent-concierge/).

## 1. What it is

A **single deployed agent** (`slug: agent-concierge`) that lives in
PostHog's primary org and is the best-in-class operator / author /
debugger for **every other agent on the platform**. One concierge,
many surfaces:

| Surface           | How it's reached                                                                                            | Principal                                                                                   |
| ----------------- | ----------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| **Agent console** | The `<AgentChat />` dock embeds it on every page; opens a chat session against the concierge's chat trigger | The signed-in user (OAuth-derived session principal, per `per-session-access-elevation.md`) |
| **MCP (direct)**  | `https://<concierge-slug>.agents.posthog.com/mcp` — paste the snippet into Claude Code / Cursor / Inspector | A PostHog PAT the user attaches in their MCP client config                                  |
| **Slack (later)** | `@concierge what's wrong with weekly-digest?` — when the integration is configured for a workspace          | The Slack user resolved through the `slack` integration                                     |

It is **a regular agent on the platform**. Same revision lifecycle,
same bundle layout, same MCP-served authoring surface. PostHog ships
and maintains the canonical revision; customers who want to extend it
(extra review steps, custom internal links) fork the bundle.

## 2. Why a single agent (not one per surface)

The "concierge in the console" and the "concierge in your IDE" are
the same job: **understand, debug, and edit an agent on behalf of
the user**. The only thing that changes between surfaces is:

- Which client tools the connecting client implements (`ui/focus` in
  the browser, none over plain MCP).
- Which trigger fired (chat vs MCP `ask` tool).
- Whose principal is on the wire.

The concierge is written defensively for all three (per the client
opt-in handshake in [`agent-console-website.md`](agent-console-website.md)
§8.3) — when a client doesn't handle `@posthog/ui/focus` it falls back
to spelling out where it went in text. Same agent, different render.

## 3. Auth model — PostHog OAuth all the way down

Both entry points resolve to the same thing: the agent runs **as the
user**, not as PostHog's org. This is non-negotiable for audit and
blast-radius reasons.

### 3.1 Console flow

1. User logs into `console.agents.posthog.com` via PostHog OAuth (the
   existing `services/oauth-proxy/` flow).
2. The console opens an `<AgentChat />` session against
   `agents.posthog.com/agents/agent-concierge/chat` and attaches a
   `principalToken` minted from the OAuth session.
3. The runner threads the user-principal through every MCP / tool
   call the concierge makes. Activity log shows the **user** acting,
   not the concierge.

### 3.2 MCP flow

1. User runs `GET /agents/agent-concierge/mcp/connect-info` (or asks
   the agent console for the snippet) and pastes the config into
   Claude Code / Cursor.
2. The MCP transport requires `Authorization: Bearer phx_*` against
   `spec.auth.mode: pat`. The user's PostHog PAT carries their
   identity + scopes.
3. The runner resolves the PAT to a principal once at session start
   and threads it through identically to the console flow.

### 3.3 What the concierge sees

It never sees the user's raw PAT or OAuth token. It receives a
**session principal token** the runner mints — opaque from the
agent's perspective, accepted by the PostHog authoring MCP as proof
of user identity + scope.

This means: **the concierge can read and write everything the user
themselves can, and nothing more.** A read-only OAuth scope → the
concierge can inspect but not promote. A team-admin scope →
promote, set env, archive.

## 4. The tool surface

| Kind   | Tool                                                                                      | What the concierge does with it                                                                                                                                      |
| ------ | ----------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| MCP    | `agent-applications-list` / `-retrieve` / `-revisions-*` / `-sessions-*` / `-approvals-*` | The bulk of the work. Reading bundles, listing sessions, diffing revisions, kicking off test runs, fielding approvals — all flow through the existing authoring MCP. |
| MCP    | `agent-native-tools-list`                                                                 | Catalog the building blocks when the user is authoring something new                                                                                                 |
| Native | `@posthog/query`                                                                          | Run LLM-analytics + session-event queries for the cost / failure-rate / volume views                                                                                 |
| Native | `@posthog/web-fetch`                                                                      | Pull runbooks, third-party docs (Slack API ref, Anthropic API ref, etc.) when explaining something the user doesn't know                                             |
| Native | `@posthog/load-skill`                                                                     | Auto-included; loads the deep skills on demand                                                                                                                       |
| Client | `@posthog/ui/focus`                                                                       | Drives the console's view as the agent narrates ("I just opened revisions/abc, see panel left")                                                                      |
| Client | `@posthog/ui/toast`                                                                       | Quiet status notifications when a long-running tool is in flight                                                                                                     |
| Meta   | `ask-for-input`, `end-turn`, `end-session`                                                | Standard control-flow                                                                                                                                                |

Two layers of distinction that matter for the spec:

- **Native tools** run server-side in the runner.
- **MCP tools** are remote tools the runner connects to at session
  start ([`runtime-mcps.md`](runtime-mcps.md)). The PostHog authoring
  MCP is the single MCP the concierge declares — every
  `agent-applications-*` call is a routed MCP tool call.
- **Client tools** are dispatched back to the connecting client over
  SSE and fulfilled in-browser ([`agent-console-website.md`](agent-console-website.md) §8).

## 5. The MCP surface the concierge exposes

Per [`agent-as-mcp-server.md`](agent-as-mcp-server.md), every agent
with the `mcp` trigger gets an `ask` tool free. The concierge also
declares curated tools so a Claude Code session can call them
typed:

```jsonc
{
  "mcp": {
    "tools": [
      {
        "name": "inspect_agent",
        "description": "Summarize an agent's purpose, tool surface, recent session health, and any obvious risks. Use as the first call when a user asks 'what does X do?' or 'is X healthy?'.",
        "input_schema": {
          "type": "object",
          "properties": { "slug": { "type": "string" } },
          "required": ["slug"],
        },
        "prompt_template": "Inspect the agent with slug {{ slug }}. Produce a structured summary (purpose, triggers, tools, recent failures, recommended next actions).",
      },
      {
        "name": "debug_session",
        "description": "Diagnose a failed or anomalous session — read its events, classify the failure, propose a fix.",
        "input_schema": {
          "type": "object",
          "properties": { "session_id": { "type": "string" }, "agent_slug": { "type": "string" } },
          "required": ["session_id"],
        },
        "prompt_template": "Debug session {{ session_id }} on agent {{ agent_slug }}. Read the full event log, identify what went wrong, and produce a structured root-cause summary.",
      },
      {
        "name": "audit_team_agents",
        "description": "Sweep every agent in the team and surface health / cost / drift concerns. Use for a periodic review.",
        "input_schema": { "type": "object", "properties": {} },
        "prompt_template": "Audit every agent application in the current team. For each: state (healthy / drifting / failing), 7d cost trend, 7d session count, top failure category if any. Surface the top 3 things the team should act on.",
      },
    ],
  },
}
```

(Pending — `spec.mcp.tools[]` is the v1 work in
[`agent-as-mcp-server.md`](agent-as-mcp-server.md) §7. Today the
concierge's MCP exposes the default `ask` tool only.)

## 6. The bundle layout

```text
services/agent-tests/src/examples/agent-concierge/
├── README.md                                # deploy + status + gaps
├── spec.json                                # AgentSpec
├── agent.md                                 # short system prompt; defers to skills
└── skills/
    ├── platform-mental-model.md             # agents, revisions, bundles, lifecycles
    ├── reading-an-agent.md                  # inspect, summarize, explain
    ├── debugging-sessions.md                # event-log reading, failure taxonomy
    ├── editing-agents-safely.md             # draft → validate → freeze → promote
    ├── authoring-new-agents.md              # full creation flow (mirrors agent-authoring-flow.md §6)
    ├── secrets-and-integrations.md          # punch-out flow, integrations table
    ├── designing-mcp-surfaces.md            # spec.mcp.tools[] design rules
    ├── running-and-evaluating-tests.md      # test runs + judge skills
    ├── using-the-console-ui.md              # @posthog/ui/focus + toast etiquette
    ├── working-outside-the-console.md       # MCP / IDE mode; no client tools
    ├── cost-and-quota-analysis.md           # LLM analytics views the concierge can build
    └── safety-and-boundaries.md             # things the concierge MUST NOT do
```

Each skill is a few hundred lines max, fits in one short read, and
the `description` in `spec.skills[]` is the only signal the model
gets about when to load it. The descriptions get tuned harder than
the bodies.

## 7. The system prompt (`agent.md`) — what stays at the top

The framework preamble + `agent.md` are the only thing in the model's
context for every turn. Skills load on demand. So `agent.md` carries:

1. **Identity + frame.** "You are the agent concierge. The user is
   either in the agent console (browser, has `ui/focus`) or in an MCP
   client (terminal, no UI). Detect which from the session and adapt."
2. **The three modes.** Inspect / Debug / Edit. Each one has a
   matching skill — load it when the user's intent matches.
3. **Hard rules.** What it must never do (raw secrets, unprompted
   promotion, edits without user confirmation, hallucinated tool
   ids).
4. **The acknowledgement contract.** Every user message gets a
   one-line "what I'm about to do" before any tool call. With
   `ui/focus`, also pre-focus the resource you're about to read
   from so the user sees what you see.
5. **Tone.** Direct, concrete, evidence-cited. Same calibration as
   the SRE bot — no hedging, no fluff, name specific files / ids.

The deep "how to triage a failing session" or "how to write a
custom tool schema" lives in skills, not in `agent.md`. We pay for
`agent.md` on every turn; skills only on the turns that need them.

## 8. Gaps blocking the v0 concierge

Ordered roughly by blast-radius (top = biggest unlock per unit of
work).

### 8.1 Client-fulfilled tools (`kind: "client"`)

**Status:** designed in [`agent-console-website.md`](agent-console-website.md)
§8, not implemented.

**Why it matters:** without `@posthog/ui/focus` the concierge is a
text-only chat box that talks about navigating but can't drive the
view. The whole "the agent shows you what it's looking at" UX
disappears.

**What's needed:**

- Add `kind: "client"` to `ToolRefSchema` (and `from_native` /
  inline-id variants).
- Build the runner-side dispatch path: `client_tool_call` SSE event
  - `/sessions/<id>/client_tool_result` POST + per-call timeout +
    16 KiB cap on args/result.
- Build the well-known registry for `@posthog/ui/*` tools (`focus`,
  `toast` for v0). Schema lookup parallels the native tool catalog.
- Build the client handshake — `client.handles[]` reconciliation
  with spec at session open.
- Ship the React handlers in `@posthog/agent-chat` for the
  well-known set.

### 8.2 Runtime MCP support (`spec.mcps[]`)

**Status:** schema exists in `services/agent-shared/src/spec/spec.ts`,
runner doesn't read it. Designed in [`runtime-mcps.md`](runtime-mcps.md).

**Why it matters:** the concierge's entire job is calling
`agent-applications-*` tools. If runtime MCPs don't work, the
concierge has nothing to do.

**What's needed:**

- Open one MCP client per `spec.mcps[]` entry at session start; close
  on `release`. Open in parallel.
- Tool prefix routing (`<mcp_id>__<tool_name>`).
- OAuth-passthrough auth (v2 in the runtime-mcps plan) — needed so
  the concierge passes the user's PAT through to the PostHog MCP,
  not a per-agent secret.

### 8.3 Session principal threading (OAuth → user-principal-on-tool-calls)

**Status:** designed in
[`per-session-access-elevation.md`](per-session-access-elevation.md) +
[`agent-console-website.md`](agent-console-website.md) §7.1.

**Why it matters:** the security guarantee that "the concierge can
only do what the user can do" depends on the runner threading the
session's principal through every MCP / tool call. Without it the
concierge would have to hold a fallback credential, which is the
custody risk we explicitly want to avoid.

**What's needed:**

- Mint short-lived session-principal tokens from OAuth (15 min) on
  the console side.
- Accept the principal as a `chat` trigger field at session open;
  store on the session row.
- Plumb the principal into the MCP client request headers when
  calling out to the PostHog authoring MCP.

### 8.4 The `agent-applications-revisions-validate` endpoint

**Status:** listed as `enabled: true` in
[`agent_stack.yaml`](../../../services/mcp/definitions/agent_stack.yaml)
but the underlying Django action is a stub.

**Why it matters:** the concierge would gate every freeze on a
validate call. Without it, freezes go out broken and the user finds
out at runtime — exactly the loop the authoring flow promises to
remove.

**What's needed:** wire the validator to actually parse spec against
`AgentSpecSchema`, walk skill / tool references, surface a
structured `{ ok, errors, warnings }`. See
[`agent-authoring-flow.md`](agent-authoring-flow.md) §3 phase 4.

### 8.5 Test runs (`agent-applications-revisions-test-run` + results)

**Status:** designed in
[`agent-authoring-flow.md`](agent-authoring-flow.md) §5, not built.

**Why it matters:** the concierge cannot say "I tested my edit and
it works" without a sandboxed re-run path. Today the only way to
test is to promote-then-pray.

**What's needed:** the `is_test=true` session column + egress
sandbox + test spec schema + assertion runner + the three new MCP
verbs. See §5 of the authoring-flow plan.

### 8.6 Secrets punch-out flow

**Status:** designed in
[`agent-authoring-flow.md`](agent-authoring-flow.md) §3 phase 3, not
built.

**Why it matters:** the concierge cannot help with "add a new
secret" without this. Today the only way to set a secret is to
`POST /agent-applications/<id>/set-env` with the raw value in the
body — exactly what the concierge must not see.

**What's needed:** the issue-write-token + status MCP verbs, plus
the `/agents/<slug>/secrets?token=...` PostHog UI form.

### 8.7 Revision diff

**Status:** not designed; mentioned as a stretch goal in
[`agent-console-website.md`](agent-console-website.md) §6 ("Diff against live").

**Why it matters:** "what changed between live and this draft" is
the #1 reviewer question. The concierge can do this synthetically
today by reading two manifests + diffing in-context, but it's
expensive in tokens. A first-class `agent-applications-revisions-diff`
MCP verb would let the concierge surface a clean diff in O(1) MCP
calls.

### 8.8 Live session SSE tail over MCP

**Status:** the SSE bus exists (`RedisSessionEventBus` +
`/listen/<id>`), but there's no MCP wrapper.

**Why it matters:** the concierge debugging a live session today
has to poll `agent-applications-sessions-retrieve`. With an MCP
streaming verb (or a `resources/subscribe` per
[`agent-as-mcp-server.md`](agent-as-mcp-server.md) §7 v2) the
concierge could tail in real time and surface "the agent just
called `@posthog/slack-post-message` with args X" as it happens.

### 8.9 The judge-skill convention

**Status:** mentioned in
[`agent-authoring-flow.md`](agent-authoring-flow.md) §5 + open
question §4.3, not designed in detail.

**Why it matters:** the concierge's self-evaluation loop ("does the
agent I just edited still pass its tests?") is much stronger if
there's a canonical "judge agent" pattern it can invoke. Otherwise
every concierge install reinvents grading.

**What's needed:** a judge-skill template + a convention for
calling it from the concierge ("here's a test run id, grade it
against rubric R"). The judge could itself be a deployed agent,
which is the nicest dogfooding.

## 9. Ideas that aren't in v0 but should be on the roadmap

### 9.1 Cross-agent comparison view

"Why is `weekly-digest` 3x more expensive than `daily-digest`?" The
concierge runs LLM-analytics queries scoped to both agents, surfaces
side-by-side token usage, tool-call mix, average turns. Today
requires the user to know which queries to run; this is exactly
what a concierge should do reflexively.

### 9.2 Agent-fleet health monitor (cron concierge)

A scheduled run of the concierge against every agent in the team —
fires nightly, posts a Slack summary or PostHog notification when an
agent's error rate crossed a threshold or its cost jumped. Same
agent, different trigger.

### 9.3 The concierge as judge

The judge skill convention (§8.9) could ship as a mode of the same
concierge — invoke it with a `judge_run({ test_run_id, rubric })`
MCP tool. One agent, two jobs; the rubric switches the prompt
context.

### 9.4 First-run onboarding mode

When the concierge detects a user has zero agents (`agent-applications-list`
returns empty), it switches to onboarding mode — explains the
platform, walks the user through deploying the example bot (e.g.
the SRE one), connects the dots between bundle + spec + revision +
session.

### 9.5 Skill library curation

A skill that teaches the concierge how to recognize "this skill is
reusable across agents" and proactively suggest promoting it to a
template (per [`skill-templates.md`](skill-templates.md), once that
ships). Helps the platform's shared-library compound over time.

### 9.6 Approval-queue triage

The concierge could surface "you have 7 approvals waiting in this
team, here's the one to look at first" by reading the pending
approvals list, classifying by risk, and ordering. Composes with
the inline-approval UI from
[`agent-console-website.md`](agent-console-website.md) §10.

### 9.7 Memory (per-team, persistent)

When [`agent-memory.md`](agent-memory.md) ships, the concierge
should be its #1 consumer — remember each team's idioms ("this
team always uses kebab-case slugs", "this team gates promotes on a
PR review"), each agent's known quirks ("this agent's first
hypothesis is always wrong, prompt it harder"). The concierge is
the natural shape to dogfood memory.

### 9.8 Co-edit mode

Two users editing the same agent at once — the concierge could
broadcast "Ben just changed `skills/research.md`, you may want to
refresh" via a third `@posthog/ui/*` well-known tool
(`@posthog/ui/peer_edit_warning`).

### 9.9 Replay-and-tweak

"Re-run session X with the new agent.md applied" — the concierge
takes a real session's inputs, runs them through a draft revision
in test mode, surfaces the diff in behavior. Massively shortens
the "did my edit fix the bug?" loop.

### 9.10 OSS / self-host reach

The concierge bundle is OSS — a self-hosted PostHog instance can
deploy it the same way. The only org-specific knob is the
authoring MCP URL. Worth keeping the bundle dependency-light so
forks stay sustainable.

## 10. Phasing

The reference bundle in `services/agent-tests/src/examples/agent-concierge/`
is shippable **today** (faux-tested in `agent-tests`) but its
production deployment depends on the gaps in §8.

| Slice                                                  | Lands when                                                                                                                                                    |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **v0 — read-only concierge in the console**            | §8.1 (client tools), §8.2 (runtime MCPs), §8.3 (OAuth principal threading). Concierge can inspect any agent, narrate, drive `ui/focus`. No writes.            |
| **v0.1 — edit through the concierge**                  | §8.4 (validate) + §8.6 (secrets punch-out). Concierge can branch a draft, surface a validate report, freeze + promote. No tests yet — high-trust path only.   |
| **v0.2 — tested edits**                                | §8.5 (test runs). Concierge gates every promote on a test run.                                                                                                |
| **v1 — MCP surface**                                   | `spec.mcp.tools[]` v1 lands in [`agent-as-mcp-server.md`](agent-as-mcp-server.md). Concierge exposes `inspect_agent` / `debug_session` / `audit_team_agents`. |
| **v1.1 — debugging power**                             | §8.7 (revision diff) + §8.8 (SSE tail over MCP). Concierge moves from polling to streaming.                                                                   |
| **v2 — judge mode**                                    | §8.9. Self-evaluation closes the authoring loop.                                                                                                              |
| **v2+ — roadmap items in §9** as the platform matures. |                                                                                                                                                               |

## 11. Why this is worth front-loading

The platform already has the building blocks. Without a flagship
agent that exercises them end-to-end — runtime MCPs, OAuth
principal, client tools, validate, tests, judge, MCP-curated
surface — each piece risks being shipped in isolation and never
proving it composes. The concierge is the integration test for the
whole authoring story, **and** the user-visible artifact that makes
the platform usable.

Building it now also forces the small platform gaps (§8.4–§8.8) out
of "designed" and into the implementation queue. They're individually
small; bundled behind the concierge they have a clear customer.

## 12. Related docs

- [`agent-console-website.md`](agent-console-website.md) — the
  read-mostly UI + chat dock that's the concierge's primary surface
- [`agent-authoring-flow.md`](agent-authoring-flow.md) — the MCP
  authoring contract the concierge calls
- [`agent-as-mcp-server.md`](agent-as-mcp-server.md) — how agents
  expose MCP; the concierge's external surface
- [`runtime-mcps.md`](runtime-mcps.md) — how the concierge calls
  the authoring MCP at runtime
- [`per-session-access-elevation.md`](per-session-access-elevation.md) —
  principal model the concierge inherits
- [`agent-memory.md`](agent-memory.md) — what the concierge
  remembers across sessions, once it lands
