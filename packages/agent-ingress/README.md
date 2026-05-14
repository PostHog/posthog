# @posthog/agent-ingress

Public-facing HTTP process for the PostHog agent platform.

- All `*.agents.posthog.com` traffic terminates here.
- Resolves the inbound host to `(application, revision)` via the Django internal API.
- Implements `/run`, `/listen/:id`, `/send/:id`, `/webhooks/:provider`, `/health`, `/status`.
- Writes an `agent_sessions` row + enqueues a session job in `@posthog/agent-core`'s queue.
- Streams session events out via SSE, backed by the session bus (Redis in prod, in-memory in tests).

## Hard rules

- **No Anthropic / Claude Agent SDK / Modal imports.** Enforced by `eslint-plugin-no-restricted-imports`. The whole point of splitting from the runner is to keep the blast radius small.
- **Never decrypts a secret.** Secret material only lives in `@posthog/agent-runner`.
- **No imports from `nodejs/`.** Cherry-pick by copy if you ever need something from it.

See [`docs/internal/agent-platform.md`](../../docs/internal/agent-platform.md) for the full architecture.
