# Wake-me-up — daily briefing agent

Personal morning-briefing agent. Fires daily on a cron, optionally
also on `@mention` from Slack, and produces a categorised briefing
covering PostHog signals, GitHub PRs awaiting review, Slack
mentions, and yesterday's carry-over items. Writes a full markdown
report to memory and posts a condensed mrkdwn version to a
configured Slack channel.

Inspired by the user's local Claude-Code skill of the same shape;
this is the platform-resident version that runs without the user
being awake.

## Status

**Infant.** Buildable today on shipped primitives — no platform
work blocks it.
The bundle exercises every shipped concept the platform calls v0:
cron trigger, native tools, both prose (`memory-*`) and tabular
(`table-*`) memory, multi-skill loading, and Slack output.

## What it does

| Capability                                | How                                                                  |
| ----------------------------------------- | -------------------------------------------------------------------- |
| Daily firing                              | `cron` trigger at `0 8 * * 1-5` (Mon–Fri 08:00 PT)                   |
| On-demand re-run from Slack               | `slack` trigger, `mention_only: true`                                |
| Ad-hoc from the agent console             | `chat` trigger — useful for iterating on prompt / skills             |
| Pulls PostHog signals (alerts, anomalies) | `@posthog/query`                                                     |
| Pulls GitHub / external HTTP data         | `@posthog/http-request`                                              |
| Reads monitored Slack channels            | `@posthog/slack-read-channel`                                        |
| Writes the markdown report                | `@posthog/memory-write` to `briefings/{YYYY-MM-DD}.md`               |
| Tracks briefing index for carry-over      | `@posthog/table-append`, `@posthog/table-query` on `briefings` table |
| Carries forward yesterday's open items    | `skills/carry-over/SKILL.md`                                         |
| Pins the output schema                    | `skills/briefing-template/SKILL.md`                                  |
| Projects to Slack mrkdwn                  | `skills/slack-post-format/SKILL.md` → `@posthog/slack-post-message`  |

## What it cannot do (yet)

- **Reach private SaaS data.** Public GitHub / Zendesk / etc. is
  fine via `http-request`; private dashboards need an external MCP
  or a custom API tool.
- **Drive a UI.** This is a fire-and-write agent; it produces a
  markdown file + Slack post. The user reads from those, not from
  a console session.
- **Edit its own config.** Things like `channels.yml`,
  `teammates.yml`, `relevance.yml` live in memory as user-maintained
  notes — the agent reads them but doesn't rewrite them.

## Bundle layout

```text
wake-me-up/
├── README.md                              # this file
├── spec.json                              # AgentSpec
├── agent.md                               # system prompt
└── skills/
    ├── briefing-template/SKILL.md         # pinned output schema
    ├── carry-over/SKILL.md                # yesterday → today
    └── slack-post-format/SKILL.md         # mrkdwn projection
```

## Prerequisites for deploying

1. **Slack integration** connected to your PostHog team — same
   token the SRE bot uses.
2. **`spec.triggers[].slack.trusted_workspaces`** updated from the
   placeholder `T0XXXXXXX` to your Slack team id.
3. **Cron timezone** — `spec.triggers[].cron.timezone` defaults to
   `America/Los_Angeles`; change if you live elsewhere.
4. **Optional `channels.yml` in memory** — a markdown note at
   `channels.yml` listing monitored channels, teammates, target
   post channel. The agent reads it via `@posthog/memory-search`;
   it's user-maintained, not auto-discovered.

## Deploying

Same flow as any other agent — see
[SRE bot's README](../sre-slack-bot/README.md#deploying) for the
authoring MCP + janitor REST steps. The two are interchangeable;
the spec is what's specific.

## Regression test

[`services/agent-tests/src/cases/example-wake-me-up.test.ts`](../../cases/example-wake-me-up.test.ts)
loads this bundle from disk, deploys it, fires the cron trigger
through the janitor's `cronTick`, and drives a realistic full-loop
session with the faux model. Run with:

```bash
pnpm --filter @posthog/agent-tests test cases/example-wake-me-up
```

## Gaps that would make it better

- **External MCPs for GitHub / Zendesk / Linear.** `http-request`
  against public APIs works, but a dedicated MCP gets you typed
  responses + auth handling. Hooks straight into the
  `kind: 'external'` McpRef variant once you have the MCP URL
  - an OAuth integration row.
- **Skill templates for the briefing shape.** The two output
  skills (`briefing-template`, `slack-post-format`) are good
  candidates for the shared template registry — they're not
  agent-specific.
- **Custom relevance rules.** The user's dotfile version reads a
  `relevance.yml` file with natural-language rules. This bundle
  uses defaults; wiring user-maintained rules in memory is
  step-2 work.
