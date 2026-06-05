# Design — runtime MCP auth + OAuth discovery

**Status:** **Tier 1 ✅ shipped** (BYO headers + secret substitution on
`McpRefSchema`). Tier 2 (DCR + managed OAuth) still queued. **Owner:**
dylan. **Tracking:** [`_ROADMAP.md`](_ROADMAP.md) §C.2 (follow-up).
**Sibling:** [`runtime-mcps.md`](runtime-mcps.md) — the runner-side
plumbing this builds on.

## Decision (read this first)

Two-tier auth for `spec.mcps[]`, exact same shape as
`@posthog/http-request` for the simple case, plus a managed OAuth
path that doesn't require a Django PR per provider.

- **Tier 1 — bring-your-own token via `headers` + `secrets`.** Self-
  serve. Author registers a PAT / app at the provider, drops the
  bearer into `spec.secrets[]`, references it via `${TOKEN}` in
  `mcps[].headers`. Substitution happens server-side; plaintext
  never leaves the runner process. The default for "I have a token,
  just call the MCP."
- **Tier 2 — Dynamic Client Registration (DCR) OAuth.** Managed.
  Author picks an MCP server in the console; the platform performs
  RFC 9728 (`/.well-known/oauth-protected-resource`) + RFC 8414
  (`/.well-known/oauth-authorization-server`) discovery, then RFC
  7591 (Dynamic Client Registration) against the discovered auth
  server. No per-kind Django code; storage piggybacks on the
  existing `Integration` model + a new generic `MCP_OAUTH` kind.

`auth.integration` stays as the binding seam between an MCP ref
and a stored credential — the existing field, just pointed at the
new `MCP_OAUTH` integration kind instead of per-provider kinds.

**Why both tiers:**

- Tier 1 covers the long tail of "MCP server with a static API
  token" (Sentry, Linear PAT, self-hosted Grafana). No platform
  changes per provider.
- Tier 2 covers MCP servers that implement the official MCP auth
  spec (every compliant server does). No platform changes per
  provider either, because DCR + discovery removes the per-kind
  switch case.

**Result:** runtime MCP auth becomes provider-agnostic. Adding a
new MCP server is a spec edit, never a Django PR.

## Problem

[`runtime-mcps.md`](runtime-mcps.md) shipped `kind: 'external'` with
two auth knobs:

- **`secrets[]`** — `${NAME}` substitution into `mcps[].url` only.
  Works for MCPs that accept tokens as query params (`?token=xxx`)
  or as part of the hostname. Doesn't work for the most common
  modern shape: a static bearer token in an `Authorization` header.
- **`auth.integration`** — references a PostHog `Integration` row;
  the access token is stamped as `Authorization: Bearer <token>`.
  Requires the integration kind to be supported in
  [`posthog/models/integration.py`](../../../posthog/models/integration.py)'s
  `OauthIntegration.oauth_config_for_kind` switch. Adding a new
  service is a Django PR per provider, with pre-registered OAuth
  client credentials baked in.

Net result: the SaaS MCP universe is reachable in principle, but
practically every new provider needs platform code. That's the
exact bottleneck `@posthog/http-request` was designed to bypass —
and it bypasses it for HTTP services. For MCPs, the runtime path
is still gated on platform code per provider.

The fix is two small additions and a discovery flow that lets the
platform handle "any OAuth-compliant MCP server" without per-kind
plumbing.

## Tier 1 design — bring-your-own headers

### Schema change

Add a single field to `McpRefSchema`:

```typescript
McpRefSchema = z.object({
  id: z.string().min(1),
  url: z.string().url(),
  auth: z.object({ integration: z.string().optional() }).optional(),
  secrets: z.array(z.string()).default([]),
  // NEW — same substitution semantics as @posthog/http-request.
  // Values may reference `${NAME}` from `secrets[]`; the runner
  // substitutes plaintext before opening the MCP client.
  headers: z.record(z.string(), z.string()).optional(),
  tools: z.array(McpToolEntrySchema).optional(),
})
```

Mirror in `products/agent_platform/backend/spec_schema.py`. Regen
OpenAPI.

### Runner change

`services/agent-runner/src/loop/mcp-clients.ts:resolveTarget` already
substitutes secrets into the URL and stamps an `Authorization` header
from `auth.integration`. Extend the same function to walk `headers`:

```typescript
async function resolveTarget(
  ref: McpRef,
  deps: OpenMcpClientsDeps
): Promise<{ url: string; headers: Record<string, string> }> {
  const url = substituteSecrets(ref.url, ref.secrets, deps.secrets)
  const headers: Record<string, string> = {}

  if (ref.auth?.integration) {
    // ... existing OAuth-integration path ...
  }

  // NEW — author-supplied headers with `${SECRET}` substitution.
  if (ref.headers) {
    for (const [k, v] of Object.entries(ref.headers)) {
      headers[k] = substituteSecrets(v, ref.secrets, deps.secrets)
    }
  }

  return { url, headers }
}
```

Precedence: integration-stamped headers come first, author-supplied
headers second. If an author supplies an `Authorization` header _and_
`auth.integration`, the explicit author choice wins — same posture
as `http-request` (caller-set values are not silently overwritten).

### Author experience

```yaml
mcps:
  - id: linear
    url: https://mcp.linear.app/sse
    secrets: [LINEAR_TOKEN]
    headers:
      Authorization: 'Bearer ${LINEAR_TOKEN}'
    tools: [list-issues, create-issue]
```

The concierge's existing `set_secret` flow handles pasting
`LINEAR_TOKEN`. Same UX as `http-request`, applied to MCPs.

### Cost estimate

- TS schema + tests: ~5 LOC + a couple of cases in `spec.test.ts`
- Runner `resolveTarget`: ~10 LOC + a couple of cases in
  `mcp-clients.test.ts`
- Django mirror: ~10 LOC in `spec_schema.py`, mirrored test in
  `test_spec_schema.py`
- OpenAPI regen

~30 LOC. One PR.

### What this unlocks

Every SaaS MCP with a static-token auth model. Linear, Sentry, the
self-hosted half of Grafana, Notion, internal services. The author
generates the token at the provider, pastes once, done.

### ✅ Shipped

`headers` field landed on `McpRefSchema` with `${SECRET}` substitution.
Runner walks `ref.headers` after the integration / dev-bearer paths,
substituting from the ref's `secrets[]` (missing secrets throw
`mcp_secret_not_resolved` — same loud-failure shape as the URL path).
Author-supplied entries take precedence on duplicate keys, matching
`http-request`'s "caller-set values are not silently overwritten" rule.
Django spec validator mirrored. OpenAPI regenerated. Test coverage:

- `services/agent-shared/src/spec/spec.test.ts` — parsing with headers
- `services/agent-runner/src/loop/mcp-clients.test.ts` — substitution,
  precedence over integration auth, missing-secret error
- `services/agent-tests/src/cases/mcp-tools.test.ts` — end-to-end
  GitHub-MCP-shaped round trip with `Authorization: Bearer ${TOKEN}`
- `products/agent_platform/backend/test_spec_schema.py` — Django mirror

Spec authors using a typed MCP catalog with bearer-token auth land at:

```yaml
mcps:
  - id: github
    url: https://api.githubcopilot.com/mcp
    secrets: [GITHUB_TOKEN]
    headers:
      Authorization: 'Bearer ${GITHUB_TOKEN}'
    tools: [get_issue, search_issues, create_pull_request_comment]
```

Tier 2 (DCR + managed OAuth) is the queued upgrade for "click-to-connect"
UX; until then, paste-a-PAT via the concierge's `set_secret` flow is
the path.

## Tier 2 design — Dynamic Client Registration

### Problem with the per-kind status quo

Today's `auth.integration` path requires this Django code to ship
before an MCP server can be reached:

```python
# posthog/models/integration.py — OauthIntegration.oauth_config_for_kind
if kind == "linear":
    return OauthConfig(
        authorize_url="https://linear.app/oauth/authorize",
        token_url="https://api.linear.app/oauth/token",
        client_id=settings.LINEAR_CLIENT_ID,
        client_secret=settings.LINEAR_CLIENT_SECRET,
        # ...
    )
```

Every new provider = Django PR + new env vars + OAuth app pre-
registration with the provider. That's the bottleneck.

### What the MCP spec says

The MCP authorization spec mandates that compliant servers
self-describe their auth via standard discovery documents:

1. The MCP server publishes `GET /.well-known/oauth-protected-resource`
   (RFC 9728), pointing at the auth server it trusts.
2. The auth server publishes `GET /.well-known/oauth-authorization-server`
   (RFC 8414), listing `authorize_url`, `token_url`, supported scopes,
   `registration_endpoint`, etc.
3. The client (PostHog) dynamically registers a new OAuth client at
   the auth server's `registration_endpoint` (RFC 7591 — Dynamic
   Client Registration), receiving a fresh `client_id` +
   `client_secret` per registration.
4. Standard PKCE-protected authorization-code flow against the
   discovered endpoints.

Every compliant MCP server already does this. Claude Desktop, Cline,
mcp-inspector all use this exact flow. PostHog itself implements the
server side via [`posthog/api/oauth/dcr.py`](../../../posthog/api/oauth/dcr.py).

We need the **client** side of the same protocol.

### Generic `MCP_OAUTH` integration kind

Replace the per-kind switch with a single integration kind that
accepts an MCP server URL as input and discovers everything else.

```python
# posthog/models/integration.py
class IntegrationKind(models.TextChoices):
    # ... existing kinds ...
    MCP_OAUTH = "mcp-oauth"   # new — generic, MCP-spec-compliant servers

class McpOauthIntegration:
    """
    Sibling to `OauthIntegration` but config-driven by RFC 9728/8414/7591
    discovery rather than a per-kind switch case. The `integration_id`
    is the MCP server's resource URL (host + path); the `config` /
    `sensitive_config` hold the discovered endpoints, the DCR-issued
    client_id/secret, and the access/refresh tokens.
    """

    @classmethod
    async def discover(cls, mcp_server_url: str) -> "McpDiscoveryResult":
        """
        1. GET <mcp_server_url>/.well-known/oauth-protected-resource
        2. Extract `authorization_servers[]`; pick the first.
        3. GET <auth_server>/.well-known/oauth-authorization-server
        4. Cache result in `config` (TTL = a few hours).
        """

    @classmethod
    async def register(cls, discovery: McpDiscoveryResult, team_id: int) -> "McpOauthIntegration":
        """
        POST <discovery.registration_endpoint> with PostHog as the client
        metadata (RFC 7591). Receive client_id/client_secret. Store on
        the Integration row's sensitive_config.
        """

    async def authorize_url(self, state: str, code_verifier: str) -> str:
        """Standard PKCE-protected authorize URL — same shape as OauthIntegration."""

    async def exchange_code(self, code: str, code_verifier: str) -> dict:
        """Exchange auth code for access + refresh tokens. Store on row."""

    async def refresh_access_token(self) -> None:
        """Same shape as OauthIntegration.refresh_access_token."""
```

The Integration model itself doesn't change. `IntegrationViewSet`
gets one new callback handler at `/api/integrations/mcp-oauth/callback`
that resolves the in-flight flow by `state`, exchanges the code, and
stamps tokens on the row.

### Spec author experience

```yaml
mcps:
  - id: linear
    url: https://mcp.linear.app/sse
    auth:
      integration: mcp-oauth:linear-app # references the Integration row
    tools: [list-issues, create-issue]
```

The concierge surfaces an inline `Connect to Linear` button (a new
client tool, sibling to `set_secret`). On click, the dock opens a
popup at PostHog's `/api/integrations/mcp-oauth/start?mcp_url=...`
endpoint. The endpoint runs discovery + DCR, redirects to the auth
server's `authorize_url`, the user logs in + grants, the callback
stamps tokens, the popup closes, the concierge resolves with
`{ integration_id }`. Same UX shape as the existing OAuth integrations
(Slack, GitHub) — but no per-provider Django code.

### Per-asker scoping

The current `Integration` row is keyed `(team, kind, integration_id)`
— team-scoped, one token per team. For MCP servers where each user
should call the MCP **as themselves** (Linear's "show me my issues",
GitHub's "list my PRs"), the storage shape needs a `user_id` segment:

```python
class Integration(models.Model):
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    kind = models.CharField(...)
    integration_id = models.TextField(...)
    user = models.ForeignKey("User", on_delete=models.CASCADE, null=True)  # NEW

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "kind", "integration_id", "user"],
                name="posthog_integration_kind_id_user_unique",
            )
        ]
```

When `user_id` is null → team-scoped (the existing behavior, for
bot-style "shared" integrations). When set → per-user (the auth
context is the session principal's identity).

At runtime, the runner resolves the integration via
`(team_id, kind, integration_id, session.principal.user_id ?? null)`.
First it tries the per-user row; falls back to the team row if
absent. Composes with
[`per-session-access-elevation.md`](per-session-access-elevation.md):
the elevated session's principal identity is the lookup key.

The author opts into per-user mode via a flag on the McpRef:

```yaml
mcps:
  - id: linear
    url: https://mcp.linear.app/sse
    auth:
      integration: mcp-oauth:linear-app
      per_asker: true # NEW — resolve token by session principal
    tools: [list-issues]
```

Default is `per_asker: false` (team-scoped, current behavior). Apps
that need per-user identity opt in explicitly.

### Cost estimate

- `McpOauthIntegration` class + tests: ~250 LOC Python
- `IntegrationViewSet` callback handler: ~80 LOC
- DCR client (POST to `registration_endpoint`): ~50 LOC + http client tests
- Discovery cache (TTL-bounded): ~50 LOC
- Migration for `Integration.user` FK: ~30 LOC
- Concierge `attach_mcp_credentials` client tool: ~80 LOC TS in agent-console
- New endpoint for "start mcp-oauth flow": ~60 LOC Python
- Schema field `auth.per_asker`: ~10 LOC TS + Django mirror
- Runner lookup change: ~20 LOC in `mcp-clients.ts`

~650 LOC total. Three PRs (DCR client + discovery, per-asker
storage, console UX).

### What this unlocks

Any MCP-spec-compliant server. The author types a URL, clicks
"Connect," does the OAuth dance once, the agent now has access. No
platform code per provider, ever.

## Trust model + security review delta

### Tier 1 (BYO headers)

Threat model is identical to `@posthog/http-request`:

- **Author chose the URL + headers.** Same as `external` MCP refs
  today. Smokescreen at the egress hop denies RFC1918 / loopback /
  cloud IMDS, with DNS re-resolution per-IP to close the rebinding
  gap. No new SSRF surface.
- **Secrets are server-side substituted.** The model never sees the
  plaintext. Same posture as the existing `secrets[]` URL
  substitution.
- **Authors can put a token in an arbitrary header.** They can today
  via http-request. Net-new attack surface for runtime MCPs: zero.

### Tier 2 (DCR OAuth)

Three new surfaces, all bounded:

- **Untrusted MCP server URL → discovery requests.** A malicious
  agent author could point at a URL that returns crafted JSON to
  trick the discovery flow. Mitigations: (a) the discovery docs are
  fetched via smokescreen (same SSRF posture as `external` URLs);
  (b) the auth server URL discovered from doc 1 is validated against
  the same host-allowlist before doc 2 is fetched; (c) failures are
  surfaced as `mcp_discovery_failed` without exposing internal
  state.
- **Untrusted auth server → DCR client_id/secret.** The auth server
  could mint a client_id that points at attacker-controlled redirect
  URIs. Mitigation: we pin `redirect_uris` to PostHog's own
  callback during DCR registration, and reject any auth server that
  refuses our pinned URI. (RFC 7591 supports this — the client
  specifies its `redirect_uris` as part of registration.)
- **Per-asker token storage.** The new `user_id` FK on Integration
  rows is straightforward — same encryption (`sensitive_config`),
  same access controls. Risk is bookkeeping (per-user rows can
  proliferate); mitigation is a TTL-based cleanup task.

A separate security-review pass on the DCR client implementation
before merging the second PR. Standard OAuth-client-as-relying-
party threat model; nothing exotic.

## Author UX summary

Both tiers route through the concierge's authoring flow:

- **Tier 1 — paste a token:** concierge calls `set_secret(name:
"LINEAR_TOKEN", purpose: "Linear MCP")`. Existing flow. Concierge
  writes `mcps[].headers["Authorization"] = "Bearer ${LINEAR_TOKEN}"`
  into the spec.
- **Tier 2 — connect via OAuth:** new client tool
  `attach_mcp_credentials(slug, mcp_url)`. Console renders an inline
  "Connect to <server>" button. Click → popup → discovery + DCR +
  authorization → callback → integration row lands. Tool resolves
  with `{ integration_id }`. Concierge writes
  `mcps[].auth.integration = integration_id` into the spec.

Both flows leave the same end state: the agent has access to the
MCP. The author chose the path based on whether they had a static
token already (tier 1) or wanted PostHog to mint and store one
(tier 2).

## Resolved questions

- **Should tier 1 substitution allow `${SECRET}` in `mcps[].url`
  too?** Yes — already supported via existing `secrets[]` URL
  substitution; tier 1 just adds the same to `headers`. No
  duplication needed.
- **Default precedence between author-supplied `headers` and
  integration-stamped `Authorization`?** Author wins. Matches
  `http-request`'s "caller-set values not silently overwritten"
  rule. Authors who want the integration's token must omit
  `Authorization` from `headers`.
- **DCR registration scope — per (team, mcp_url) or per
  (team, mcp_url, user)?** Per `(team, mcp_url)`. One PostHog
  client registration at the auth server; per-user tokens are
  obtained via the standard authorization-code flow against that
  shared client. Matches how Claude Desktop registers once per
  workspace per MCP server.
- **What if the same MCP server is added by multiple agents in the
  same team?** Same integration row; the agent specs all reference
  `mcps[].auth.integration: mcp-oauth:linear-app`. Token refresh +
  rotation centralized.
- **What if discovery fails (server doesn't speak DCR)?** Fall back
  to tier 1 — the console surfaces a "paste a token instead"
  message. Authors aren't locked out of MCPs that haven't shipped
  the auth spec.

## Open questions

1. **Refresh-token revocation handling.** When a user revokes
   authorization at the auth server, the cached access token keeps
   working until expiry. PostHog should poll for revocation periodically
   or rely on 401 responses to invalidate. Defer to implementation —
   the existing `OauthIntegration.refresh_access_token` pattern
   handles 401-driven refresh; revocation is the same shape.
2. **Should tier 1 support per-MCP-tool secrets?** Today an MCP ref's
   `secrets[]` is per-ref, all tools see the same env. A more granular
   model would let the author scope `LINEAR_TOKEN` to only
   `linear__create-issue` (not `linear__list-issues`). Probably
   overkill; revisit if a concrete use case shows up.
3. **DCR client metadata — what name/logo do we register as?**
   `PostHog Agents` as the client name; PostHog's logo URL; product
   description per RFC 7591 section 2. Per-team or generic? Generic
   probably — auth servers display the client name to the user, and
   "PostHog Agents" is clearer than `dylan-acme-corp-tenant-12345`.
4. **Multi-tenant auth server quirks.** Some auth servers (Microsoft,
   Google) require per-tenant client registrations. DCR doesn't
   prescribe how multi-tenant servers handle this; we'll need to
   special-case the few common ones. Defer to a follow-up if a
   concrete user shows up.

## Rollout sequence

Three PRs, each shippable in isolation:

1. **PR 1 — Tier 1 (BYO headers).** ~30 LOC. Schema field + runner
   handling + Django mirror + tests. Lands first because it's the
   smallest and unlocks the most apps today. Concierge already has
   `set_secret`; no UX changes.
2. **PR 2 — Tier 2 backend (discovery + DCR client).** ~400 LOC.
   `McpOauthIntegration` class, callback handler, discovery cache.
   No UI yet — exercised via direct API calls from the agent-tests
   harness using a stub MCP server.
3. **PR 3 — Tier 2 console UX (`attach_mcp_credentials` client
   tool).** ~150 LOC. Concierge surfaces the connect button; popup
   drives the flow shipped in PR 2.

After PR 1: every BYO-token MCP works. After PR 3: the
`https://api.slack.com/apps?new_app=1` rabbit-hole vanishes — the
concierge can offer "Connect to Slack MCP" inline.

## Out of scope

- **Streaming tool results from MCPs.** One-shot only, same as
  [`runtime-mcps.md`](runtime-mcps.md).
- **MCP sampling.** Pi-ai handles all inference; sampling-back-to-the-
  model is deferred indefinitely.
- **Re-adding the `kind: 'agent'` variant** (agent-to-agent MCP).
  Ripped in the post-ship simplification. Re-adds with
  [`agent-as-mcp-server.md`](agent-as-mcp-server.md) once a concrete
  consumer lands. Orthogonal to auth.
- **MCP servers that don't implement the auth spec at all.** They
  work via tier 1 (the author registers + pastes a token manually).
  We don't try to support "discover something that isn't there."

## Related plans

- [`runtime-mcps.md`](runtime-mcps.md) — runner-side MCP plumbing.
  This plan extends its schema + auth surface.
- [`per-session-access-elevation.md`](per-session-access-elevation.md)
  — principal threading model. The per-asker storage shape composes
  with elevation; the session principal's identity is the
  per-user integration lookup key.
- [`approval-gated-tools.md`](approval-gated-tools.md) — per-MCP-tool
  approval gating, orthogonal to auth. A tool that requires approval
  AND uses a per-asker integration both work — the gate fires on
  call, the integration resolution happens on dispatch.
- [`agent-as-mcp-server.md`](agent-as-mcp-server.md) — inverse case:
  PostHog agents as MCP servers. Auth from the **server** side is
  PostHog's existing DCR provider implementation; this plan is the
  **client** side of the same protocol.
