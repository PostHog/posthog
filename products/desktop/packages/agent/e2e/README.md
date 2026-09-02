# Live agent e2e suite

Drives representative sessions **end to end** through the real adapter, the real
binary (codex `app-server` / Claude Code CLI), and the real llm-gateway on a cheap
model — parametrized across `claude` and `codex`. The only thing mocked is the
host/UI client (a recording `sessionUpdate`, an auto-allow `requestPermission`,
and real file read/write against a throwaway git repo). Nothing in the
agent/model/tool path is stubbed.

## What it covers

Four suites. The two adapter-parametrized ones loop with `describe.skipIf` over
`["claude", "codex"]` (titles carry a `(claude)` / `(codex)` marker so
`-t "(codex)"` selects one arm across files); `compaction.e2e.test.ts` runs the
codex arm only, and `guard.e2e.test.ts` always runs:

`session-lifecycle.e2e.test.ts` — one shared golden turn plus focused scenarios:
- **newSession config options** — model / effort selectors are offered.
- **working turn** — `initialize → newSession → prompt` (read a file, edit a
  line, run a command): streamed assistant text, tool calls + a completed tool
  call, the exact usage signal, `stopReason: end_turn`, the real on-disk file
  edit, and (codex) the `_posthog/sdk_session` + `_posthog/turn_complete`
  ext-notifications.
- **setSessionConfigOption** — switching a config option is accepted + acked.
- **interrupt** — `cancel` during an in-flight (unbounded) turn yields `cancelled`.
- **resumeSession** — reconnect returns config options.
- **loadSession** — a fresh connection reattaches and the transcript replays
  (asserts the tool transcript replays, not just any update).

Codex-only (advertised codex capabilities; registered as skipped on the claude
arm so the gap is visible):
- **mode switch** → `current_mode_update`.
- **steering** — a mid-turn prompt folds into the running turn via `turn/steer`.
- **list + fork** — `listSessions` finds the session; `forkSession` branches it.

The command/file approval `{decision}` round-trip is **not** covered here: codex
spawns under a `danger-full-access` sandbox and auto-approves, so it never sends
an approval request to assert on. That envelope is covered by unit tests instead.

`structured-output.e2e.test.ts` — `_meta.jsonSchema` + `onStructuredOutput`
delivers a parsed, schema-constrained object (the signals-pipeline contract).
Runs on the strong model (`E2E_*_STRONG_MODEL`); the cheapest models hang on
the constrained decode.

`compaction.e2e.test.ts` — codex only: a low `auto_compact_token_limit` plus a
big input blob trips auto-compaction, and the adapter must surface
`_posthog/compact_boundary`.

`guard.e2e.test.ts` — always runs: fails loudly when the token is missing (every
arm would self-skip) or the codex binary is absent despite a token, so the suite
can never skip itself green.

Assertions are structural lifecycle invariants + the deterministic file/JSON
side effects — never model prose — so they hold across adapters and cheap models.

## Structure

- `config.ts` — gateway/token/model resolution, per-adapter env wiring, skip logic.
- `driver.ts` — the in-process ACP host client (recording capture, auto-allow,
  real FS), `openConnection` / `openSession` helpers, the throwaway-repo helpers,
  and `waitFor`.
- `*.e2e.test.ts` — the scenarios.

## Running

These never run under `pnpm test` or per-PR CI (the default vitest config only
includes `src/**`). They are opt-in and cost a couple of short model turns.

In CI they run as the **`e2e` job in `.github/workflows/test.yml`**, on pull
requests only, after the unit + integration jobs pass. The job is opt-in and safe
by default: it self-skips unless the repo variable `AGENT_E2E_ENABLED` is `true`
with an `POSTHOG_CODE_E2E_GATEWAY_PERSONAL_API_KEY` secret and an `POSTHOG_CODE_E2E_GATEWAY_URL` variable pointing at a
gateway reachable from the runner, and it never runs for fork PRs (their secrets
are withheld, which would otherwise red the fail-loud token guard). Off by
default, so it costs nothing until explicitly enabled; the codex arm self-skips if
the native binary isn't on the runner.

```bash
# from packages/agent — reads the local dev API key from the posthog repo, runs both arms
bash e2e/run-e2e.sh

# just one adapter (matches the (codex) / (claude) marker in every title)
bash e2e/run-e2e.sh -t "(codex)"
```

Prereqs: a local llm-gateway up (`./bin/start` in the posthog repo) and the
native codex binary present at `apps/code/resources/codex-acp/codex` (the codex
arm self-skips if it is missing).

## Configuration (env)

| Var | Default | Notes |
| --- | --- | --- |
| `POSTHOG_CODE_E2E_GATEWAY_PERSONAL_API_KEY` | — | Required. A token the gateway accepts — the `ci` product takes a personal API key (no OAuth). Without it every arm skips. `run-e2e.sh` reads the local dev key. |
| `POSTHOG_CODE_E2E_GATEWAY_URL` | `http://localhost:3308/ci` | Gateway base (codex appends `/v1`). `ci` accepts a personal API key; `posthog_code` is OAuth-only. |
| `POSTHOG_CODE_E2E_CLAUDE_MODEL` | `claude-haiku-4-5` | Override if the gateway serves a different cheap Claude id. |
| `POSTHOG_CODE_E2E_CODEX_MODEL` | `gpt-5-mini` | Cheapest codex id the local gateway serves; override if needed. |
| `POSTHOG_CODE_E2E_CLAUDE_STRONG_MODEL` | `claude-sonnet-4-5` | Stronger Claude id for tests the cheap model can't handle (structured output). |
| `POSTHOG_CODE_E2E_CODEX_STRONG_MODEL` | `gpt-5.5` | Stronger codex id for the same tests. |
| `POSTHOG_REPO` | sibling `../posthog` | Where `run-e2e.sh` reads the local dev key from. |
| `E2E_DEBUG` | — | `1` for verbose adapter logging. |

If a default model isn't served by your gateway, the turn fails loudly (never a
false green) — set the matching `E2E_*_MODEL`.

Each arm self-skips with a visible reason (missing token / missing binary) rather
than passing silently.
