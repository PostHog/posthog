# One-time setup

## `~/.config/foundry/bet.env` (required)

```sh
POSTHOG_URL=http://localhost:8010
POSTHOG_PROJECT_ID=<team id>
POSTHOG_PERSONAL_API_KEY=<personal API key>
```

Mint the key with the minimal scope list this skill needs:

```sh
# from the posthog repo root, with a working Django env
.claude/skills/bet/scripts/mint-api-key.sh you@example.com
```

This creates a `PersonalAPIKey` for that user (via `manage.py shell` —
`PersonalAPIKey.objects.create(..., secure_value=hash_key_value(token), ...)`,
the same pattern the repo's own tests use to mint keys) and writes
`bet.env` with mode `0600`. It never prints or logs the raw token except into
that file.

**Scopes minted, and why each is needed:**

| Scope             | Why                                                                                                                                                          |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `bet:write`       | Full bet lifecycle: create/fund/verdict/events. `:write` also satisfies `:read` checks, so this alone covers `list`/`retrieve`/`GET events`/`GET nodes` too. |
| `insight:write`   | Create the optional rollout-KPI insights (`kpi-dashboard.sh`).                                                                                               |
| `dashboard:write` | Create the optional `Bet: <slug>` KPI dashboard.                                                                                                             |
| `experiment:read` | Pull experiment name/dates into `/bet status` and `/bet verdict`.                                                                                            |

No scope grants access to anything outside bets, dashboards/insights, and
read-only experiment data — the skill never needs the user's session cookie
or admin credentials, on Cloud or self-hosted.

If `bet.env` is missing or a variable is empty, every script exits with an
actionable message naming the exact variable — don't try to work around it,
surface the message.

## `~/.config/foundry/memory.env` (optional)

```sh
MEMORY_GIT_BASE=https://git.example.com/memory
MEMORY_GIT_USER=some-bot-user
MEMORY_GIT_TOKEN=<token with push access to the org's repos>
```

One Gitea (or equivalent) org, one repo per product, e.g.
`$MEMORY_GIT_BASE/<product>.git`. If this file is absent or incomplete, every
memory step (`memory-seed.sh`, `memory-verdict.sh`, and the memory step
inside `record-verdict.sh`) prints a one-line note and exits 0 — memory is a
nice-to-have, never a hard dependency for running a bet. Say this to the user
plainly rather than silently skipping.

The default product repo is `foundry` (`MEMORY_GIT_PRODUCT` env var, or
`--product NAME` on `memory-seed.sh`/`memory-verdict.sh`, overrides this) —
point it at whichever product's memory repo the bet is actually about.

**Never commit either env file, and never put real values in SKILL.md or any
committed doc** — only placeholders like the tables above. `bet.env` and
`memory.env` live outside the repo (`~/.config/foundry/`) precisely so a
`git status` inside the repo never sees them.

## Managed-bet credentials in `memory_repo_url`

When a bet is `managed` and the user wants the memory repo cloned into every
node's sandbox, `memory_repo_url` needs to carry credentials if the repo
requires auth (private Gitea, in our case) — there's no separate credential
channel into the sandbox. `scripts/lib.sh`'s `memory_repo_url` function
builds the tokened `https://user:token@host/...` form from `memory.env` for
exactly this reason. **This means the token becomes readable to anyone with
`bet:read` on that bet** (it's returned verbatim in the API response) — an
accepted trade-off for a bot token scoped to one memory org, not something to
extend to a token with broader blast radius. Don't embed a personal or
broadly-scoped credential this way.
