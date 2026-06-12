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

## Done: conversational continuity on re-claim

Shipped. Investigation (posthog/code at `/Users/benwhite/Development/code`): the harness's only
resume path (`POSTHOG_RESUME_RUN_ID`) fetches the prior run's log from the PostHog API, then just
formats the conversation as markdown into the first prompt (`packages/agent/src/resume.ts` +
`agent-server.ts` `sendResumeMessage`). No structured history-injection API; Claude SDK native
`resume` not exposed. So: supervisor does the same formatting itself.

- `services/agent-shared/src/sandbox/coding/resume-context.ts` —
  `formatConversationForResume` (markdown history, tool results folded + truncated, char budget)
  - `buildResumePrompt` (harness-matching preamble, so its `isResumeContextTurn` detection
    recognizes these turns if native resume lands later).
- `coding-driver.ts`: on re-claim (prior assistant turns), wraps ONLY the first wire send;
  persisted transcript + analytics keep the raw message.
- Tests: formatter unit (`resume-context.test.ts`), driver unit (re-claim wrap, raw later sends),
  worker e2e (`coding-agent.test.ts` re-claim case via real ingress /send), real-harness e2e
  (codeword recalled from replayed history by a cold harness).

Workspace state still NOT restored on re-claim (preamble says so) — that's snapshot/resume (#4).

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
