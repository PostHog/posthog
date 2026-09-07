---
name: upgrade-claude-adapter
description: >-
  Sync this fork of @anthropic-ai/claude-agent-acp (packages/agent/src/adapters/claude)
  with a newer upstream release: bump the claude-agent-sdk / @agentclientprotocol/sdk,
  port upstream bug fixes and new SDK message handling, preserve the fork's divergences,
  verify, and update UPSTREAM.md. Use when asked to "upgrade/sync the claude adapter",
  "bump the agent SDK", or "port upstream claude-agent-acp changes".
---

# Upgrade the Claude ACP adapter (upstream sync)

This is a runbook for syncing our **fork** of `@anthropic-ai/claude-agent-acp` (the upstream
Zed/agentclientprotocol ACP agent) that lives in `packages/agent/src/adapters/claude/` with a newer
upstream release. The fork is heavily diverged. The job is to port the *valuable* upstream changes
(SDK bumps, bug fixes, new SDK-message handling) while preserving every intentional divergence — not
to make the fork identical to upstream.

`UPSTREAM.md` (this directory) is the source of truth for the **fork point**, **last-synced
version/commit**, the **file mapping**, the **PostHog-only code**, and the **intentional
divergences**. Read it first, update it last.

> This file is a runbook, not an auto-registered slash command. Invoke it by telling Claude to
> "follow the upgrade skill in the claude adapter dir." Move it to `.claude/skills/<name>/SKILL.md`
> if you ever want it runnable as `/<name>`.

## Inputs you need before starting

1. **Upstream source checkout** — a local git clone of `github.com/agentclientprotocol/claude-agent-acp`.
   You need its history to diff. If the user hasn't given the path, **ask for it** (it's usually
   somewhere like `~/Cloud/claude-agent-acp`). Do not guess.
2. **This repo** — the fork under `packages/agent/`.

## Process

### 0. Orient (read, don't write)

- Read `UPSTREAM.md`. Note **Last sync** (commit + version), the pinned **SDK** versions, the
  **File Mapping**, **PostHog-Only Code (Do Not Sync)**, and **Intentional Divergences**.
- In the upstream checkout, list the change set since the last sync and skim the changelog:
  - `git -C <upstream> log --oneline <last-sync-sha>..HEAD`
  - `git -C <upstream> show <upstream>/CHANGELOG.md:CHANGELOG.md` (or just read `CHANGELOG.md`)
- Confirm the new target version + HEAD sha and the target SDK versions from the upstream
  `package.json`.

### 1. Triage every commit

Bucket each commit since the last sync:

- **Port** — bug fixes and new feature / SDK-message handling that are *not* in the PostHog-only
  list and don't fight a divergence.
- **Dep bump** — record the target SDK versions; the diff tells you if code changes ride along.
- **Skip** — `chore(main): release …`, `actions/* ` CI bumps, pure dependabot **dev**-dep bumps, and
  anything matching the PostHog-only / divergence lists.

Read intent from source diffs (exclude tests + JSON first):

```
git -C <upstream> show <sha> -- src/ ':(exclude)src/tests/*' ':(exclude)*.json'
```

A dependabot SDK-bump commit often *also* carries real code (new message handling). Don't assume
"deps" == "no code".

### 2. Map upstream → fork

Upstream is one large `src/acp-agent.ts`; our fork is split. Use the File Mapping in `UPSTREAM.md`.
Rough guide:

| Upstream | Fork |
| --- | --- |
| `acp-agent.ts` prompt loop, lifecycle, cancel | `claude-agent.ts` |
| inline message/stream/result/system conversion | `conversion/sdk-to-acp.ts` |
| inline prompt→SDK conversion | `conversion/acp-to-sdk.ts` |
| `tools.ts` (tool_use→ACP, PostToolUse hook) | `conversion/tool-use-to-acp.ts`, `hooks.ts` |
| model alias resolution | `session/models.ts`, `session/model-config.ts` |
| options / system prompt | `session/options.ts` |
| permissions | `permissions/*` |

For each upstream change, `rg` the fork for the touched symbol first — the fork usually already has a
diverged version of it, so you're editing, not adding.

### 3. Bump dependencies

In `packages/agent/package.json`, set `@anthropic-ai/claude-agent-sdk`, `@agentclientprotocol/sdk`,
and `@anthropic-ai/sdk` to the upstream `package.json` versions, then `pnpm install` from the repo
root. (`packages/shared` pins its own older `@agentclientprotocol/sdk`; leave it unless a
cross-package type error forces a bump.)

### 4. Find the breaking-change surface

Run `pnpm --filter agent typecheck`. The errors are your ACP/SDK breaking-change list. Gotchas seen
in past syncs:

- **The ACP SDK ships name-mangled generated types.** `dist/schema/*.gen.d.ts` shows enum literals as
  `n` (e.g. `StopReason = "…" | "n" | "cancelled"`). Don't trust grep there. Read the hand-written
  `dist/acp.d.ts`, or download the exact target to inspect cleanly:
  ```
  cd /tmp && npm pack @agentclientprotocol/sdk@<ver> && tar xzf *.tgz
  rg -n "type StopReason|deleteSession|SessionModelState" package/dist/schema/types.gen.d.ts package/dist/acp.d.ts
  ```
- **`node -e "require('<pkg>/package.json')"` may fail** on the SDKs (exports map blocks the subpath).
  Read `node_modules/<pkg>/package.json` directly for the installed version.
- **An ACP SDK bump can break code outside the claude adapter.** The whole `packages/agent` package
  must typecheck — expect to also fix `adapters/codex/*` and `server/agent-server.ts`. Keep those
  fixes minimal and behavior-preserving (e.g. when ACP removed the `models` response field, the codex
  adapter derived the model id from `configOptions` instead).

### 5. Port in phases — bug fixes first, then features

For each ported change:

- **Preserve divergences** (see `UPSTREAM.md` → Intentional Divergences + PostHog-only). The big ones:
  single-session `this.session` (not `this.sessions[id]`); `interruptReason` on cancel; gateway models
  via `fetchGatewayModels` (not `initializationResult.models`); `_posthog/*` ext notifications;
  the "Unsupported slash command" gate on `knownSlashCommands`; `SYSTEM_REMINDER` stripping; plan /
  questions / MCP-metadata machinery.
- **New SDK `system` subtypes are safe by default.** `handleSystemMessage` ends in `default: break`,
  and the prompt-loop top-level `switch (message.type)` only `unreachable()`s unknown top-level
  *types*. So a new subtype won't crash the loop — port real handling only where there's user value
  (e.g. `permission_denied` → failed tool_call, `tool_progress` → in_progress, `commands_changed` →
  available_commands_update, `mirror_error` → log).
- When upstream reads new fields (`stop_details`, `getContextUsage`, `thinking`), confirm the
  installed SDK `.d.ts` actually has them before porting. Skip ports the fork can't use (e.g. the
  fork doesn't read `MAX_THINKING_TOKENS`, so upstream's `resolveThinkingConfig` was N/A).
- Typecheck after each logical group, not just at the end.

### 6. Verify (all of it)

```
pnpm --filter agent typecheck
pnpm --filter agent build
npx biome check --write <changed files>      # biome is the formatter/linter, not prettier/eslint
pnpm typecheck                                # whole repo: confirms apps/code compiles vs the new ACP SDK
pnpm --filter agent test
pnpm --filter code test
```

- The `apps/code` renderer unit tests `analytics.test.ts` and `panelLayoutStore.test.ts` are **flaky**
  — they sometimes throw in `getElectronTRPC` / electron-trpc `ipcLink` depending on test ordering. If
  they fail, re-run; a clean rerun (or `git stash` + run on the clean tree) passing confirms it's the
  known flake, not your change.

### 7. Update `UPSTREAM.md` (do this last)

- Bump **Last sync** (version + HEAD sha + date) and the pinned **SDK** versions.
- Add `## Changes Ported in v<X> Sync` (one bullet per change, with PR # and short sha) and
  `## Skipped in v<X> Sync` (with the reason for each skip).
- If a port made a former divergence match upstream, move it out of the Intentional Divergences table.

## Fork facts worth remembering

- **Single session.** The agent owns one `this.session` (from `BaseAcpAgent`), not a `sessions` map.
  Upstream's per-session refactors usually collapse to "just use `this.session`".
- **Prompt loop is a persistent consumer** (since the v0.54.1 sync, upstream #780): `prompt()`
  enqueues a `Turn` deferred; `runConsumer` drains the query stream for the session's life, settles
  turns at their terminal `result`, and captures `query` + `session.queryGeneration` so the
  fork-only `refreshSession()` can retire it (bump generation → abort wake-up → end input). Steer
  mode, `interruptReason`, per-turn broadcast-at-activation and the unsupported-slash-command gate
  all live inside it — port upstream prompt-loop changes into the consumer, not a per-prompt loop.
- **ACP connection classes are the deprecated ones on purpose.** The fork stays on
  `AgentSideConnection`/`ClientSideConnection` (still shipped in ACP 1.x) because they carry the
  `extMethod`/`extNotification` surface `_posthog/*` uses; permission requests reach the client via
  the class's generic `request(..., { cancellationSignal })`. Don't port the `agent()` builder
  without a plan for the extension surface.
- **Renderer uses config options only.** Model/mode/effort selection is `SessionConfigOption` end to
  end; the renderer never reads the legacy `models` response field or calls `unstable_setSessionModel`.
  That's why upstream's ACP-0.24/0.25 model-state removals are safe to follow.
- **`toolUseCache` is never cleared** in the fork (created once in the constructor), so long sessions
  accumulate — keep the prune-at-tool_result behavior, and make any PostToolUse hook close over the
  data it needs rather than re-reading the cache.
- **Conversion is split out.** `claude-agent.ts` calls `handleSystemMessage` / `handleStreamEvent` /
  `handleResultMessage` / `handleUserAssistantMessage` from `conversion/sdk-to-acp.ts`. Upstream
  inlines all of this in `acp-agent.ts`.
- **Don't commit or push** unless the user explicitly asks. Leave the work on the current branch.
