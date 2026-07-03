# Agent Builder — the meta-agent for the platform

The "explain, debug, edit" assistant for every agent on the
PostHog agent platform. One deployment, three surfaces (PostHog Code
chat dock, MCP from Claude Code / Cursor, future Slack),
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
underperforming?"), the Agent Builder sweeps every agent in the team,
mines each one's recent sessions for failures / anomalies / degraded
behaviour, diagnoses root causes, and for each concrete fix branches
a **draft** revision with the change applied (validated, never frozen
or promoted — drafts are proposals a human reviews). The findings
land as a structured report in memory (`reports/fleet-audit/{date}.md`
plus `latest.md`), which is the deliverable of the sweep.

The run is deliberately read-and-propose: the skill forbids
freeze / promote / archive / delete, leaving the validated drafts for
the user to review and promote themselves. `auditing-the-fleet` is a
kernel skill, injected at freeze — see
[`backend/kernel_skills/auditing-the-fleet/SKILL.md`](../../../../../backend/kernel_skills/auditing-the-fleet/SKILL.md).

For each mode, the Agent Builder calls the same `agent-applications-*`
native tools that the authoring AI uses,
acting under the connected user's principal so every write shows
up in the activity log as **the user**, not as the Agent Builder.

## Where its guidance lives — three homes, none of them this bundle

The Agent Builder's instructional content sits in exactly one of three
places, chosen by **what the content is for**. None of it ships in this
author-facing bundle — the bundle is just `agent.md`, `spec.json`, and
the faux test cases.

| Home              | What                                                                                                                                                              | How it reaches the agent                                                                                                                                                              |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Kernel skills** | The concierge's own runtime behaviour, coupled to the platform (safety, console UI, working outside it, fleet audit)                                              | Injected from backend code (`products/agent_platform/backend/kernel_skills/`) at **freeze**; read via `@posthog/load-skill`. Code-locked, identical across accounts, never in the DB. |
| **MCP playbooks** | Reusable builder knowledge — how to read / debug / edit / author agents, identity, secrets, Slack, MCP-surface design, model choice, testing, cost, observability | Served by the MCP `agent-resolve-resource`, fetched on demand. Versioned with the MCP code.                                                                                           |
| **Skill store**   | Team-authored reusable agent skills                                                                                                                               | Pinned via `skill_refs`, materialized into the bundle at freeze.                                                                                                                      |

Kernel skills are platform-injected (see
[`logic/kernel_skills.py`](../../../../../backend/logic/kernel_skills.py) — a
folder of SKILL.md files whose frontmatter declares an `agents:` mapping).
Authors never write skills inline; `skill_refs` → the store is the only
author path into a bundle's `skills/`.

## Bundle layout

```text
agent-builder/
├── README.md     # this file
├── spec.json     # triggers, tools, mcps — NO skills[] (kernel injected at freeze)
├── agent.md      # system prompt; loads kernel skills + fetches MCP playbooks
└── tests/        # faux wiring cases
```

## Tool surface

| Class              | Tool                                                                                                                     | Class semantics                                                                                                                                                                                          |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Native             | `@posthog/agent-applications-*` (list, retrieve, revisions, sessions, logs + the draft edit + validate verbs)            | Read agent state — applications, revisions, sessions, logs — as the connected user. Routed through the credential broker; no platform credentials, no impersonation.                                     |
| Native (telemetry) | `@posthog/query`                                                                                                         | HogQL the agent's LLM-observability events (`$ai_generation` / `$ai_span` / `$ai_trace`) the runner captured into the team's project. Powers debug + improve evidence — see `querying-ai-observability`. |
| Native (audit I/O) | `@posthog/memory-search`, `@posthog/memory-read`, `@posthog/memory-write`                                                | Durable output of a fleet audit — persist the report to memory.                                                                                                                                          |
| Client             | `focus_tab`, `focus_file`, `focus_revision`, `focus_session`, `focus_spec_section`, `toast`, `get_context`, `set_secret` | Drive PostHog Code's read panel + read the user's current view. No-op outside PostHog Code.                                                                                                              |

## Auth model

Auth is configured **per trigger** — there is no top-level
`spec.auth`. Each of the Agent Builder's triggers sets
`auth.modes: [posthog, posthog_internal]` (an array), so both entry
points map to the same effective auth:

1. **PostHog Code** — user signs into the PostHog Code app via
   PostHog OAuth; the app mints a short-lived session-principal
   token from the OAuth session, attaches it as the chat trigger's
   principal field. Every tool call runs as the user.
2. **MCP** — user attaches their PostHog PAT in their MCP client
   config. The runner resolves the PAT to a principal once at
   session start, threads it through identically.

The Agent Builder holds no fallback credential.

## Platform pieces it relies on (all shipped)

These are platform-side, not bundle-side — and they're in place:

1. **`kind: "client"` tool support in the spec** — the spec schema
   accepts `kind: "client"`; the bundle's `focus_*`, `toast`, and
   `set_secret` entries parse and validate.
2. **Runtime MCP support** — the runner opens the clients declared in
   `spec.mcps` at session start. (The Agent Builder declares none —
   `spec.mcps` is empty — because its authoring surface is native, not
   a remote MCP server.)
3. **OAuth principal threading** — the session principal threads
   through every tool call, so writes attribute to the user.
4. **The native authoring tools** — `@posthog/agent-applications-*`
   are native in-process tools resolved through the tool registry
   (not a separate MCP server), including the draft-edit + validate
   verbs the Agent Builder uses.

## Deploying

Through the authoring MCP (preferred — same as other example bundles):

```text
agent-applications-create slug=agent-builder name="Agent Builder"
agent-applications-revisions-create application_id=<id>
# write bundle resources via the granular per-resource tools:
#   agent-applications-revisions-agent-md-update / -tools-update
# kernel skills are injected from backend code at freeze (no author step);
# store skills come from the store: llm-skills-create / -search, then
#   agent-applications-revisions-skill-refs-update
agent-applications-revisions-partial-update revision_id=<rid> spec=<contents of spec.json>
agent-applications-revisions-validate-create revision_id=<rid>
agent-applications-revisions-freeze-create revision_id=<rid>
agent-applications-revisions-promote-create revision_id=<rid>
```

The Agent Builder lives in **PostHog's primary org** so it's
available to every team via the standard MCP / chat ingress. Each
trigger's `auth.modes: [posthog, posthog_internal]` means it's not
callable as a random external bot — only PostHog Code's signed
session-principal token (`posthog_internal`) + verified user PATs
(`posthog`) get through.

## Regression test

[`services/agent-tests/src/cases/example-agent-builder.test.ts`](../../cases/example-agent-builder.test.ts)
loads the bundle from disk and asserts:

- The bundle carries NO inline skills (kernel skills are injected at
  freeze from backend code; builder playbooks are served by the MCP)
- `agent.md` is present and non-trivial
- `spec.mcps` is empty (the Agent Builder authors via native tools only —
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
pnpm --filter @posthog/agent-tests test cases/example-agent-builder
```

## Extending the Agent Builder

Two ways:

1. **Fork.** Clone the bundle, edit, deploy under a different
   slug. Useful for teams that want bespoke review steps,
   internal links, or a different tone.
2. **Add guidance upstream**, in the right home (see the table
   above): a new **kernel** behaviour → drop a folder under
   `backend/kernel_skills/<id>/SKILL.md` with an `agents:` mapping in
   its frontmatter; a new **builder playbook** → add it to the MCP
   playbook set; team content → the skill store.

Don't fork to add a tool that should be universally available —
add it to the canonical bundle so every team benefits.

## Tuning notes

- `reasoning: high` is set because debugging and editing benefit
  from long deliberation. Cost-sensitive deployments can drop to
  `medium` and re-evaluate.
- `limits.max_turns: 80` is generous; most flows finish in 5-15
  turns. The cap protects against pathological loops while
  allowing complex multi-step audits.
- Kernel skill descriptions live in each SKILL.md's frontmatter
  (`backend/kernel_skills/`) and are deliberately prescriptive
  ("Load when..." / "Load IMMEDIATELY if...") — this is the only
  signal the model gets about when to fetch the skill body. Tune the
  descriptions before the bodies.
- `agent.md` is intentionally short. Anything beyond identity,
  mode-selection, hard rules, and tone belongs in a kernel skill or
  an MCP playbook.
