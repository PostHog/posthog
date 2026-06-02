# Design — self-hosted tool runners (customer-hosted MCP via outbound poll)

**Status:** draft. **Owner:** ben.
**Companion to:** [`runtime-mcps.md`](runtime-mcps.md) — which solves the
publicly-reachable MCP case. This plan solves the **not publicly reachable**
case (Grafana, Kubernetes, internal-only APIs).

> **Names considered:** "secure tools" (Ben's first framing), "private MCPs",
> "tool bridges", "tunneled MCPs". Settled on **self-hosted tool runner**
> because (a) the user-facing object the customer deploys is a _runner
> process_; (b) "self-hosted" describes _where it runs_, which is the
> meaningful property; (c) "private" is overloaded (memory tier, network
> posture, public/internal endpoints) and didn't carry its weight.

## Problem

`runtime-mcps.md` lets a spec author wire an `mcps[]` entry pointing at a
publicly-reachable MCP endpoint. The runner opens a client at session start
and round-trips through it. For SaaS MCPs (GitHub, Linear, Stripe, Sentry)
that's fine.

For the SRE-bot v1 (Grafana + Kubernetes), the integrations our SRE bot
_most needs_, this fails:

- Grafana lives behind the corp VPN or an `internal-only` ALB.
- The k8s API server is not reachable from outside the VPC.
- Customers rightly refuse to punch holes or expose them via a public proxy.

Result: SRE bot can't reach the systems it exists to observe. Every "ops"
shaped agent (warpstream-forecasting, financial-reconciliation talking to
on-prem banking, gap-analysis hitting internal Zendesk SSO, etc.) hits the
same wall.

## Proposed shape

Customer deploys a small process — the **tool runner** — inside their own
network. It establishes an outbound connection to PostHog, registers the
tools it can serve, heartbeats, and long-polls for invocations. When the
agent calls a tool wired to that runner, PostHog enqueues the invocation;
the runner picks it up, executes locally (typically by forwarding to a
local MCP server), and posts the result back.

Wire shape: **outbound HTTPS only**. No inbound ports on the customer side.
Same pattern Temporal workers, GitHub Actions self-hosted runners, and
Cloudflared tunnels use — well-understood, firewall-friendly.

```text
                        ┌─────────────────────┐
                        │  PostHog agent      │
                        │  (agent-runner)     │
                        └──────────┬──────────┘
                                   │  tool_call(name, args)
                                   ▼
                        ┌─────────────────────┐
                        │  PostHog ingress    │
                        │  + tool_invocation  │── enqueue ──┐
                        │  table              │             │
                        └──────────▲──────────┘             │
                                   │  result POST           │
                                   │                        │
                       outbound    │            long-poll   │
                       HTTPS only  │            HTTPS GET   │
                                   │                        │
                ┌──────────────────┴────────────────────────┴──┐
                │  Customer VPC                                │
                │                                              │
                │   ┌──────────────┐    ┌──────────────────┐   │
                │   │ posthog-tool │───▶│ Grafana / k8s /  │   │
                │   │   -runner    │    │ custom MCP / sh  │   │
                │   └──────────────┘    └──────────────────┘   │
                └──────────────────────────────────────────────┘
```

## Spec-side: a new `McpRef` kind

Today [`McpRefSchema`](../../../services/agent-shared/src/spec/spec.ts#L213) has
`agent` and `external`. Add a third:

```typescript
z.object({
  kind: z.literal('self-hosted'),
  // The runner's stable slug, e.g. 'grafana-prod' or 'k8s-staging'.
  // Must already exist under the same project; freeze-time validation
  // checks the runner is registered.
  runner: z.string(),
  // Optional: subset of the runner's catalog to expose.
  // Empty = expose every tool the runner registered.
  tools: z.array(z.string()).default([]),
  // Per-MCP approval policy. Three cases all fall out of one shape:
  //   omitted              → no tool needs approval
  //   { default: 'always' } → every tool needs approval
  //   { default: 'never', by_tool: { restart: 'always' } }
  //                        → allowlist-style: approve specific tools only
  // Threads into the SAME approval_policy machinery as native tools;
  // this just declares which tools enter it.
  approval: z
    .object({
      default: z.enum(['never', 'always']).default('never'),
      by_tool: z.record(z.string(), z.enum(['never', 'always'])).default({}),
    })
    .default({ default: 'never', by_tool: {} }),
})
```

Spec author writes:

```yaml
mcps:
  # Read-only Grafana — no approval needed.
  - kind: self-hosted
    runner: grafana-prod
    tools: [query_loki, query_prometheus, get_dashboard_by_uid]

  # Mixed k8s — reads are free, writes need a human nod.
  - kind: self-hosted
    runner: k8s-staging
    tools: [pods_list, pods_logs, deployments_restart, exec]
    approval:
      default: never
      by_tool:
        deployments_restart: always
        exec: always

  # Bank-account-shaped tool — every call gated.
  - kind: self-hosted
    runner: stripe-finance
    tools: [issue_refund, void_invoice]
    approval:
      default: always
```

See **Approval flow** below for how this threads into the existing
approval gate.

## Transport is private to the client

**The architectural contract: from the dispatcher's perspective, calling a
self-hosted tool is indistinguishable from calling an external one.** Same
surface, same blocking semantics, same error model.

This is enforced by treating the MCP client as the abstraction. Concrete
impls vary in transport; the dispatcher does not branch on `kind`.

```typescript
interface McpClient {
  callTool(name: string, args: object, opts: { timeout_ms: number }): Promise<unknown>
  listTools(): Promise<ToolDescriptor[]>
  close(): Promise<void>
}

// runtime-mcps.md — opens stdio/sse/ws via the official MCP SDK.
class ExternalMcpClient implements McpClient {
  /* ... */
}

// This plan — enqueues an invocation, awaits a SessionEventBus result event,
// gives up on timeout. No persistent socket; at session start it verifies
// the runner is `live` (recent heartbeat) and fetches the cached catalog so
// `listTools()` works the same way as the external variant.
class SelfHostedMcpClient implements McpClient {
  /* ... */
}
```

Sketch of `SelfHostedMcpClient.callTool`:

```typescript
async callTool(name, args, { timeout_ms }) {
  const invocationId = await ingress.enqueue({ runner: this.slug, name, args })
  const waiter = this.bus.waitForResult(invocationId, { timeout_ms })
  const settled = await waiter
  if (settled.timedOut) {
    // Best-effort cancel signal; the row stays leased until lease-expiry,
    // janitor sweeps it. Log loudly either way.
    ingress.publishCancel(invocationId).catch(noop)
    throw new ToolTimeoutError(name, timeout_ms)
  }
  if (settled.error) throw new ToolError(settled.error)
  return settled.result
}
```

What this buys:

- **`run-turn.ts` does not change.** It calls `client.callTool()` and
  awaits. The latency budget (`timeout_ms` per tool) governs everything;
  a sub-second Grafana query and a five-minute k8s rollout both fit, with
  no polling tax between them.
- **Future transports are new clients, not new branches.** A WebSocket
  variant later, a Cloudflared-tunnel variant, a NAT-traversal variant —
  each is a new `McpClient` impl. `run-turn.ts` keeps not caring.
- **Crash recovery is uniform.** On session re-lease the runner queries
  `tool_invocation` rows in non-terminal state belonging to this session,
  re-subscribes to the bus for each. The bus carries the live signal;
  Postgres is the durable source of truth. Same pattern as approvals.

## Runner-side: what the customer deploys

### The platform contract

A runner is anything that:

1. **Authenticates + heartbeats.** Pre-shared bearer token; each heartbeat
   declares its tool catalog and liveness.
2. **Long-polls for invocations.** Open HTTPS GET, blocked on the PostHog
   side up to ~30 s. Server-side push with outbound-only semantics.
3. **Reports.** POSTs `result` (with `extend_lease` for long-running work).

That's the whole protocol. Languages, frameworks, internal architecture
all live below it. **How the runner produces tool results is intentionally
outside the platform contract** — it can shell out, proxy MCP servers,
exec native code, call into a customer SDK. The platform doesn't and
shouldn't know.

### The off-the-shelf runner

We ship a reference runner (`posthog-tool-runner`) via Helm chart that
handles the 90% case out of the box. It accepts a YAML config that wires
common tool sources:

```yaml
# Example reference-runner config.
# Each project entry is an independent registration from PostHog's
# perspective — its own endpoint, token, slug, catalog, queue. The runner
# process just multiplexes them onto one binary. Endpoints can differ per
# project (US cloud + EU cloud + self-hosted all from one runner). To
# grant/revoke a project: add/remove its entry and redeploy.
projects:
  - project_id: 123
    endpoint: https://us.posthog.com
    token_secret_ref: posthog-runner-token-us-prod # K8s Secret name
    slug: grafana-prod # stable within this project
    expose:
      - grafana.query_loki
      - grafana.query_prometheus
  - project_id: 456
    endpoint: https://eu.posthog.com
    token_secret_ref: posthog-runner-token-eu-staging
    slug: grafana-prod # same slug fine — different project
    expose:
      - grafana.query_loki
      - grafana.query_prometheus
      - grafana.get_dashboard_by_uid
      - kubernetes.restart_deployment

# Tool sources the reference runner knows how to wire up. Names referenced
# by `expose` above are `<source_name>.<tool_name>`. Sources are shared by
# all projects this runner serves — secrets / endpoints are per-process.
tool_sources:
  # Proxy an existing MCP server reachable inside the cluster.
  - source: mcp
    name: grafana
    endpoint: http://grafana-mcp.observability.svc.cluster.local:3000
    secrets_envs:
      - GRAFANA_API_KEY # rendered from a K8s Secret on the runner side

  # Shell-command tool with a hand-written schema.
  - source: command
    name: kubernetes.restart_deployment
    args_schema:
      type: object
      required: [namespace, deployment]
      properties:
        namespace: { type: string }
        deployment: { type: string }
    command: kubectl --namespace=${args.namespace} rollout restart deployment/${args.deployment}
```

Per-project the runner runs an independent heartbeat + long-poll loop
under its own token. To PostHog, that's two unrelated `tool_runner`
rows; the slugs can even collide because they're scoped to different
projects. The customer's win is operational: one Deployment, one image,
one set of tool sources, N project entries.

`source: mcp` covers the common case — Grafana, Kubernetes, Stripe, etc.
already have MCP servers; the customer runs one in-cluster and the runner
forwards. `source: command` covers the long-tail of "we have an internal
script we want the agent to call" without making the customer write a
full MCP server.

The reference runner ships pre-baked tool sources for the integrations
PostHog expects most customers to want (Kubernetes, Grafana, common
SaaS) — toggled on via config rather than implemented per-customer. The
toggles are reference-runner features, _not_ part of the platform
contract.

### Customers who outgrow the reference runner

For anything the reference runner doesn't cover, the customer writes
their own runner against the same protocol. Native code, embedded SDKs,
in-memory state, custom auth flows — all viable, because the platform
only sees "registered runner that returns results". A WASM / plugin path
_inside_ the reference runner is plausible later but is overkill today;
the escape hatch (write your own runner) is enough.

## PostHog-side: storage + endpoints

Scoping model: **runners are project-scoped** (team-scoped in code) —
the token, the slug, the catalog, the queue all live under one project.
PostHog has no concept of "one runner serving multiple projects". A
single customer process can still hold N project configs and act as N
independent runners; from PostHog's perspective those are just N
separate `tool_runner` rows that happen to share a host. Access control
is "did the customer give the runner this project's token?", nothing
more.

New tables (live in `@posthog/agent-migrations`, not inline):

```sql
-- One row per registered runner (per project). Slug is the project-stable
-- identifier — `runner: 'grafana-prod'` in an agent spec resolves to the
-- row with (team_id = this agent's project, slug = 'grafana-prod').
tool_runner (
  id                bigserial primary key,
  team_id           bigint not null,              -- the project (Team model)
  slug              text not null,                -- 'grafana-prod'
  token_hash        text not null,                -- argon2 of the bearer
  status            text not null,                -- 'active' | 'revoked'
  description       text,
  created_at        timestamptz not null default now(),
  last_seen_at      timestamptz,                  -- updated on heartbeat
  unique (team_id, slug)
);

-- Tool catalog the runner published on its last heartbeat. Replaced
-- wholesale each heartbeat; no per-tool history.
tool_runner_tool (
  runner_id         bigint not null references tool_runner(id) on delete cascade,
  tool_name         text not null,
  input_schema      jsonb not null,
  description       text,
  primary key (runner_id, tool_name)
);

-- Work queue. One row per pending tool call.
tool_invocation (
  id                bigserial primary key,
  runner_id         bigint not null references tool_runner(id),
  session_id        text not null,                -- the agent session waiting on this
  tool_name         text not null,
  args              jsonb not null,
  status            text not null,                -- 'queued' | 'leased' | 'done' | 'failed' | 'cancelled' | 'timed_out'
  leased_by         text,                         -- runner instance id (uuid set at lease)
  lease_expires_at  timestamptz,
  result            jsonb,
  error             text,
  created_at        timestamptz not null default now(),
  completed_at      timestamptz,
  index (runner_id, status, created_at)
);
```

New ingress endpoints (all `Authorization: Bearer <runner_token>` except
the admin ones, which use the normal PostHog session auth):

| Verb + path                                        | Caller         | Purpose                                                                                                      |
| -------------------------------------------------- | -------------- | ------------------------------------------------------------------------------------------------------------ |
| `POST /api/projects/:team/tool_runners`            | PostHog UI     | Create runner, return one-time token (`phtr_<slug>_<secret>`).                                               |
| `GET  /api/projects/:team/tool_runners`            | PostHog UI     | List runners + last-seen + tool catalog.                                                                     |
| `POST /api/projects/:team/tool_runners/:id/rotate` | PostHog UI     | Rotate the bearer token.                                                                                     |
| `DELETE /api/projects/:team/tool_runners/:id`      | PostHog UI     | Revoke.                                                                                                      |
| `POST /runners/heartbeat`                          | Runner process | Liveness + replaces the tool catalog. Body: `{ tools, version, instance_id }`.                               |
| `GET  /runners/poll?max_wait_seconds=30`           | Runner process | Long-poll. Returns the next leased invocation or 204 on timeout. Server sets `leased_by`/`lease_expires_at`. |
| `POST /runners/invocations/:id/result`             | Runner process | Body: `{ status: 'done' \| 'failed', result?, error? }`.                                                     |
| `POST /runners/invocations/:id/extend_lease`       | Runner process | For long-running tools — push out `lease_expires_at`.                                                        |

Ingress writes the queue; the agent-runner blocks on `SessionEventBus`
for the result event. Ingress publishes the bus event in the same
transaction as the row flip from `leased` → `done`/`failed`. Postgres
remains the durable source of truth (used by crash recovery + the janitor
sweep); the bus carries the live signal during the happy path. No Postgres
polling on the runner side.

## Lifecycle of one invocation

1. **Tool call inside `run-turn.ts`.** The dispatcher does `await
client.callTool(name, args, { timeout_ms })` — it does **not** branch
   on kind. `client` is the `SelfHostedMcpClient` instantiated for this
   `mcps[]` entry at session start. (See _Transport is private to the
   client_ above for why this matters.)
2. **Approval gate (if any).** Existing approval-policy code runs _before_
   `callTool` resolves to enqueue. If approval is required, an
   `ApprovalRequest` row is created and the agent yields; the invocation
   is **not enqueued** until approval is granted. This is the critical
   security property: a sensitive op never reaches the customer's cluster
   without an approved PostHog ticket.
3. **Enqueue.** `SelfHostedMcpClient.callTool` POSTs to ingress, which
   inserts a `tool_invocation` row with status `queued`, registers a
   bus-listener for the invocation id, then awaits.
4. **Lease.** A runner long-polling `GET /runners/poll` gets the row.
   Server atomically sets `status='leased'`, `leased_by=<instance>`,
   `lease_expires_at=now()+visibility_timeout`. Other runners with the
   same slug (HA case) won't see it.
5. **Execute.** Runner forwards to the local MCP server or runs the
   shell command. Calls `extend_lease` if the work takes longer than the
   visibility timeout.
6. **Report.** Runner POSTs `result`. Ingress flips the row to
   `done`/`failed` and publishes a `tool_result` event on
   `SessionEventBus`.
7. **Agent resumes.** `SelfHostedMcpClient.callTool` returns the result;
   `run-turn.ts` continues the turn exactly as it would for any other
   `McpClient` impl.

**Crash recovery.** If the agent-runner dies between steps 3 and 7: on
session re-lease, the new runner queries `tool_invocation` rows in
non-terminal state for this session and reattaches a bus listener (or
reads the result directly if the row is already `done`/`failed`). The
listener-attach is idempotent.

**Tool-timeout.** If `timeout_ms` expires before the result event arrives,
`SelfHostedMcpClient.callTool` rejects with `ToolTimeoutError` and
best-effort publishes a cancel signal. The customer-side row stays leased
until the lease expires, at which point a janitor sweep marks it
`cancelled` (or `timed_out`). If the work was non-idempotent, the bundle
author should have wrapped it in an approval gate or made it idempotent —
same rule as today's tool model.

**Runner crash.** If the runner dies mid-step 5: lease expires, row goes
back to `queued`, another runner (or the same one after restart) picks
it up. At-least-once delivery for the underlying work.

## Approval flow integration

No new approval machinery. Today's pipeline:

```text
tool_call → approval_policy_check
          → (if required) ApprovalRequest pending → user clicks approve
          → tool dispatch (= client.callTool)
```

For self-hosted, `client.callTool` is `SelfHostedMcpClient.callTool`,
which enqueues + waits. The approval gate runs _before_ `callTool` is
called, so the customer's runner only ever leases pre-approved invocations.
This is what makes the security story tight: PostHog enforces auth +
approval at the _platform_ layer.

### Per-MCP approval policy

The `approval` field on the self-hosted McpRef (see _Spec-side_ above)
binds each exposed tool to "needs approval" / "doesn't" at session
start. The dispatcher's pre-call gate consults a single resolver:

```typescript
function needsApproval(toolName: string): boolean {
  // Native + custom tools — existing approval_policy field on the spec.
  const native = nativeApprovalForTool(toolName)
  if (native !== undefined) return native

  // Self-hosted MCP — fall through to the per-MCP `approval` block.
  const mcp = mcpForTool(toolName) // looks up which McpRef this tool came from
  if (mcp?.kind === 'self-hosted') {
    const bareName = stripMcpPrefix(toolName)
    const override = mcp.approval.by_tool[bareName]
    if (override !== undefined) return override === 'always'
    return mcp.approval.default === 'always'
  }

  return false
}
```

The three common shapes:

- **No approval** — omit `approval` (or `{ default: 'never' }`).
- **Approve everything** — `{ default: 'always' }`.
- **Allowlist style** — `{ default: 'never', by_tool: { dangerous_op: 'always' } }`.
- **Denylist style** — `{ default: 'always', by_tool: { safe_op: 'never' } }`.

The _approver policy_ — who can approve, where the prompt shows up
(Slack channel, team members, org admins) — is governed by the agent's
existing top-level `approval_policy` (see
[`approval-gated-tools.md`](approval-gated-tools.md)), exactly the same
as for native tools. This field only decides _whether_ approval is
required.

## Helm chart (`charts/posthog-tool-runner/`)

Customer-facing chart. Modeled on the `posthog-app` golden chart, but
trimmed: no HPA, no ingress, no PgBouncer — just a single Deployment, a
ConfigMap with the tools spec, and a Secret holding the bearer token.

```yaml
# values.yaml — what customers tune
replicaCount: 2 # HA-by-default; we do at-least-once anyway

# The runner config from above — either inlined or rendered into a
# ConfigMap by the chart. Each `projects[]` entry has its own endpoint,
# token secret ref, slug, and exposed-tool list. The chart wires the
# referenced K8s Secrets into the pod as env.
config: <inline or configMapRef>

resources: { ... }
nodeSelector: { ... }
serviceAccount: # if any command source needs cluster access
  create: true
  annotations: { ... }
```

We ship the chart with the binary image pinned to a tag; customers run
`helm upgrade` to pick up runner updates. Image hosted on Docker Hub or
GHCR, _not_ a private registry — must be pullable from the customer's
cluster.

## Authentication: runner token

- Created per `tool_runner` row — one token per `(project, slug)` pair.
  One-time-display on create (`phtr_<slug>_<base64-secret>`), stored
  argon2'd. Same shape as the existing `posthog_personal_api_key`.
- Sent on every runner→PostHog request as `Authorization: Bearer ...`.
- The token can only fetch/complete invocations for _its_ runner row
  and publish a catalog for _its_ runner row. Nothing cross-project.
- Rotate-without-downtime: rotate endpoint returns a _new_ token; both
  the old and new tokens are valid for a 24h overlap window; old token
  hash deleted after.
- Revoke = delete the row; ongoing invocations cancel-via-event.
- A customer multiplexing N projects onto one runner process holds N
  separate tokens — one secret per project. The chart wires each via
  its `token_secret_ref`.

## Discovery in the spec-author UX

Spec author opens the "Add MCP" picker. Today's options: `agent`,
`external`. Add `self-hosted`. Picking `self-hosted` shows a dropdown of
the team's registered runners (with last-seen status: ⏺ live, ⚠ stale,
⊘ never-connected). Picking a runner shows its current tool catalog so
the author can pick the subset.

Freeze-time validation (`services/agent-janitor/src/validate-spec.ts`)
checks each `self-hosted` entry refs an existing runner _and_ that all
listed tools are in the runner's most-recently-published catalog. The
catalog can drift between freeze and run; runtime falls through with a
"tool not currently available" error rather than failing the session.

## Observability

- Per-runner: heartbeat freshness, current catalog size, invocations/min,
  error rate, p50/p99 dispatch latency.
- Per-invocation: log line on enqueue, lease, complete, with the
  `session_id` so SRE bot's own observability lights up alongside.
- **`dispatch_latency_ms` broken into four phases** so the ~30–60 ms
  overhead budget (see Q4) is empirically verifiable and regressions
  are visible:
  - `enqueue_ms` — agent-runner POST → row visible to pollers
  - `lease_wait_ms` — row queued → leased by a runner
  - `execute_ms` — leased → result POSTed (the tool's own time)
  - `propagate_ms` — result POST → bus event delivered to agent-runner
- Surface in the agent_stack product under a new "Tool runners" page
  (project-scoped, alongside the existing "Integrations" and "API keys"
  pages).

## Failure modes (call out the worst)

- **Runner offline.** Heartbeat older than `5m` → status flips to
  `stale`. Tool calls fail fast with `runner_offline` error rather than
  queuing for hours. Surfaced to the bundle author as a tool error.
- **Runner crashes mid-invocation.** Lease expires; row re-queued; HA
  replicas or post-restart instance picks it up. Idempotency = bundle
  author's responsibility for non-idempotent ops, exactly like today.
- **Runner token leak.** Rotate from UI (or revoke). 24h overlap window
  for graceful rollover.
- **Customer Grafana DNS flap.** Runner reports `failed` with the
  underlying MCP error; agent decides how to handle (retry, ask user,
  end session) — same model as `runtime-mcps.md` open question 5.
- **PostHog ingress restart while a runner is long-polling.** Runner
  sees a 502/connection-reset, retries with exponential backoff +
  jitter. No invocation loss (rows are durable in Postgres).
- **Two runners with the same slug (intended HA).** Lease is exclusive;
  only one gets each invocation. Catalog publishes are last-writer-wins
  on heartbeat; both runners SHOULD publish identical catalogs (because
  they're the same Helm release). Mismatched catalogs in a single slug
  = customer config error, not our problem to reconcile.

## Open questions

1. ~~**Push vs poll on the agent side.**~~ **Resolved: push, via
   `SessionEventBus`.** Same primitive the runner already blocks on for
   approval grants and resume-on-message; one consistency model instead
   of two; latency scales with the tool's own `timeout_ms` rather than a
   global poll interval. See _Transport is private to the client_ above
   for the client-impl sketch.
2. ~~**Plugin / WASM path.**~~ **Resolved: not a platform concern.** The
   platform contract is _just_ the wire protocol (register, heartbeat,
   lease, report). The reference runner ships with `source: mcp` +
   `source: command` baked in plus pre-baked sources for the integrations
   we expect to be common (Kubernetes, Grafana, etc.). Anything more
   exotic is a "write your own runner" question, not a platform question.
   A plugin / WASM path _inside_ the reference runner is plausible later
   but overkill today.
3. ~~**Cross-project runner sharing.**~~ **Resolved: project-scoped,
   client-side multiplexing.** PostHog has no concept of a runner
   serving multiple projects — `tool_runner` is keyed on `(team_id,
slug)` and the token is bound to that row. A customer who wants one
   process to serve N projects holds N independent `(project_id,
endpoint, token, slug)` configs and the runner spawns one
   register-heartbeat-poll loop per entry. To PostHog those are N
   unrelated runners; slugs can even collide across projects. No
   org-level concept, no cross-project ACL, no PostHog-side audit log
   for sharing decisions.
4. ~~**Cold-start latency.**~~ **Resolved: budget is ~30–60 ms of
   overhead per call (one Postgres write + one HTTPS hop on top of the
   underlying tool work).** Acceptable for every use case in scope —
   the LLM round-trip dwarfs it for interactive triggers, and even a
   50-tool fan-out only costs ~3s total which is rounding error vs
   LLM throughput limits. Tracked empirically via the per-phase
   `dispatch_latency_ms` breakdown in _Observability_ below.
5. ~~**Streaming results.**~~ **Resolved: deferred, tied to the
   `runtime-mcps.md` streaming decision.** v1 stays one-shot; bundle
   authors needing progressive output model it as a paginated tool
   (cursor / since parameter, agent makes repeated calls). The right
   time to design streaming is when `ExternalMcpClient` _also_ gains
   it, so the `McpClient` interface stays uniform. Forward-compatibility
   nudge: the bus event uses `kind: 'tool_result'` as a discriminator,
   leaving `kind: 'tool_result_chunk'` + `kind: 'tool_result_done'`
   reserved for the streaming variant. Zero cost today, no schema
   migration when we add it.
6. ~~**Auth handoff for the underlying MCP server.**~~ **Resolved:
   deferred. v1 ships service-account-only.** The agent's principal
   does not flow into Grafana / k8s / etc. — every downstream call runs
   as "the runner's service account". The customer-side audit log
   loses per-user differentiation; PostHog's activity log keeps the
   asking principal, so a two-step trace is possible. Per-principal
   handoff is genuinely confusing to design well (per-user secrets,
   OAuth-on-behalf-of, etc., all have different shapes per downstream
   system) and no v1 app needs it. **The workaround we DO support is
   per-function approval gating** (see _Per-MCP approval policy_
   above) — sensitive calls go through the existing approval system
   with the asking principal captured in PostHog's log. That covers
   the audit-trail case for "Ben triggered the restart". The
   per-principal handoff feature stays parked until a real customer
   asks.

## What this unblocks

Per [`_APP_IDEAS.md`](_APP_IDEAS.md):

- **SRE Slack bot v1** — the Grafana + Kubernetes MCP wiring the doc
  flags as the v1 upgrade. Goes from 🟡 to ✅.
- **Warpstream forecasting** — Warpstream's API + a private Grafana,
  both internal-only at most companies. Goes from 🔴 to ✅.
- **Financial reconciliation** — banking MCPs are _all_ private. Goes
  from 🔴 to ✅.
- **Gap analysis / Feature prioritization** — for orgs whose Zendesk /
  internal ticketing isn't reachable from a PostHog public IP.
- Same shape as **agent-as-MCP** for the outbound case: makes "the
  Wizard for ASS local-CLI" buildable, since the local CLI can register
  as a runner exposing `local-fs/*` and `local-git/*` tools.

## Out of scope

- **Push transport (WebSocket / gRPC streams).** Long-poll is enough
  for v1 and works through every firewall without extra plumbing.
- **MCP sampling.** Same call as `runtime-mcps.md`.
- **Hosted/managed tool runners** (PostHog runs them for you, e.g. as
  a Cloudflared tunnel). Reasonable v2; v1 is BYO infra.
- **Multi-region runner pinning** (an EU runner stays in EU). Comes
  for free if PostHog deployment is region-pinned; revisit if not.

## Rollout

Stages, each independently shippable:

1. Schema + ingress endpoints + bearer-token auth + admin UI (create /
   rotate / revoke / list).
2. Reference runner binary + minimal Helm chart (Path A only).
3. Wire `kind: 'self-hosted'` into `McpRefSchema`, add the
   `SelfHostedMcpClient` impl behind the existing `McpClient` interface,
   add freeze-time validation.
4. Path B (command tools).
5. Polish: observability page, HA docs, rotation docs.

Sequence is dependent on `runtime-mcps.md` landing first — this plan
inherits its dispatcher routing pattern and freeze validation
infrastructure.

## Related plans

- [`runtime-mcps.md`](runtime-mcps.md) — sibling, solves the
  publicly-reachable-MCP case.
- [`approval-gated-tools.md`](approval-gated-tools.md) — the gating
  layer this plan composes with.
- [`per-session-access-elevation.md`](per-session-access-elevation.md)
  — principal threading model; self-hosted runners do not extend it.
- [`agent-as-mcp-server.md`](agent-as-mcp-server.md) — symmetric
  pattern (inbound vs outbound); some persistence-layer concepts
  overlap.
