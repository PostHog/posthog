# Agent Builder — the meta-agent for the platform

The "explain, debug, edit" assistant for every agent on the
PostHog agent platform. One deployment, two surfaces (PostHog Code
chat dock, MCP from Claude Code / Cursor),
all acting under the user's PostHog OAuth principal.

## Status

**Reference bundle.** Loadable, faux-testable, and deployable on the
current platform. The pieces this bundle leans on have shipped:
`kind: "client"` tool support is in the spec schema (and exercised by
the `focus_*` / `set_secret` entries), the runner opens the clients
declared in `spec.mcps`, and the `agent-applications-*` authoring
surface is reached through the one declared PostHog MCP, authed by
the `posthog` identity provider as the asking user.

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

For each mode, the Agent Builder calls the `agent-applications-*`
tools on the PostHog MCP,
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

| Class            | Tool                                                                                                                                    | Class semantics                                                                                                                                                                                                                      |
| ---------------- | --------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| MCP (authoring)  | `agent-applications-*` (list, retrieve, revisions, sessions, logs + the draft edit + validate verbs)                                    | The bulk of its work — read + write agent state as the connected user, via the one `spec.mcps` entry (PostHog MCP, `posthog` identity provider). Curated `tools[]` allow-list; `promote` / `archive` / `destroy` are approval-gated. |
| MCP (telemetry)  | `execute-sql`, `insight-query`, `get-llm-total-costs-for-project`                                                                       | HogQL / insights over the agent's LLM-observability events (`$ai_generation` / `$ai_span` / `$ai_trace`) the runner captured into the team's project. Powers debug + improve evidence.                                               |
| Native (runtime) | `@posthog/memory-search`, `@posthog/memory-read`, `@posthog/memory-write`, `@posthog/web-search`                                        | The agent's own runtime tools — durable memory (persist a fleet-audit report) and web search.                                                                                                                                        |
| Client           | `focus_tab`, `focus_file`, `focus_revision`, `focus_session`, `focus_spec_section`, `toast`, `get_context`, `set_secret`, `connect_mcp` | Drive PostHog Code's read panel + read the user's current view. No-op outside PostHog Code.                                                                                                                                          |

## Auth model

Auth is configured **per trigger** — there is no top-level
`spec.auth`. Each of the Agent Builder's triggers sets
`auth.modes: [posthog, posthog_internal]` (an array), so both entry
points map to the same effective auth:

1. **PostHog Code** — user signs into the PostHog Code app via
   PostHog OAuth; the app mints a short-lived session-principal
   token from the OAuth session and attaches it to the chat trigger.
   Every tool call runs as the user without a separate MCP connection.
2. **MCP** — user attaches their PostHog PAT in their MCP client
   config. The runner resolves the PAT to a principal once at
   session start, threads it through identically.

The Agent Builder holds no fallback credential.

The PostHog MCP is a first-party implementation detail of the builder, not a
connection the user configures. MCP startup only reuses an existing trigger or
linked credential; it never starts OAuth or reconnects automatically. The
identity-connect tool remains available for agents that intentionally support
account linking, but startup never invokes it.

The Agent Builder chat therefore does not use the ingress OAuth callback route.
PostHog Code supplies the signed-in user's short-lived bearer at the trigger
edge, and the runner passes that credential to the first-party MCP. The
`/link/<provider>/callback` flow exists for agents that intentionally support
connecting an additional identity.

The checked-in MCP URL is the local development endpoint. `seed.py` rewrites
PostHog-authenticated MCP entries to the target region, so the production US
deployment uses `https://mcp.us.posthog.com/mcp` rather than localhost. The
PostHog identity provider explicitly allows that matching regional MCP host.

## Platform pieces it relies on (all shipped)

These are platform-side, not bundle-side — and they're in place:

1. **`kind: "client"` tool support in the spec** — the spec schema
   accepts `kind: "client"`; the bundle's `focus_*`, `toast`, and
   `set_secret` entries parse and validate.
2. **Runtime MCP support** — the runner opens the clients declared in
   `spec.mcps` at session start. (The Agent Builder declares exactly
   one — the PostHog MCP, authed by the `posthog` identity provider —
   which carries its whole authoring surface.)
3. **OAuth principal threading** — the session principal threads
   through every tool call, so writes attribute to the user.
4. **The MCP authoring tools** — the `agent-applications-*` verbs
   (including draft-edit + validate) are served by the PostHog MCP,
   scoped by the entry's curated `tools[]` allow-list, with the
   destructive verbs approval-gated.

## Deploying

The canonical US-prod deployment is kept in sync by CI:
[`.github/workflows/cd-agent-builder-seed.yml`](../../../../../../../.github/workflows/cd-agent-builder-seed.yml)
runs `seed.py agent-builder` against `us.posthog.com` on every master
push touching this bundle, `seed.py`, or `backend/kernel_skills/`, plus
a daily schedule (kernel-skill changes only take effect once the
backend deploy carrying them is live, so the scheduled run converges
them; it also heals manual drift). Runs are churn-free: a seed whose
frozen artifact is byte-identical to the live revision skips promote
instead of minting a new live revision. It authenticates with the
`AGENT_BUILDER_SEED_PAT` repo secret and is gated to the canonical
deploy repo via `CD_DEPLOY_ENABLED`. Manual seeding is only needed for
other environments or when bootstrapping from scratch.

Through the authoring MCP (preferred for manual deploys — same as
other example bundles):

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
- Authoring goes through ONE PostHog MCP (`spec.mcps[0].auth.provider`
  is `posthog`), the only natives left are the agent's own runtime
  tools (memory + web-search), **and** every declared native tool id
  resolves in the native catalog (`listNativeTools()`)
- Both `chat` and `mcp` triggers are declared — and NO `slack` trigger
  (no dedicated Slack app exists, and a slack trigger blocks promote
  until its required secrets are set)
- The `kind: "client"` tools (`focus_*`, `toast`, `get_context`,
  `set_secret`, `connect_mcp`) are present, and the destructive MCP
  authoring tools (`promote`, `archive`, `destroy`) are gated with
  `level: "approve"` + a principal `approval_policy`

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
