# kitchen-sink — the everything agent

A deliberately maximal reference bundle: it wires **virtually every
feature the platform exposes today** into one agent ("Sink"), so the
whole surface can be poked from a single deployable bundle. New
primitives should grow a demonstration here.

It's also a real, usable assistant — memory, tables, Slack, the web,
PostHog data, identity-linked credentials, approvals, and a wide,
slightly delightful skill set.

> Status: **infant** — every wired feature is buildable against shipped
> primitives, but a few edges are duct-taped or deliberately left off
> (see [Known gaps](#known-gaps)). No `../cases/example-kitchen-sink.test.ts`
> exists yet — see [The regression net](#the-regression-net-todo).

## What it exercises

| Surface                         | How this bundle demonstrates it                                                                                                                                                                                                                                        |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **All 5 trigger types**         | `chat` (console, `allow_restart`), `slack` (mention + DM + auto-resume + ack reaction), `cron` (`daily-delight`, weekday 09:00 PT, catch-up), `webhook` (`POST /webhook`, shared-secret auth), `mcp` (exposes Sink as an MCP tool).                                    |
| **Trigger auth modes**          | `posthog` + `posthog_internal` (chat/mcp), `shared_secret` (webhook), intrinsic Slack signing, `audience: organization` on the mcp trigger.                                                                                                                            |
| **Native tools — every family** | memory (`-search/-read/-list/-write/-update/-delete`), tables (`-query/-count/-membership/-append/-delete/-truncate`), `query`, `list-projects`, `http-request`, `identity-connect/-fetch`, slack (`-post-message/-update-message/-read-thread/-read-channel/-react`). |
| **Both approval authorities**   | `agent` (team-admin) on `memory-write/-update` + `table-truncate`; `principal` (the asker) on `memory-delete`, `table-delete`, `http-request`, and two `posthog__*` MCP tools. Plus `allow_edit` on a few.                                                             |
| **Client tools**                | `get_context`, `toast`, and the **interactive** `set_secret` (parks the session, resumes on the user's answer). All `required:false` → degrade gracefully off-console.                                                                                                 |
| **MCPs (connect-out)**          | `posthog` (managed `posthog` provider, curated tool list with two gated entries) **and** `github` (bring-your-own `oauth2` provider).                                                                                                                                  |
| **Identity providers**          | managed `posthog` (read scopes + `feature_flag:write`) **and** bring-your-own `oauth2` `github`. Demonstrates `link_required` → connect-link flow.                                                                                                                     |
| **Secrets + host binding**      | bare (`SLACK_SIGNING_SECRET`, `WEBHOOK_SECRET`, `GITHUB_OAUTH_CLIENT_SECRET`) and host-bound (`SLACK_BOT_TOKEN`→`slack.com`, `EXAMPLE_API_TOKEN`→`api.example.com`).                                                                                                   |
| **Resume**                      | `enabled: true`, 7-day `max_completed_age_ms` — a Slack thread / cron session stays reachable.                                                                                                                                                                         |
| **Sandbox limits**              | `max_memory_mb` / `max_cpu_cores` set (ready for custom tools).                                                                                                                                                                                                        |
| **Framework prompt knob**       | `framework_prompt.omit: []` present as a no-op, to show the escape hatch exists.                                                                                                                                                                                       |
| **Skills**                      | 6 capability skills (the _right_ way to use each feature) + 5 wide-ranging "fun" skills.                                                                                                                                                                               |

### Skills

**Capability** — `using-memory-and-tables`, `working-with-approvals`,
`slack-presence`, `querying-product-data`, `reaching-the-internet`,
`acting-as-you`.

**Wide-ranging** — `on-this-day` (the cron's daily delight),
`rubber-duck`, `standup-bard`, `the-decider`, `explain-like-im-five`.

## Prerequisites

To **deploy + promote** (the bundle goes live and visible) you need the
trigger-required secrets set, even if dummy:

| Secret                                    | Needed for                           | Real value?                      |
| ----------------------------------------- | ------------------------------------ | -------------------------------- |
| `SLACK_SIGNING_SECRET`, `SLACK_BOT_TOKEN` | Slack trigger (promote gate)         | Yes, for Slack to actually work. |
| `WEBHOOK_SECRET`                          | webhook shared-secret auth           | Yes, to call the webhook.        |
| `EXAMPLE_API_TOKEN`                       | the `http-request` host-binding demo | Only to exercise that path.      |
| `GITHUB_OAUTH_CLIENT_SECRET`              | the `github` oauth2 provider         | Only to exercise GitHub linking. |

For a **local "just make it live" run**, `SEED_DUMMY_SECRETS=1` sets
fake placeholders so it promotes (Slack/webhook calls will fail signature
checks, but the agent shows up and chat works).

Before Slack/GitHub actually function you'd also:

- Replace `triggers[].slack.trusted_workspaces` (`["T0XXXXXXX"]`) with
  your real Slack team id, create the Slack app from the generated
  manifest, and set a posting channel for `on-this-day`.
- Register a real GitHub OAuth app and drop its `client_id` into
  `identity_providers[]` + its secret into `GITHUB_OAUTH_CLIENT_SECRET`.

## Deploy

From the repo root, via the shared seeder
([`../seed.py`](../seed.py)):

```bash
# Local dev — mints the dev key, sets dummy secrets so it promotes:
SEED_DUMMY_SECRETS=1 python \
  products/agent_platform/services/agent-tests/src/examples/seed.py kitchen-sink

# Dry run (no mutations):
python products/agent_platform/services/agent-tests/src/examples/seed.py --list

# To a real project:
PAT=phx_… POSTHOG_API=https://us.posthog.com PROJECT_ID=123 python \
  products/agent_platform/services/agent-tests/src/examples/seed.py kitchen-sink
```

The seeder rewrites the `posthog` MCP `url` to match the target region
automatically; the `github` MCP url is left as-is.

## Known gaps

- **Custom tools are intentionally NOT wired.** The platform's
  `kind: 'custom'` (sandboxed, author-written) tools aren't reliable
  enough to demo yet, so this bundle omits them. The spec's
  `max_memory_mb` / `max_cpu_cores` are set in anticipation. **When
  custom tools are solid, add one here** (the obvious candidate: an
  enrichment tool that `requires_identity: 'github'`, so it also
  demonstrates a custom tool acting as the linked user). This is the
  single biggest "not everything yet" item.
- **`spec.integrations` is empty.** Team-level integration credentials
  aren't demonstrated (Slack here goes through `secrets`, matching the
  other examples). Add one once there's a non-Slack integration worth
  showing.
- **No ungated `web-fetch` tool exists yet.** `@posthog/web-fetch` is
  referenced in the platform but not registered, so the only egress tool
  is the approval-gated `@posthog/http-request`. Consequence:
  `on-this-day`'s unattended cron can't fetch live (a gated call would
  park with no one to approve), so it composes an evergreen delight or
  re-posts a stored one; only on-demand asks fetch live. When
  `web-fetch` ships, wire it in and let the cron fetch freely.
- **`trusted_workspaces` / GitHub `client_id` are placeholders.** It
  promotes, but Slack and GitHub linking need the real values.

## The regression net (TODO)

Per the [examples README](../README.md), a bundle reaches **ready**
status when it has a `../cases/example-kitchen-sink.test.ts` that loads
it from disk, deploys it through the in-process harness, and drives a
realistic flow. This bundle doesn't have one yet. A good first case:
chat → "remember that I prefer dark mode" → assert the `memory-write`
returns a **queued** approval envelope (not a real write), mirroring
[`example-agent-approval-demo.test.ts`](../../cases/example-agent-approval-demo.test.ts).
Until then the source of truth for "does this still parse + freeze" is
running `seed.py --list` and a validate.
