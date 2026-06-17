# Agent platform — local dev + testing

This is the working guide for hacking on the v2 agent platform locally:
how the pieces fit, how to bring up the stack, how to drive it end-to-end
(including via the local MCP server), and how to add a test for any new
vital feature so future regressions land with the change that broke them.

This doc is dev-mode only.

## The stack at a glance

```text
┌─────────────────────────────────────────────────────────────────────┐
│ Django (products/agent_platform)                                       │
│   models.py · serializers.py · api.py · janitor_client.py           │
│   owns: agent_application, agent_revision (POSTHOG_DB)              │
│   exposes: /api/projects/<team>/agent_applications/...              │
│   proxies bundle + native_tools reads through janitor_client        │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTP (x-internal-secret)
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ products/agent_platform/services/agent-janitor          (port 3031)                         │
│   /revisions/* authoring API · /native_tools · /healthz             │
│   sweeps stuck running/waiting sessions on a timer                  │
└─────────────────────────────────────────────────────────────────────┘
                              │ writes to AGENT_DB
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ products/agent_platform/services/agent-ingress          (port 3030)                         │
│   /agents/<slug>/run · /send · /listen (SSE) · /webhook · MCP       │
│   resolves slug → application + live revision → enqueues session    │
└─────────────────────────────────────────────────────────────────────┘
                              │ enqueues to AGENT_DB.agent_session
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ products/agent_platform/services/agent-runner            (no inbound HTTP)                  │
│   Worker loop: claim → load revision + bundle → pi-ai call →        │
│     dispatch native/custom tools → write conversation → publish     │
│     lifecycle events → loop or park                                 │
└─────────────────────────────────────────────────────────────────────┘
```

Shared building blocks (queue, bundle store, sandbox pool, spec
schema, log sink) live in [products/agent_platform/services/agent-shared](../../../products/agent_platform/services/agent-shared/).
Tools the runner can dispatch (`@posthog/query`, `@posthog/meta-*`,
etc.) live in [products/agent_platform/services/agent-tools](../../../products/agent_platform/services/agent-tools/).

### Two databases

- **POSTHOG_DB** — Django-owned. Tables: `agent_application`,
  `agent_revision`. Written by Django; read by ingress + runner.
- **AGENT_DB** — node-owned. Tables: `agent_session`, `agent_user`,
  `agent_sandbox_instance`, `agent_tool_approval_request`. Schema is
  managed by [@posthog/agent-migrations](../../../products/agent_platform/services/agent-migrations/);
  the runner applies pending migrations on boot (idempotent).

In dev they're the same Postgres (`postgres://posthog:posthog@localhost:5432`),
just two databases: `posthog` and `agent_runtime_queue`. In prod they're
separate physical instances.

## Bringing it up

The three node services are wired into [bin/mprocs.yaml](../../../bin/mprocs.yaml)
under the `agent_runtime` capability. Pick that capability in `hogli
dev:setup` and `hogli start` (or `./bin/start`) gives you:

```text
agent-ingress     → http://localhost:3030     (PORT=AGENT_INGRESS_PORT)
agent-janitor     → http://localhost:3031     (PORT=AGENT_JANITOR_PORT)
agent-runner      → no HTTP, watches the queue
migrate-agent-runtime → applies AGENT_DB migrations once on boot
```

Standalone (without phrocs) if you only want the agent services:

```bash
pnpm --filter @posthog/agent-runner start:dev
pnpm --filter @posthog/agent-ingress start:dev
pnpm --filter @posthog/agent-janitor start:dev
```

Each defaults to localhost Postgres on the two databases above.

### Healthchecks

```bash
curl -s localhost:3030/healthz   # ingress
curl -s localhost:3031/healthz   # janitor
```

The runner doesn't expose HTTP — check its mprocs pane for
`starting worker loop` (the `ready_pattern`).

### Local ai-gateway (optional)

The runner can route every model call through PostHog's external Go
[ai-gateway](https://github.com/PostHog/ai-gateway) instead of going
direct to providers. Useful if you're working on gateway integration,
billing/quota plumbing, or `$ai_origin` analytics. Off by default —
the runner uses direct providers when `AGENT_USE_AI_GATEWAY=false`.

To turn it on:

1. **Clone the sibling repo** at `~/Development/ai-gateway`
   (override with `AI_GATEWAY_REPO`).
2. **Create `~/Development/ai-gateway/.env`** with provider keys:

   ```bash
   AI_GATEWAY_AUTH_MODE=open
   AI_GATEWAY_ANTHROPIC_API_KEY=sk-ant-...
   AI_GATEWAY_OPENAI_API_KEY=sk-proj-...
   ```

   Note the `AI_GATEWAY_*` prefix — older docs/scripts referenced
   `LLM_GATEWAY_*`, which is inert against the current compose file.

3. **Enable the `ai_gateway` capability** in `hogli dev:setup` so the
   `ai-gateway` mprocs entry runs. It executes
   [`bin/start-ai-gateway`](../../../bin/start-ai-gateway) which
   brings up `docker compose --profile full` (gateway + billing +
   deps) and seeds the anonymous-team ledger with $100 so requests
   pass admission. Idempotent — runs cleanly on every restart.
4. **Flip `AGENT_USE_AI_GATEWAY: 'true'`** on the agent-runner entry
   in [bin/mprocs.yaml](../../../bin/mprocs.yaml).

How model routing works:

The gateway is a drop-in proxy — point an existing provider SDK at
`<gateway>/v1` and send the provider-native SKU as `model`. The
runner mirrors that contract: pi-ai resolves `spec.model` to a Model
with the correct api shape per provider (`openai-completions` /
`openai-responses` / `anthropic-messages`), and
[`posthogAiGatewayModel`](../../../products/agent_platform/services/agent-runner/src/models/ai-gateway-model.ts)
overrides only `baseUrl` (with the shape-appropriate suffix) and the
`provider` tag. OpenAI agents hit `/v1/chat/completions` or
`/v1/responses`; Anthropic agents hit `/v1/messages` — all on the
same gateway.

If the gateway returns `unknown model` for a model that works direct,
the gateway's `modelTable` (`ai-gateway/internal/router/chain.go`)
needs a SKU alias for pi-ai's name (e.g. pi-ai says
`claude-sonnet-4-6`, the gateway's primary SKU for the same model
is `claude-sonnet-4-5`). Ping the ai-gateway team — it's a one-line
addition.

## Driving the stack: three paths

### 1. `bin/run-agent` — the smoke test

Fires a chat trigger against the canned dev revision and tails SSE:

```bash
bin/run-agent                            # default app (slug=demo)
bin/run-agent --input='{"foo":"bar"}'
bin/run-agent --no-listen                # skip SSE tail
```

Validates the full ingress → queue → runner → bus → SSE path with one
command. Reach for this first when anything changes in any of the three
services.

### 2. Local MCP — end-to-end via an MCP client

The `agent_platform` Django endpoints (`/api/projects/<team>/agent_applications/...`)
are exposed as MCP tools, generated from the OpenAPI schema into
[services/mcp/src/tools/generated/agent_platform.ts](../../../services/mcp/src/tools/generated/agent_platform.ts).
That means once the local MCP server is running, an MCP client (Claude
Desktop, MCP Inspector, claude.ai) can:

- create + list agent applications
- create draft revisions, write bundle files via the janitor proxy
- freeze + promote
- (downstream) trigger them via ingress

Bring up the MCP server alongside the agent stack:

```bash
# Already wired into hogli — select the mcp_server capability.
# Or standalone:
cd services/mcp && pnpm run dev          # → http://localhost:8787/mcp
cd services/mcp && pnpm run inspector    # web UI to call tools by hand
```

Wire Claude Desktop or Claude Code (see [services/mcp/CONTRIBUTING.md](../../../services/mcp/CONTRIBUTING.md#testing-with-claude-desktop-macos)).
The same config shape works for Claude Code — add the server to
`~/.claude/settings.json` or a project-level `.mcp.json`:

```json
{
  "mcpServers": {
    "posthog-dev": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "http://localhost:8787/mcp",
        "--header",
        "Authorization: Bearer <your_local_personal_posthog_key>"
      ]
    }
  }
}
```

Then in the MCP client you can issue real authoring tool
calls against your local Django + janitor. This is the path
to use when reproducing what an authoring AI would see, or when
validating that a Django serializer change flowed through to the MCP
tool surface (`hogli build:openapi` regenerates [services/mcp/src/generated/agent_platform/api.ts](../../../services/mcp/src/generated/agent_platform/api.ts)).

When you change a serializer or viewset under `products/agent_platform/backend/`,
**always rerun `hogli build:openapi`** before testing via MCP — the MCP
tool schemas come from the generated OpenAPI and silently drift otherwise.

### Gap: no MCP tools for invoking a created agent

The `agent_platform` MCP surface today is **authoring-only** — `agent-applications-*`
and `agent-applications-revisions-*` cover create / edit bundle / freeze /
promote, but there is no MCP tool that wraps the ingress runtime endpoints
(`/agents/<slug>/run`, `/send`, `/listen`). After an authoring harness like
Claude Code creates and promotes an agent via MCP, it has no in-band way to
then talk to it — the next step ("invoke the thing I just built") is not
discoverable from the tool list.

Workarounds until invocation tools land:

- `bin/run-agent --slug=<your-slug>` from a terminal pane.
- `curl -XPOST localhost:3030/agents/<slug>/run -d '{"message":"hi"}'` plus
  `curl -N localhost:3030/agents/<slug>/listen?session_id=...` for SSE.
- The [`agent-authoring-flow.md`](../plans/agent-authoring-flow.md) plan
  covers the proper fix: dedicated `agent-invoke` / `agent-send` /
  `agent-listen` MCP tools (and a scripted test-run surface) so the
  authoring AI can iterate end-to-end without leaving MCP.

## E2E tests — `products/agent_platform/services/agent-tests`

Every vital platform feature has a case in
[products/agent_platform/services/agent-tests/src/cases/](../../../products/agent_platform/services/agent-tests/src/cases/).
The harness ([src/harness/cluster.ts](../../../products/agent_platform/services/agent-tests/src/harness/cluster.ts))
boots ingress + runner + janitor in-process against a real test DB,
real filesystem, real express, real Worker, real PiAiClient — mocked
**only** at the model layer via pi-ai's `faux` provider. You arm the
script per test:

```ts
c.setScript([fauxText('hello world')])
await c.deployAgent({ slug: 'echo' })
const res = await request(c.ingress).post('/agents/echo/run').send({ message: 'hi' })
await c.drain()
```

Run them:

```bash
pnpm --filter @posthog/agent-tests test                 # full suite (faux)
pnpm --filter @posthog/agent-tests test cases/chat      # one case file
```

Requires `agent_runtime_queue_test` to exist locally (`bin/migrate
--scope=agent_runtime` creates `agent_runtime_queue`; the test DB is a
sibling). The harness drops + reapplies schema per test, so DB state
is never shared between tests.

### Vital-feature coverage rule

If a feature is user-visible and could regress (a new trigger type, a
new lifecycle state, a new tool category, a routing edge), it needs a
case in `src/cases/`. The naming is one-file-per-concern — see existing
files: `chat-trigger`, `slack-trigger`, `worker-resume`, `strict-principal`,
`approval-gated` (when it lands), etc. Add yours next to them.

### Real-inference variant

[src/cases/real-inference.test.ts](../../../products/agent_platform/services/agent-tests/src/cases/real-inference.test.ts)
runs the same harness against a real provider model. **It runs by
default and fails if no provider key is found** — that's the only way
to know v2 talks to a real model end-to-end. Key discovery order:

1. `POSTHOG_AI_GATEWAY_KEY` + `POSTHOG_AI_GATEWAY_URL` → ai-gateway
2. `ANTHROPIC_API_KEY` → Anthropic (default `claude-sonnet-4-6`)
3. `OPENAI_API_KEY` → OpenAI (default `gpt-4o-mini`)

`.env` at the repo root is loaded automatically.

Opt out in CI without provider creds: `AGENT_SKIP_REAL_INFERENCE=1`.
**Do not opt out by default in local runs** — losing real-inference
coverage is how silent drift in pi-ai integration sneaks in.

### Per-service unit tests

The harness covers the platform integration story. Per-service unit
tests live alongside each service:

```bash
pnpm --filter @posthog/agent-runner test
pnpm --filter @posthog/agent-ingress test
pnpm --filter @posthog/agent-janitor test
pnpm --filter @posthog/agent-shared test
```

Use these for pure-function logic (spec parsing, sweep thresholds,
auth predicates). Anything that crosses two services belongs in
`agent-tests`, not in a per-service test.

## Debugging recipes

- **Session stuck in `available`** — runner not picking it up. Check
  the runner pane for errors, and verify `AGENT_DB_URL` matches the
  DB the ingress wrote to.
- **`session.revision_missing` in runner logs** — `POSTHOG_DB_URL`
  is wrong, or you enqueued against a revision that isn't `live`.
- **Janitor 401 on `/native_tools`** — `AGENT_INTERNAL_SIGNING_KEY`
  (Django) doesn't match the same env var in the janitor. Django mints
  an `aud=agent-janitor.rpc` JWT signed with the key; the janitor
  verifies with it. Both sides must agree.
- **MCP tool schema looks stale** — rerun `hogli build:openapi` after
  changing a serializer. The MCP generated files don't watch.
- **`/listen` SSE returns nothing across hosts** — `REDIS_URL` isn't
  set on both ingress and runner. `RedisSessionEventBus` is the only
  bus impl now; both processes must point at the same Redis.

## Where the canonical docs live

- This file — local dev + testing.
- [../plans/\_ROADMAP.md](../plans/_ROADMAP.md) — what we're building next.
- [products/agent_platform/CLAUDE.md](../../../products/agent_platform/CLAUDE.md) — Django-side rules.
- [products/agent_platform/services/agent-tests/CLAUDE.md](../../../products/agent_platform/services/agent-tests/CLAUDE.md) — test conventions.
