# Design — Tailscale-backed MCP integration

**Status:** draft. **Owner:** ben.
**Sibling to:** [`runtime-mcps.md`](runtime-mcps.md) — adds a new
`McpClient` impl alongside the existing `kind: 'external'` one.

## Problem

`runtime-mcps.md` lets agent specs reference MCP servers via
`kind: 'external'` and a publicly-reachable URL. That works for SaaS
MCPs (GitHub, Linear, Stripe). It fails for the integrations agents
most need — Grafana, Kubernetes, internal service wrappers — which
live inside the customer's network behind no public DNS and rightly
refuse to be exposed publicly.

This plan adds a `kind: 'tailscale'` McpRef variant. PostHog-hosted
agents reach customer-deployed MCP servers over the customer's own
Tailscale tailnet, authenticated via a tag-scoped OAuth client the
customer mints and pastes into PostHog. Customer-side network
boundary is preserved — every call from PostHog enters through the
customer's tailnet ACL and is bounded by what they explicitly
allowed.

The platform contract is deliberately narrow: PostHog provides the
connectivity machinery; **the customer owns everything else** — which
MCP servers to deploy, where, how to authenticate them upstream,
which tools to expose. We ship docs, not infrastructure.

## What the customer owns

- **Their MCP servers.** `mcp-grafana`, `mcp-kubernetes`, anything
  custom — their choice. We provide reference deploy recipes for the
  common ones, no required runtime.
- **Their tailnet.** Whatever they have today. PostHog joins it via
  OAuth, doesn't replace it.
- **The ACL boundary.** Strict tag-based ACL rules decide what
  `tag:posthog-managed` can reach. PostHog can only call what the
  customer's hujson allows.
- **The OAuth client.** Minted in their Tailscale admin console with
  `auth_keys:write` scoped to one tag. Revoked any time without
  PostHog involvement.

## What PostHog owns

Three small pieces:

1. A **Tailscale Integration** model — stores `client_id`,
   `client_secret`, `tailnet`, encrypted at rest. Configured
   per-org via the existing Integrations UI.
2. A **`kind: 'tailscale'` McpRef variant** — agent spec field
   referencing the Integration + the MagicDNS hostname of the
   upstream MCP server.
3. A **`tsnet`-backed `McpClient` impl** — per-session ephemeral
   tailnet node joined into the customer's tailnet via a short-lived
   tag-scoped auth key minted from the OAuth client at session start.

Approval gating, audit logging, principal threading all reuse
existing PostHog machinery. No new primitives.

## Spec-side: a new `McpRef` kind

Today [`McpRefSchema`](../../../services/agent-shared/src/spec/spec.ts#L213)
has `agent` and `external`. Add a third:

```typescript
z.object({
  kind: z.literal('tailscale'),
  // References a Tailscale Integration row (the customer's saved OAuth
  // client + tailnet name). Freeze-time validation checks the row
  // exists for this team.
  integration: z.string(),
  // MagicDNS hostname of the upstream MCP server inside the tailnet.
  // e.g. 'grafana-mcp'. No scheme — http is implied (intra-tailnet
  // wireguard already provides encryption).
  hostname: z.string(),
  port: z.number().int().positive().default(3000),
  // Path the MCP server serves on. Default '/mcp' matches the
  // mark3labs/mcp-go convention.
  path: z.string().default('/mcp'),
  // Optional: subset of the upstream's catalog to expose to this agent.
  // Empty = expose every tool the MCP advertises.
  tools: z.array(z.string()).default([]),
  // Per-MCP approval policy — same shape as runtime-mcps + native tools.
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
  - kind: tailscale
    integration: tailscale-internal # PostHog's own Integration row
    hostname: grafana-mcp
    tools: [query_loki_logs, query_prometheus]

  - kind: tailscale
    integration: tailscale-internal
    hostname: kubernetes-mcp
    tools: [pods_list, pods_logs, deployments_restart]
    approval:
      default: never
      by_tool:
        deployments_restart: always
```

## Transport is private to the client

**The architectural contract: from the dispatcher's perspective,
calling a Tailscale-routed tool is indistinguishable from calling an
external one.** Same surface, same blocking semantics, same error
model.

This is enforced by treating the MCP client as the abstraction.
Concrete impls vary in transport; the dispatcher does not branch on
`kind`.

```typescript
interface McpClient {
  callTool(name: string, args: object, opts: { timeout_ms: number }): Promise<unknown>
  listTools(): Promise<ToolDescriptor[]>
  close(): Promise<void>
}

// runtime-mcps.md — opens HTTP/SSE/WebSocket via the official MCP SDK.
class ExternalMcpClient implements McpClient {
  /* ... */
}

// This plan — wraps an ExternalMcpClient whose http.Client routes
// through a per-session tsnet node joined into the customer's tailnet.
class TailscaleMcpClient implements McpClient {
  /* ... */
}
```

`run-turn.ts` does not change. The latency budget (`timeout_ms` per
tool) governs everything. Future transports — Cloudflare Tunnel,
NAT-traversal, direct WireGuard — each land as a new `McpClient`
impl. `run-turn.ts` keeps not caring.

## Session lifecycle

At session start, for every `kind: 'tailscale'` McpRef in the spec:

1. **Resolve Integration.** Load `(client_id, client_secret, tailnet)`
   for the referenced Integration row. Fail-fast on revoked / missing.
2. **Mint an ephemeral auth key.** POST to Tailscale's API with the
   OAuth client credentials, scoped to the Integration's default tag
   (`tag:posthog-managed` by convention). Key is single-use, expires
   in 10 minutes, ephemeral so the node auto-deletes on disconnect.
3. **Spin up a `tsnet.Server`.** Hostname encodes the session id
   (`posthog-<session-id>`) so the customer can see exactly which
   session corresponds to which node in their tailnet admin console.
   Ephemeral state dir, tmpfs-backed.
4. **Construct the underlying MCP client** with an `http.Client`
   routed through `tsnet.Server.HTTPClient()`. From this point on
   the upstream call is just an HTTP request to
   `http://<hostname>:<port><path>` — `tsnet` handles the tailnet
   routing.

At session end, `tsnet.Server.Close()` detaches the node, and (because
the auth key was ephemeral) the customer's tailnet automatically
removes it. No graveyard of dead PostHog nodes.

## Per-MCP approval policy

The `approval` field on the McpRef binds each exposed tool to "needs
approval" or "doesn't" at session start. The dispatcher's pre-call
gate consults a single resolver:

```typescript
function needsApproval(toolName: string): boolean {
  // Native + custom tools — existing approval_policy field on the spec.
  const native = nativeApprovalForTool(toolName)
  if (native !== undefined) return native

  // Tailscale / external MCP — fall through to the per-MCP `approval` block.
  const mcp = mcpForTool(toolName)
  if (mcp?.kind === 'tailscale' || mcp?.kind === 'external') {
    const bareName = stripMcpPrefix(toolName)
    const override = mcp.approval.by_tool[bareName]
    if (override !== undefined) return override === 'always'
    return mcp.approval.default === 'always'
  }
  return false
}
```

Three common shapes (all fall out of one schema):

- **No approval** — omit `approval` (or `{ default: 'never' }`).
- **Approve everything** — `{ default: 'always' }`.
- **Allowlist style** — `{ default: 'never', by_tool: { restart: 'always' } }`.
- **Denylist style** — `{ default: 'always', by_tool: { safe_op: 'never' } }`.

The _approver policy_ (who can approve, where the prompt shows up) is
governed by the agent's existing top-level `approval_policy` (see
[`approval-gated-tools.md`](approval-gated-tools.md)). This field only
decides _whether_ approval is required.

## Customer setup

The customer-facing flow is the documentation deliverable. Same five
steps the PostHog team runs internally (see dogfood below):

1. **Deploy MCP server(s) in their cluster.** Their choice of
   image, helm chart, secrets management. We publish reference
   recipes for `mcp-grafana` and `mcp-kubernetes` modelled on
   PostHog's own setup.
2. **Expose each MCP on the tailnet.** Standard Tailscale operator
   annotation on the Service:

   ```yaml
   service:
     annotations:
       tailscale.com/expose: 'true'
       tailscale.com/tags: tag:grafana-mcp
       tailscale.com/hostname: grafana-mcp
   ```

3. **Configure tailnet ACLs.** A single rule per upstream:

   ```hujson
   {
     "tagOwners": {
       "tag:grafana-mcp":     ["group:platform"],
       "tag:posthog-managed": ["group:platform"]
     },
     "acls": [
       {
         "action": "accept",
         "src":    ["tag:posthog-managed"],
         "dst":    ["tag:grafana-mcp:3000"]
       }
     ]
   }
   ```

4. **Mint a Tailscale OAuth client.** Scopes:
   `auth_keys:write` constrained to `tag:posthog-managed`. Save
   `client_id` + `client_secret`.
5. **Paste into PostHog UI.** Settings → Integrations → "Tailscale"
   → fill in the three fields. Done.

That is the entire customer-side work. No PostHog binary deployed.
No helm chart of ours. They configure their own existing
infrastructure and hand over scoped credentials.

## PostHog dogfoods this — customer zero

PostHog uses `kind: 'tailscale'` for our own SRE bot. Same code path,
same OAuth dance, same `tsnet` nodes, same failure modes as the
customer flow. Concretely:

- **OAuth client** minted in the PostHog Tailscale admin console
  (`hedgehog-kitefin.ts.net`), scoped to `tag:posthog-managed`.
- **ACL** allows `tag:posthog-managed` → `tag:posthog-agent-mcp:3000`.
- **`mcp-grafana` and `mcp-kubernetes`** deployed in the
  `agent-platform` namespace, exposed via the Tailscale operator
  using the same pattern as
  [`charts/argocd/sherlockhog/manifests/`](../../../../charts/argocd/sherlockhog/manifests/).
- **PostHog's Tailscale Integration row** is the first row in the
  Integration table. Configured once via the PostHog UI.
- **SRE-bot agent spec** uses `kind: 'tailscale'` referencing the
  internal MCPs. No `kind: 'external'` shortcut for our own dogfood
  — same code path the customer hits.

The customer-facing setup doc is derived from these exact steps. We
write the doc by replaying what we did, not by hypothesising.

## Failure modes

| Scenario                                        | Behaviour                                                                                                                                                                                                                                                          |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| OAuth client revoked by customer                | Auth key mint fails 401. Session fails open with `tailscale_integration_revoked` in the activity log.                                                                                                                                                              |
| ACL denies the call                             | `tsnet` HTTP request fails with connection-refused. Surfaced as a tool error; bundle author decides retry / end.                                                                                                                                                   |
| Upstream MCP server down                        | HTTP request returns 5xx. Same handling as `kind: 'external'` MCP downtime.                                                                                                                                                                                        |
| Tailnet split-brain or transient unreachability | `tsnet` retries internally. After the tool's `timeout_ms` we report `ToolTimeoutError` to the agent.                                                                                                                                                               |
| OAuth client secret leaks                       | Attacker can mint auth keys with `tag:posthog-managed` only — and ACLs say they can only reach `tag:<their-allowed-mcps>` on the configured ports. Blast radius bounded by customer ACL. Customer rotates secret in Tailscale admin, pastes new one in PostHog UI. |

## Open questions

1. **Connection pooling per `(team_id, integration_id)`.** Spinning
   up a `tsnet` node per session is ~1–2 s of cold start. For
   chat-trigger latency this matters; for SRE-bot Slack triggers it
   doesn't. Pool with idle eviction is doable but complicates
   teardown — punt to v2.
2. **State directory for `tsnet`.** It wants somewhere to keep
   ephemeral wireguard state. tmpfs is fine; confirm
   `EmptyDir{medium:Memory}` works in our pod spec.
3. **Sidecar vs in-process `tsnet`.** In-process is simpler and what
   the design assumes. Sidecar would give stronger network isolation
   from the agent-runner's main loop. v1 chooses in-process; revisit
   if security review surfaces concerns.
4. **Multi-tailnet customers.** Each tailnet → one Integration row.
   The Integration model already supports multiple rows per team;
   no schema change.

## Out of scope

- **The customer's MCP server deployment story.** We provide
  reference docs and example helm values, not a chart we ship.
- **Non-Tailscale transports** (Cloudflare Tunnel, etc.) — each
  would be a new `McpClient` impl behind the same interface.
  May come later; not v1.
- **Streaming tool results.** One-shot only; same call as
  `runtime-mcps.md`. The event-kind discriminator is reserved.
- **Per-principal auth handoff into the upstream MCP.** Every
  upstream call uses the MCP server's own credentials (whatever the
  customer baked into it). The agent's _principal_ doesn't flow
  into Grafana / k8s. Acceptable for SRE-bot; problematic for
  per-user-permissions use cases. Defer.

## Rollout

Sequenced so each stage has independent value:

1. **[`runtime-mcps.md`](runtime-mcps.md) lands** — foundation. The
   `McpClient` abstraction + `kind: 'external'` impl. Already in
   flight on a separate branch.
2. **Deploy `mcp-grafana` + `mcp-kubernetes`** in PostHog's
   `agent-platform` namespace, exposed via Tailscale.
3. **Set up PostHog's own Tailscale OAuth client + ACLs**
   (`tag:posthog-managed`).
4. **Build the Tailscale Integration model** in PostHog
   (`posthog/models/integration.py` + UI surface).
5. **Build the `kind: 'tailscale'` `McpRef` variant + `TailscaleMcpClient`**
   in agent-runner, wired against the existing dispatcher.
6. **Configure PostHog's own Tailscale Integration** in our PostHog
   UI. We become the first row in the Integration table.
7. **Build SRE-bot v1** against `kind: 'tailscale'` referencing our
   internal MCPs. First real consumer.
8. **Publish the customer-facing setup doc** derived from the exact
   steps we just performed.

## Related plans

- [`runtime-mcps.md`](runtime-mcps.md) — sibling. Provides the
  `McpClient` abstraction this plan extends.
- [`approval-gated-tools.md`](approval-gated-tools.md) — the
  approval-policy machinery this plan composes with.
- [`per-session-access-elevation.md`](per-session-access-elevation.md)
  — principal threading model. Tailscale MCPs do not extend it (per
  the Out-of-scope auth-handoff item).
