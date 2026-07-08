# PostHog AI — ask PostHog anything, from Slack

A Slack-triggered agent with the **full PostHog MCP** tool surface. It answers
questions about a user's PostHog data — insights, HogQL, dashboards, flags,
error tracking — by calling the MCP **as the asking user** (their linked PostHog
identity), never as PostHog.

This is the MCP counterpart to the `agent-builder` example: instead of the
native `@posthog/*` tools, everything flows through one MCP entry.

## How it's wired

- **Trigger:** `slack` (mention + DM). `allow_workspace_participants: false` —
  required, so the asker is the session owner and their identity resolves; a
  shared thread would fail closed (you can't act as the user for someone else).
- **MCP:** one entry pointing at the PostHog MCP with `auth.provider: "posthog"`.
  The runner resolves the **asking user's** PostHog bearer and stamps it on every
  MCP request. Unlinked → the tool returns an `auth_required` link the agent
  relays in the thread.
- **Identity provider:** `{ kind: "posthog", scopes: [<read scopes>] }`. On
  promote the backend provisions a normal (user-consented) OAuth app and the
  link requests these scopes. They must be **explicit OAuth scope objects** —
  the `*` wildcard is a PAT/first-party concept and OAuth `/authorize` rejects
  it (`invalid_scope`). The set here is broad read access (query, insights,
  dashboards, flags, experiments, error tracking, …); add more `:read` scopes
  if the user asks about a surface that 403s. The OAuth app's scope ceiling is
  provisioned from this list, so changing it requires a re-promote.
- **No native tools, no `spec.secrets`.** Replies post to the thread via the
  platform Slack relay (no `@posthog/slack-*` needed). The Slack
  `SLACK_SIGNING_SECRET` + `SLACK_BOT_TOKEN` are trigger-required secrets — set
  them in the agent's `encrypted_env`, not the spec.

## The MCP URL tracks the seed target

`spec.json` ships the localhost URL (`http://localhost:8787/mcp`). `seed.py`
rewrites any `auth.provider: "posthog"` MCP entry to match the host it's seeding
into: `localhost` → local, `*.us.posthog.com` → `mcp.us.posthog.com`,
`*.eu.posthog.com` → `mcp.eu.posthog.com`. An explicit `MCP_URL` /
`MCP_URL_posthog` env still wins.

## Set it up + test in Slack

1. Create a Slack app from the generated manifest:
   `agent-applications-revisions-slack-manifest` (its scopes + event
   subscriptions are derived from this spec). Paste the `events_url` /
   `interactivity_url` it returns into the Slack app dashboard.
2. Set `SLACK_SIGNING_SECRET` + `SLACK_BOT_TOKEN` in the agent's env editor
   (both are required before promote).
3. Lock `trusted_workspaces` from `"*"` to your workspace id.
4. Seed + promote: `PAT=phx_… python services/agent-tests/src/examples/seed.py posthog-ai`
5. In Slack, @-mention or DM the bot. First call → it relays a "connect your
   PostHog account" link; after you link, ask it real questions ("how many
   signups this week?").

## Regression test

[`services/agent-tests/src/cases/example-posthog-ai.test.ts`](../../cases/example-posthog-ai.test.ts)
asserts the wiring (slack trigger, the posthog-provider MCP, the posthog
identity provider, a non-trivial `agent.md`) — a faux net, not a quality bar.
