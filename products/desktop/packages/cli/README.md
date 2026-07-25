# @posthog/code-cli

Headless CLI for PostHog Code: one agent turn against a local repository, prompt in, answer on stdout, exit code out. Drives the same in-process ACP connection the desktop app uses.

```bash
posthog-code-cli "Fix the failing test" --cwd ~/src/myrepo
```

The prompt can also come from stdin:

```bash
echo "Summarize the last commit" | posthog-code-cli --cwd ~/src/myrepo
```

## Flags

| Flag | Default | Notes |
| --- | --- | --- |
| `[prompt]` | reads stdin when piped | Positional. Quote it; multiple words without quotes are an error. |
| `--cwd <path>` | current directory | Must exist and be a directory. Resolved to its realpath. |
| `--permission-mode <mode>` | `auto` | `auto` or `bypassPermissions`. Interactive modes need a UI to answer prompts, so they are rejected. |
| `--model <id>` | session default | Must start with `claude-`. An id that isn't available is substituted, and the adapter warns (visible with `--debug`). |
| `--system-prompt <text>` | preset | Replaces the default system prompt. |
| `--output <format>` | `text` | `text` streams as it arrives; `json` emits one document. |
| `--debug` | off | Verbose diagnostics on stderr. |

## Output

stdout carries only assistant output. Every diagnostic goes to stderr, so `--output json` is safe to pipe.

`--output text` streams each assistant chunk as it arrives and terminates with a newline. `--output json` buffers and emits a single document:

```json
{ "text": "…", "stopReason": "end_turn", "usage": null, "sessionId": "…" }
```

`usage` is `null` rather than absent when the turn settled without token counts, so `.usage` is always safe to read. Nothing is written on a hard mid-turn failure, so check the exit code before parsing.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | `end_turn` |
| 1 | Bad arguments, no prompt, or an unexpected failure (reason on stderr) |
| 2 | `refusal` |
| 3 | `max_tokens` or `max_turn_requests` |
| 130 | SIGINT |
| 143 | SIGTERM |

Both signals cancel the turn and tear the agent subprocess down before exiting.

## Authentication

Auth comes from the environment and is passed to the agent subprocess:

- `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN`
- `ANTHROPIC_BASE_URL` to point at a gateway

With neither key set, the CLI warns and falls back to a stored `claude` login credential.

## Unattended behavior

There is no user to answer prompts, so:

- Tool permissions that reach the client are auto-approved, preferring `allow_once` so a run never persists allow-always rules into the target repo's settings. See `resolveUnattendedPermissionRequest` in `@posthog/agent`.
- `AskUserQuestion` calls are parked: the model is told to restate the question as text and end its turn rather than answer on the user's behalf.
- `bypassPermissions` as root outside a sandbox fails fast, matching what the agent subprocess would refuse anyway. Set `IS_SANDBOX=1` if that is genuinely the situation.

## Development

```bash
pnpm --filter @posthog/code-cli build      # tsup -> dist/cli.js
pnpm --filter @posthog/code-cli test       # vitest, src/**/*.test.ts
pnpm --filter @posthog/code-cli typecheck
```

`pnpm --filter @posthog/code-cli test:e2e` runs a live turn against the built binary. It needs `POSTHOG_CODE_E2E_GATEWAY_PERSONAL_API_KEY` (same env contract as `packages/agent/e2e`) and fails rather than skipping when it is unset.
