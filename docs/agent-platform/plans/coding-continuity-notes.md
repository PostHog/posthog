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

## State assessment (2026-06-12)

Architecture validated, dev vertical slice works end-to-end (real image, real model via local
gateway, full observability, multi-turn + continuity). Pre-v0 on the `agent-sandbox-tiers.md` §10
ladder. Deployability blockers, ranked:

1. ~~**Real gateway key in tier 2**~~ — DONE. §8 inference proxy shipped: ingress mounts
   `/inference/v1/*` (token-gated, session-liveness-checked, real key swapped in proxy-side,
   streaming pass-through, allowlisted paths); runner mints audience-bound session tokens
   (`agent-ingress.inference` on `AGENT_INTERNAL_SIGNING_KEY`) when
   `AGENT_CODING_INFERENCE_PROXY_URL` is set. Kill switch live: session not `running` → 403.
   Verified end-to-end against the real harness + gateway
   (`coding-inference-proxy.realharness.test.ts`). Remaining within this item: per-session
   token/cost budget at the proxy (needs a spec budget field — open q #2) and flipping local
   dev to proxy-by-default once ingress always runs alongside the runner.
2. **Docker-only pool** — runner pod would need a Docker socket; Modal pool is the prod substrate.
3. **No egress containment** — docker args have no network restrictions; agentsh allowlist not
   driven. With (1), full exfil path is open.
4. **Approvals auto-allow** — `coding-driver.ts` answers every `permission_request` with allow.
   Stop/cancel half-wired (`cancel` in `runCodingSession` only; no client-stop path, no hard-kill
   backstop).
5. **No sandbox_instance persistence** — worker crash orphans a running container; janitor can't
   reap.
6. **Capability gaps** — no tier-3 custom-tool MCP broker, skills not delivered as files, no repo
   clone/workspace provisioning in the driver path, no workspace snapshot/resume (continuity
   replays conversation only; files vanish between invocations).

## Sequenced backlog → v0 cut-line

v0 = read-only internal coding agents, deployable. Order:

1. ~~**Inference proxy (§8)**~~ — DONE (see above). Hosted on ingress (runner's no-HTTP rule
   ruled out endpoint-on-runner; no new deploy unit). Budget metering still open (q #2).
2. **Egress containment** — drive agentsh allowlist (proxy host + declared spec egress only) +
   docker network hardening. Pin model traffic to the proxy so a leaked token is useless.
3. **sandbox_instance persistence + janitor reaping** — record tier-2 containers (`tier`/`kind`),
   reap orphans on worker crash. Existing `PgSandboxInstanceStore` + janitor sweep pattern.
4. **Stop/cancel end-to-end** — client stop → supervisor `cancel` → verify in-flight model call
   halts → hard-kill backstop (`docker rm -f` / Modal terminate). Proxy rejects further inference
   for stopped sessions (ties into 1).
5. **Per-session cost cap at the proxy** — assuming the gateway scoped-tokens RFC
   (`gateway-scoped-tokens.md` / RFC repo PR #1167) does NOT land, the proxy is the permanent
   budget choke point: add `spec.limits.max_cost_usd`; the proxy auth middleware already loads
   the session row per request, so reject when `usage_total.cost_total` exceeds it. Granularity
   is per-turn (usage persists at turn end) — acceptable since wall limits + `max_output_tokens`
   bound a single turn. Pairs with (4): together they complete the kill-switch story.
6. **Modal pool** — `ModalCodingSandboxPool` behind the same `CodingSandboxPool` interface.
   Gates fleet deploy; until then v0 can run on a Docker-capable VM if we accept that interim.

No-gateway-change caveat: the proxy also becomes production-load-bearing — every coding-agent
inference stream is a long-lived SSE connection through ingress pods. Fine at internal scale;
needs a capacity look (or its own deploy knob) before broad rollout.

——— v0 cut-line ———

7. **Approval gating end-to-end** (#3) — `permission_request` → existing approval queue/resume
   machinery; human principal only. Gates any write-capable profile (v1).
8. **Tier-3 custom-tool MCP broker + skills file-delivery** (#2) — broker endpoint on the
   supervisor fronting the existing `SecretBroker`/tier-3 sandbox; skills written into the
   workspace at boot.
9. **Workspace provisioning + snapshot/resume** (#4 rest) — repo clone at pinned ref in the
   driver path; sandbox snapshot on suspend/complete, restore on re-claim (replaces the interim
   conversation-replay preamble's "fresh environment" caveat).
