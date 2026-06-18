# Agent concierge — the meta-agent for the platform

The "explain, debug, edit" assistant for every agent on the
PostHog agent platform. One deployment, three surfaces (agent
console chat dock, MCP from Claude Code / Cursor, future Slack),
all acting under the user's PostHog OAuth principal.

## Status

**Reference bundle.** Loadable, faux-testable, and deployable on the
current platform. The pieces this bundle leans on have shipped:
`kind: "client"` tool support is in the spec schema (and exercised by
the `focus_*` / `set_secret` entries), the runner opens the clients
declared in `spec.mcps`, and the `@posthog/agent-applications-*`
authoring surface is a set of native in-process tools resolved through
the registry.

## What it does

| Mode                     | Trigger                                                     | Primary skill             |
| ------------------------ | ----------------------------------------------------------- | ------------------------- |
| Inspect                  | "what does X do?" / "is X healthy?" / "show me Y"           | `reading-an-agent`        |
| Debug                    | "why did session Y fail?" / "X is broken" / "X did Z wrong" | `debugging-sessions`      |
| Edit                     | "change X" / "tweak the prompt" / "add a tool"              | `editing-agents-safely`   |
| Author                   | "build me a new agent that..."                              | `authoring-new-agents`    |
| Audit                    | "audit my team's agents" / "where's our cost going?"        | `cost-and-quota-analysis` |
| Fleet audit (on request) | user asks for a fleet-wide sweep                            | `auditing-the-fleet`      |

### The fleet audit

When the user asks for a fleet-wide sweep ("audit my agents" / "what's
underperforming?"), the concierge sweeps every agent in the team,
mines each one's recent sessions for failures / anomalies / degraded
behaviour, diagnoses root causes, and for each concrete fix branches
a **draft** revision with the change applied (validated, never frozen
or promoted — drafts are proposals a human reviews). The findings
land as a structured report in memory (`reports/fleet-audit/{date}.md`

- `latest.md`) and a condensed digest is optionally posted to the
  team's configured Slack channel.

The run is deliberately read-and-propose: the skill forbids
freeze / promote / archive / delete, leaving the validated drafts for
the user to review and promote themselves. See
[`skills/auditing-the-fleet/SKILL.md`](skills/auditing-the-fleet/SKILL.md).

**Operator config.** Slack delivery is opt-in: set
`config/fleet-audit.md` in the agent's memory with a
`slack_channel: C0XXXXXXX` line and set the agent's `SLACK_BOT_TOKEN`
secret. Without a channel the audit skips the post silently — the
memory report is the source of truth regardless.

For each mode, the concierge calls the same `agent-applications-*`
native tools that the authoring AI uses,
acting under the connected user's principal so every write shows
up in the activity log as **the user**, not as the concierge.

## Bundle layout

```text
agent-concierge/
├── README.md                            # this file
├── spec.json                            # triggers, tools, mcps, skills
├── agent.md                             # short system prompt; defers to skills
└── skills/                                       # one folder per skill, each with a SKILL.md
    ├── platform-mental-model/SKILL.md       # spec / bundle / revision / session
    ├── reading-an-agent/SKILL.md            # standard inspection flow
    ├── debugging-sessions/SKILL.md          # failure taxonomy + triage
    ├── editing-agents-safely/SKILL.md       # branch → validate → freeze → test → promote
    ├── authoring-new-agents/SKILL.md        # fresh creation flow
    ├── choosing-the-model/SKILL.md          # match model + reasoning to the job
    ├── secrets-and-integrations/SKILL.md    # punch-out flow, integrations table
    ├── designing-mcp-surfaces/SKILL.md      # spec.mcp.tools[] design
    ├── running-and-evaluating-tests/SKILL.md # tests + judge skills
    ├── setting-up-slack-app/SKILL.md        # Slack app creation + scopes
    ├── using-the-console-ui/SKILL.md        # focus_* + toast etiquette
    ├── working-outside-the-console/SKILL.md # MCP / IDE mode; no client tools
    ├── cost-and-quota-analysis/SKILL.md     # LLM analytics views
    ├── querying-ai-observability/SKILL.md   # $ai_* event contract + debug/improve queries
    ├── auditing-the-fleet/SKILL.md          # fleet-wide sweep (on request)
    └── safety-and-boundaries/SKILL.md       # hard rules
```

## Tool surface

| Class              | Tool                                                                                                                     | Class semantics                                                                                                                                                                                          |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Native             | `@posthog/agent-applications-*` (list, retrieve, revisions, sessions, logs + the draft edit + validate verbs)            | Read agent state — applications, revisions, sessions, logs — as the connected user. Routed through the credential broker; no platform credentials, no impersonation.                                     |
| Native (telemetry) | `@posthog/query`                                                                                                         | HogQL the agent's LLM-observability events (`$ai_generation` / `$ai_span` / `$ai_trace`) the runner captured into the team's project. Powers debug + improve evidence — see `querying-ai-observability`. |
| Native (audit I/O) | `@posthog/memory-search`, `@posthog/memory-read`, `@posthog/memory-write`, `@posthog/slack-post-message`                 | Durable outputs of a fleet audit — persist the report to memory, post the digest to Slack (reads the agent's own `SLACK_BOT_TOKEN`).                                                                     |
| Client             | `focus_tab`, `focus_file`, `focus_revision`, `focus_session`, `focus_spec_section`, `toast`, `get_context`, `set_secret` | Drive the console's read panel + read the user's current view. No-op outside the console.                                                                                                                |

## Auth model

Auth is configured **per trigger** — there is no top-level
`spec.auth`. Each of the concierge's triggers sets
`auth.modes: [posthog, posthog_internal]` (an array), so both entry
points map to the same effective auth:

1. **Console** — user logs into `console.agents.posthog.com` via
   PostHog OAuth, the console mints a short-lived session-principal
   token from the OAuth session, attaches it as the chat trigger's
   principal field. Every tool call runs as the user.
2. **MCP** — user attaches their PostHog PAT in their MCP client
   config. The runner resolves the PAT to a principal once at
   session start, threads it through identically.

The concierge holds no fallback credential.

## Platform pieces it relies on (all shipped)

These are platform-side, not bundle-side — and they're in place:

1. **`kind: "client"` tool support in the spec** — the spec schema
   accepts `kind: "client"`; the bundle's `focus_*`, `toast`, and
   `set_secret` entries parse and validate.
2. **Runtime MCP support** — the runner opens the clients declared in
   `spec.mcps` at session start. (The concierge declares none —
   `spec.mcps` is empty — because its authoring surface is native, not
   a remote MCP server.)
3. **OAuth principal threading** — the session principal threads
   through every tool call, so writes attribute to the user.
4. **The native authoring tools** — `@posthog/agent-applications-*`
   are native in-process tools resolved through the tool registry
   (not a separate MCP server), including the draft-edit + validate
   verbs the concierge uses.

## Deploying

Through the authoring MCP (preferred — same as other example bundles):

```text
agent-applications-create slug=agent-concierge name="Agent concierge"
agent-applications-revisions-create application_id=<id>
# write bundle resources via the granular per-resource tools:
#   agent-applications-revisions-agent-md-update / -skills-update / -tools-update
agent-applications-revisions-partial-update revision_id=<rid> spec=<contents of spec.json>
agent-applications-revisions-validate-create revision_id=<rid>
agent-applications-revisions-freeze-create revision_id=<rid>
agent-applications-revisions-promote-create revision_id=<rid>
```

The concierge lives in **PostHog's primary org** so it's
available to every team via the standard MCP / chat ingress. Each
trigger's `auth.modes: [posthog, posthog_internal]` means it's not
callable as a random external bot — only the console's signed
session-principal token (`posthog_internal`) + verified user PATs
(`posthog`) get through.

## Regression test

[`services/agent-tests/src/cases/example-agent-concierge.test.ts`](../../cases/example-agent-concierge.test.ts)
loads the bundle from disk and asserts:

- Every `spec.skills[].path` exists in the bundle
- `agent.md` is present and non-trivial
- `spec.mcps` is empty (the concierge authors via native tools only —
  no external MCP server in the write path) **and** every declared
  native tool id resolves in the native catalog (`listNativeTools()`)
- Both `chat` and `mcp` triggers are declared
- The `kind: "client"` tools (`focus_*`, `toast`, `get_context`,
  `set_secret`) are present, and the destructive native writes
  (`promote`, `archive`) carry inline `requires_approval` +
  `approval_policy`

NOT a real-inference test — the model is faux. This is the wiring
regression net, not a quality bar. (A future real-inference case
could drive a realistic inspect / debug flow with mocked authoring
tool responses.)

Run with:

```bash
pnpm --filter @posthog/agent-tests test cases/example-agent-concierge
```

## Extending the concierge

Two ways:

1. **Fork.** Clone the bundle, edit, deploy under a different
   slug. Useful for teams that want bespoke review steps,
   internal links, or a different tone.
2. **Add a skill upstream.** New shared workflow (e.g.
   `judge-test-results`) → add a skill file + a
   `spec.skills[]` entry + a one-line description. Re-freeze.

Don't fork to add a tool that should be universally available —
add it to the canonical bundle so every team benefits.

## Tuning notes

- `reasoning: high` is set because debugging and editing benefit
  from long deliberation. Cost-sensitive deployments can drop to
  `medium` and re-evaluate.
- `limits.max_turns: 80` is generous; most flows finish in 5-15
  turns. The cap protects against pathological loops while
  allowing complex multi-step audits.
- The skill descriptions in `spec.skills[]` are deliberately
  prescriptive ("Load when..." / "Load IMMEDIATELY if...") —
  this is the only signal the model gets about when to fetch
  the skill body. Tune the descriptions before the bodies.
- `agent.md` is intentionally short. Anything beyond identity,
  mode-selection, hard rules, and tone belongs in a skill.
