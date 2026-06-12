# Coding-agent continuity — working notes

Branch `feat/agent-platform-coding`. Design: `agent-sandbox-tiers.md`.

## What this is

Coding-enabled agents run the LLM loop inside a sandboxed harness (`@posthog/agent` /
`agent-server`, image `ghcr.io/posthog/posthog-sandbox-base`) instead of in-process.
Tier 1 supervisor (in-process) ↔ tier 2 harness over JSON-RPC `/command` + SSE `/events`.

## Done (committed)

- Worker integration + multi-turn driver + real-worker e2e
- agent.md persona injection (system prompt layering)
- Observability parity: structured transcript (text + toolCall + toolResult), `usage_total`,
  `$ai_generation`/`$ai_span`/`$ai_trace` (routed to the agent's own project)
- Fix: follow-up `/send` was replaying the original prompt (seeding bug) — `192dc0252f7`

## Now: conversational continuity on re-claim

Each completed session tears down its sandbox → a `/send` re-claim boots a _fresh_ harness with
no memory of prior turns (and no workspace state). Seeding is fixed (runs the right message) but
the harness answers cold. Goal: feed prior `session.conversation` into the harness on re-claim,
interim ahead of full sandbox snapshot/resume (lifecycle item #4, separate).

### Step 1 — investigate harness support

Source checked out at `/Users/benwhite/Development/code` (posthog/code, the `@posthog/agent` /
`agent-server`). Find: initial-messages / resume / session-load mechanism, or confirm we must
replay `session.conversation` as context into the first `user_message`. Decide smallest correct
approach.

### Step 2 — implement (TDD)

- Driver: `services/agent-runner/src/loop/coding-driver.ts` (`driveCodingSession`)
- On re-claim (conversation has prior assistant/toolResult turns), seed harness with history
  before the new user message.
- Unit test first: `coding-driver.test.ts` (fake pool, assert history reaches harness via
  `pool.sandbox.sent`). Then worker e2e (`services/agent-tests/src/cases/coding-agent.test.ts`)
  - real-harness e2e (`coding-supervisor.realharness.test.ts`).

## Key files

- `services/agent-runner/src/loop/coding-driver.ts` — driver (mirror of in-process `driver.ts`)
- `services/agent-shared/src/sandbox/coding/` — `contract.ts`, `acp-parse.ts`,
  `coding-sandbox-docker.ts`, `spec-to-launch.ts`
- Tests: `coding-driver.test.ts`, `acp-parse.test.ts`, `coding-supervisor.realharness.test.ts`,
  `agent-tests/src/cases/coding-agent.test.ts`

## Conventions

TDD; commit locally as you go (don't push unless asked); conventional commits ending
`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`. Tests: `hogli test <path>`
or `npx vitest run`. Lint: `npx --prefix services/agent-runner oxlint --quiet <files>`. Inference
proxies through sibling `ai-gateway` repo. Local seeded example agent: `agent-coder`.

## Backlog after continuity

- #2 MCP broker (native + custom tools) + skills file-delivery
- #3 approval gating end-to-end + stop/cancel
- #4 sandbox_instance persistence, snapshot/resume, Modal pool
