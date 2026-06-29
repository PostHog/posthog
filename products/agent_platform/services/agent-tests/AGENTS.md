# agent-tests — e2e harness for the v2 agent platform

The single source of truth for whether the platform works. Real
everywhere except the model layer; one in-process cluster per test
case.

Read [docs/local-dev.md](../../docs/local-dev.md)
for the wider dev flow. This file is the test-side contract.

## The harness

[src/harness/cluster.ts](src/harness/cluster.ts) is the only thing
tests should construct. It boots the same impls prod runs, against
the local services `hogli start` brings up:

- **Real Postgres** at `agent_runtime_queue_test` (override with
  `AGENT_TEST_DB_URL`). Schema is **dropped + reapplied per test** —
  no leaked state between cases.
- **Real Redis** (`REDIS_URL`, defaults to `localhost:6379`) —
  `RedisSessionEventBus` with a per-cluster channel prefix so
  concurrent test files don't see each other's events.
- **Real Kafka** (`KAFKA_HOSTS`, defaults to `localhost:9092`) —
  `KafkaLogSink` against the `log_entries` topic. Tests assert on
  the wire payloads via the sink's `tap` callback (the harness
  captures into `c.logs.forSession(id)`) — we don't poll ClickHouse
  because the materialised view is async and flakey under load.
- **Real SeaweedFS / S3** (`AGENT_MEMORY_TEST_S3_*`, defaults to
  the SeaweedFS the dev stack ships) — `S3BundleStore` +
  `S3MemoryStore`, each rooted at a per-cluster random prefix that
  teardown wipes.
- **Real Express ingress + Worker loop + InProcessSandboxPool**.
  `InProcessSandboxPool`'s constructor refuses unless `NODE_ENV=test`
  (vitest sets it automatically). Prod uses Docker / Modal via
  `selectSandboxPool()`.
- **Real PiAiClient** pointed at pi-ai's `faux` provider — `c.setScript([...])`
  arms the next N responses.

The only mocked layer is the model — faux pi-ai. Everything else is
the prod impl against a real local service. There are no in-memory
queue / bundle / bus / log / identity / credential variants in the
codebase any more; constructing one is a build error.

## The "vital feature → case" rule

If a user can perceive a feature, it has a case in
[src/cases/](src/cases/). New trigger? Add `<trigger>-trigger.test.ts`.
New lifecycle state? Extend `lifecycle-edges.test.ts` or add a
sibling. New tool category? `native-tool.test.ts` covers the dispatcher;
add a case for the new family.

Don't reach for per-service unit tests for feature coverage — they
don't catch integration drift between ingress, runner, janitor. They're
fine for pure logic (spec parsing, sweep math) but a feature isn't
"covered" until it has a case here.

## The "every change ships with its test" rule

Tests aren't optional and they aren't a follow-up. Every code change in
`products/agent_platform/` ships with a test in the same commit:

- **Bug fix → regression test.** The test must fail when the fix is
  reverted. If reverting locally is annoying (formatter rewrites,
  hooks), mental-trace the assertion to prove the regression is
  caught — e.g. `expect(ctor).toHaveBeenCalledTimes(2)` would fail
  with `1` if the catch-and-clear weren't in place. State it explicitly
  in the commit message.
- **New helper / pure function → unit test.** Cover the obvious axes
  (input shape, edge cases, env fallbacks). Pure functions are cheap
  to test; "I'll add tests later" is how silent regressions ship.
- **New plumbing → at least one wire test.** When a value flows
  spec → AcquireOpts → SDK call (or any equivalent multi-hop), mock
  the downstream and assert the value lands at the destination.
- **E2E isn't a substitute for unit tests.** The harness is the
  source of truth for "does the feature work end-to-end"; unit tests
  are the source of truth for "is this single function's contract
  preserved." A new pure helper needs both: a unit test for the
  contract, and (if it changes user-visible behaviour) a harness
  case for the feature.
- **Run the test before declaring done.** "Wrote a test, didn't run
  it" is how broken assertions ship. Run the relevant test file
  before the commit, not the whole suite.

The pointer to "prefer top-level imports + `vi.doMock` over
`await import` inside `it` blocks" is the most common subtle vitest
trap when mocking modules that themselves use dynamic imports
(`sandbox-modal.ts` is the worked example). The mock registry is
consulted at the time the dynamic import inside the SUT runs, not at
the time the test file imports the SUT, so the dynamic-import
workaround inside tests is almost always unnecessary.

## Real-inference suite

[src/cases/real-inference.test.ts](src/cases/real-inference.test.ts)
runs the same harness against a real provider. It **runs by default**
and fails fast if no key is in env or repo-root `.env`. This is
deliberate — losing real-inference coverage is how silent pi-ai
integration drift sneaks in.

**Provider matrix.** Every provider with a configured key runs the
full case set — that's how we catch provider-specific drift (tool
schemas, stop reasons, system-prompt handling) end-to-end. Detected
keys (`POSTHOG_AI_GATEWAY_KEY`+`URL` / `ANTHROPIC_API_KEY` /
`OPENAI_API_KEY`) each contribute one `describe.each` row. Pin a
single provider with `REAL_INFERENCE_PROVIDER=anthropic|openai|gateway`
when iterating locally. Override the model with
`REAL_INFERENCE_MODEL_ID`. Skip the whole suite with
`AGENT_SKIP_REAL_INFERENCE=1`.

On macOS, Node's built-in `fetch` doesn't read the keychain trust
store and silently raises "Connection error." for every TLS handshake.
The suite auto-sets `SSL_CERT_FILE=/etc/ssl/cert.pem` at load if
neither `SSL_CERT_FILE` nor `NODE_EXTRA_CA_CERTS` is already set.

## Running

```bash
pnpm --filter @posthog/agent-tests test                      # full suite
pnpm --filter @posthog/agent-tests test cases/chat-trigger   # one file
pnpm --filter @posthog/agent-tests test -- -t 'multi-turn'   # by name
```

Vitest is configured with `fileParallelism: false` (cluster.ts uses a
shared pool; running files in parallel would race on schema drops).
Don't change this without rebuilding the pool model.

## Writing a new case

Minimal shape — start from [chat-trigger.test.ts](src/cases/chat-trigger.test.ts):

```ts
import { buildCluster, closeSharedPool, Cluster, fauxText } from '../harness'

describe('my feature: real e2e', () => {
  let c: Cluster
  beforeEach(async () => {
    c = await buildCluster()
  })
  afterEach(async () => {
    await c.teardown()
  })
  afterAll(async () => {
    await closeSharedPool()
  })

  it('does the vital thing', async () => {
    c.setScript([fauxText('canned response')])
    await c.deployAgent({ slug: 'x' })
    // ...fire trigger, drain, assert state.
  })
})
```

Helpers in [src/harness/faux.ts](src/harness/faux.ts): `fauxText`,
`fauxCallTool`, `fauxEndSession`. If you need a new one, add it
there — don't inline ad-hoc faux turns in cases.

## What goes where

| Concern                                          | File pattern                                                                               |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------ |
| Trigger surface (`/run`, `/webhook`, Slack, MCP) | `<trigger>-trigger.test.ts`                                                                |
| Lifecycle state machine                          | `lifecycle-edges.test.ts`, `worker-resume.test.ts`                                         |
| Tool dispatch + sandboxing                       | `native-tool.test.ts`, `custom-tool-sandbox.test.ts`, `dynamic-skills.test.ts`             |
| Auth + identity                                  | `auth.test.ts`, `strict-principal.test.ts`, `slack-identity.test.ts`, `cross-team.test.ts` |
| Janitor + sweep                                  | `janitor.test.ts`                                                                          |
| Logs + SSE                                       | `log-entries.test.ts`, `listen-sse.test.ts`                                                |
| Routing + control flow                           | `routing-edges.test.ts`, `control-flow.test.ts`, `queued-followups.test.ts`                |
| Real model                                       | `real-inference.test.ts` (don't add a second — extend this)                                |

If your new case doesn't fit any of these, you may be solving the
wrong problem — or you've found a new category, in which case add it
to this table.
