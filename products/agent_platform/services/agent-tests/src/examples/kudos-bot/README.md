# Kudos bot — peer-recognition collector + weekly digest

First-iteration ("infant") recognition bot.
People `@mention` it in Slack (or DM it, or chat from the console)
with "kudos to @jane for …"; it records each one, asks a single
clarifying question when the message is too thin, and every Monday
posts a celebratory digest of the week's kudos to a shared channel.

## Status

**Infant.** Buildable today on shipped primitives — Slack mention
trigger, cron trigger, the tabular + prose memory stores, the native
Slack tools. Capture is intentionally **mention- / chat-driven**:
people `@mention` the bot, DM it, or chat from the console. No value
loop is blocked; the items in [Gaps](#gaps-that-constrain-this-version)
are enhancements, not duct-tape.

## What it does

| Capability                               | How                                                                                                        |
| ---------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| Capture a kudos from a Slack `@mention`  | `slack` trigger, `mention_only: true` + `auto_resume_threads: true`                                        |
| Ask one clarifying question, then record | `auto_resume_threads` keeps the back-and-forth in one session; `skills/capturing-kudos`                    |
| Capture a kudos from the console         | `chat` trigger                                                                                             |
| **Post a weekly digest every Monday**    | `cron` trigger (`0 9 * * 1`, PT) → `@posthog/slack-post-message`; `skills/weekly-summary`                  |
| Store kudos as deterministic rows        | `@posthog/table-append` / `-query` / `-count` on the `kudos` table, deduped on `kudos_id`                  |
| Build a per-person highlight reel        | `@posthog/memory-write` / `-update` / `-read` / `-search` over `people/<handle>.md`                        |
| Acknowledge in Slack                     | `ack_reaction: raised_hands` (ingress, instant) + `@posthog/slack-react` `:tada:` (the "recorded" confirm) |
| Answer "what did @jane get?"             | `@posthog/table-query` by `recipient_handle` + the person's profile memory                                 |
| Follows a consistent capture flow        | `skills/capturing-kudos/SKILL.md`                                                                          |
| Follows a consistent storage schema      | `skills/kudos-storage/SKILL.md`                                                                            |
| Follows a consistent digest format       | `skills/weekly-summary/SKILL.md`                                                                           |

## Identity model — just the handle

The bot stores the **literal Slack handle** for both giver and
recipient and does no identity resolution: no email lookup, no
PostHog-person matching, no fuzzy dedupe of "Jane" vs "@jane". A
handle is the key. This is a deliberate v0 simplification — see
[Gaps](#gaps-that-constrain-this-version) for what stable identity
would buy.

## What it cannot do

- **Capture passively.** By design it only acts when `@mention`ed,
  DM'd, or chatted — a "great work @jane!" said in a channel without
  naming the bot is not picked up. This is the intended, affordable
  default (one session per addressed message, not per channel message).
- Resolve a handle to a person, dedupe display-name changes, or work
  across workspaces.
- Hand out rewards / points / gift cards. It records and celebrates;
  it doesn't transact.

## Bundle layout

```text
kudos-bot/
├── README.md                            # this file
├── spec.json                            # AgentSpec — triggers, tools, skills, limits
├── agent.md                             # system prompt
└── skills/
    ├── capturing-kudos/SKILL.md         # how to read a kudos + when to ask
    ├── kudos-storage/SKILL.md           # the table + profile schema, dedupe key
    └── weekly-summary/SKILL.md          # the Monday digest format
```

## Data model

`kudos` table (one row per recipient per kudos; `dedupe_on: kudos_id`):

| Column             | Type   | Notes                                                            |
| ------------------ | ------ | ---------------------------------------------------------------- |
| `kudos_id`         | string | Dedupe key, `slack:<channel>:<ts>:<recipient>` / `chat:<sid>:…`. |
| `recipient_handle` | string | Verbatim handle.                                                 |
| `giver_handle`     | string | Verbatim handle.                                                 |
| `message`          | string | The praise.                                                      |
| `themes`           | string | Comma-separated tags, optional.                                  |
| `given_at`         | string | ISO timestamp (from the message, not "now").                     |
| `week`             | string | ISO week — the weekly digest filters on this.                    |
| `source`           | string | `slack` / `chat`.                                                |
| `permalink`        | string | Slack link, optional.                                            |

`people/<handle>.md` memory — a rolling highlight reel per recipient.
Writes here are **not** approval-gated (low-stakes, high-volume — the
opposite call from the SRE bot's runbook corpus).

## Prerequisites for deploying

1. **Your own Slack app** registered at api.slack.com. Two values:
   - `SLACK_BOT_TOKEN` (`xoxb-…`) — used by the native `@posthog/slack-*`
     tools to call the Slack Web API.
   - `SLACK_SIGNING_SECRET` — verifies inbound event payloads for the
     `slack` trigger.
   - Scopes: `app_mentions:read`, `chat:write`, `reactions:write`,
     `channels:history`, `groups:history`, plus `im:history` /
     `im:read` if you want DM capture. Subscribe to `app_mention` and
     (for thread follow-ups) `message.channels` / `message.im`. The
     bot user must be a member of every channel it should hear.
2. **`spec.triggers[].slack.trusted_workspaces`** — replace the
   placeholder `T0XXXXXXX` with your Slack team id.
3. **A kudos channel.** The weekly digest posts to whichever channel
   you tell the bot about (today: bake it into the cron prompt or the
   agent.md). The bot must be a member of it.
4. **PostHog access** for the platform itself (PAT) — the `chat`
   trigger and console use the connected user's principal.

> **`ack_reaction` caveat.** The instant `:raised_hands:` ack the
> ingress adds the moment a mention lands resolves the bot token via
> the agent's Slack **integration**, not the `SLACK_BOT_TOKEN` secret
> the native tools use. Until a Slack integration row exists it logs
> `ack_reaction_no_bot_token` and skips the reaction (fire-and-forget,
> harmless). The model's own `:tada:` confirm — which goes through
> `@posthog/slack-react` + `SLACK_BOT_TOKEN` — is unaffected. Drop
> `ack_reaction` from the spec if you don't want the instant ack.

Set the two secrets via the [agent-builder](../agent-builder/)
`set_secret` punch-out so the values never transit the model's
tool-call history. The flow is the same as the
[sre-slack-bot](../sre-slack-bot/README.md#agent-builder-walkthrough--recommended-setup-flow);
swap the secret list for `SLACK_BOT_TOKEN` + `SLACK_SIGNING_SECRET`.

## A note on auth

Auth is per-trigger. The `slack` and `cron` triggers are intrinsic —
the `slack` trigger verifies inbound events with `SLACK_SIGNING_SECRET`
and carries no `auth` block; cron fires internally. The `chat` trigger
declares `auth.modes: [{ type: "posthog_internal" }, { type: "pat" }]`
— closed by default, so the console path uses a PostHog PAT. No
`public` exposure is needed — the bot only ever receives signed Slack
events or authenticated console traffic.

## Deploying

Through the authoring MCP (preferred) or the janitor REST API —
identical to the [sre-slack-bot deploy steps](../sre-slack-bot/README.md#deploying),
substituting `slug=kudos-bot`.

## Regression test

[`services/agent-tests/src/cases/example-kudos-bot.test.ts`](../../cases/example-kudos-bot.test.ts)
loads this bundle from disk, deploys it through the e2e harness, and
drives both flows with the faux model: a Slack-mention capture
(`@mention` → react → append row → write profile) and the Monday cron
digest (`cronTick` → query last week → post). Run with:

```bash
pnpm --filter @posthog/agent-tests test cases/example-kudos-bot
```

## Gaps that constrain this version

None block the bundle — each is an enhancement.

- **Reaction-as-trigger.** The most natural kudos UX is reacting to a
  message with `:clap:` / `:trophy:`. Slack delivers `reaction_added`
  events, but the `slack` trigger only routes `message` / `app_mention`
  today. A `reaction_added` trigger variant (with an emoji allowlist)
  would let people give kudos with one click — no typing, no mention.
- **Optional passive capture.** If a team ever wanted the bot to catch
  kudos said in a channel without naming it, that needs
  `mention_only: false` + `message.channels`, which today spins up a
  **session per message**. An ingress-level content pre-filter (fire
  only on messages matching `kudos` / `:clap:` / a regex) would make
  that affordable. Not needed for this bundle — `mention_only: true`
  is the right default — but it's the primitive a passive variant
  would want.
- **Stable identity / a people directory.** Storing raw handles works
  but is brittle: a display-name change splits a person's history, and
  there's no cross-workspace identity. The existing **per-principal /
  per-user memory scope** gap (`MemoryStore` keys on
  `(team, application)` only — see `_APP_IDEAS.md` cross-cutting
  status) is the same shortfall viewed from the storage side. v0
  accepts the handle as the key; a directory primitive would make
  aggregation reliable.
- **A first-class agent-config surface for the target channel.** The
  digest channel is hard-coded into the prompt today — the same
  "user-maintained config in memory" nice-to-have flagged on the
  [wake-me-up](../wake-me-up/) bundle. A small console panel
  (channel, schedule, emoji allowlist) would lift this to fully wired.
- **Native Slack `chat.getPermalink`.** To store a `permalink` back to
  the original kudos message the bot would call `chat.getPermalink`;
  there's no native wrapper, so v0 leaves `permalink` empty or
  reaches for `@posthog/http-request`. Cosmetic.

## Tuning notes

- `reasoning: medium` — kudos parsing is light; the only judgement is
  "is this a kudos and what's missing." Drop to `low` if cost matters;
  bump to `high` only if you add richer theme inference.
- `resume.enabled: true` with a 7-day TTL keeps a capture thread open
  so "oh, also for the docs" resumes cleanly. Without it the platform
  would close the thread at the 24h default and a late addition would
  start a fresh, context-less session.
- `mention_only: true` is the right default — the bot acts only when
  addressed. Flipping it to `false` (passive capture) would wake the
  agent on every channel message; don't, unless the content pre-filter
  in [Gaps](#gaps-that-constrain-this-version) lands first.
