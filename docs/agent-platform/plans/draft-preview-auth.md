# Design — draft preview via Django proxy (preview-proxy path)

**Status:** v1 (fail-closed enforcement) shipped; v0 skipped; v2 activity-log pending. **Owner:** ben.

> Confirmed PoC: an `auth.mode: 'public'` draft is invokable
> anonymously via the `<slug>-<prefix>` form (path mode) or the
> subdomain form (`<hex>.<slug>.agents.posthog.com`, prod). A live
> revision can be locked down with `auth.mode: 'pat'` and the draft
> still answers anyone who knows (or guesses) its UUID prefix.

## 1. Problem

The override-resolution paths
([`revision-routing.md`](revision-routing.md)) point at a non-live
revision, then run `authorize()` against **that revision's**
`spec.auth.mode`. If the draft says `public`, anyone who knows the
URL invokes it anonymously — even if the live revision requires a
PAT, an internal header, or a shared secret. Live auth doesn't
protect the draft surface.

The right contract is that the draft's _own_ `spec.auth.mode` still
governs **what runs against it once invoked** (authors keep `public`
during dev so they don't have to set up a PAT loop), but **getting
to the draft surface at all** requires a trusted authoring source.

## 2. Why a proxy, not a token-in-URL

An earlier shape of this plan minted HMAC-signed tokens embedded in
the preview URL. We rejected it because:

- **LLM safety.** An authoring AI handling preview URLs would have
  to handle a secret-bearing token. Even with TTLs and HMAC the
  raw URL trivially leaks into LLM transcripts, Slack pastes, log
  files. One leaked URL is a working credential until its expiry.
- **No good URL-redaction story.** Tokens look enough like
  opaque-ID-blobs that ingress / janitor log scrubbers would have
  to learn a new shape.
- **Operational rotation.** Rotating the HMAC secret invalidates
  every outstanding preview URL — same hazard as rotating
  `SECRET_KEY`, but the URLs sit in customer Slack threads forever.

Instead, Django proxies. Django mints a **short-lived HS256 JWT bound
to the (application, revision) being invoked** and attaches it as
`x-agent-preview-token` when forwarding to the ingress. The signing
secret never leaves the Django ↔ ingress server-server boundary.

```text
   MCP / UI / teammate
          │
          │  POST  /api/projects/X/agent_applications/<app>/preview-proxy/run
          │        ?revision_id=<draft-uuid>
          │  (authenticated as a Django user)
          ▼
        Django proxy
          │
          │  mints JWT{ aud, app, rev, exp=60s, sub=user-id }
          │  POST  /agents/<slug>-<rev-hex>/run
          │  x-agent-preview-token: <jwt>
          ▼
        Ingress  ─►  verify HS256 sig + aud + exp + app+rev claims  →  enqueue
```

The secret never leaves the Django ↔ ingress server-server boundary.
LLMs / browsers / Slack URLs only ever see PostHog's normal Django
URLs and PostHog's normal auth flow. A captured proxy → ingress
request expires within 60s and can't be replayed against any other
(app, rev) pair.

## 3. The Django proxy endpoint

New nested action on `AgentApplicationViewSet`:

```text
ANY  /api/projects/<team>/agent_applications/<app>/preview-proxy/<rest>?revision_id=<uuid>
```

Routes:

- Auth: the **standard** Django auth (session cookie or PAT) — same
  scopes as `agent_application:read`. Users without read on the
  agent can't invoke its drafts.
- Validate that `<rest>` matches one of the allowlisted ingress
  paths: `run` (POST), `send` (POST), `cancel` (POST),
  `listen` (GET, SSE), and the webhook trigger
  `webhook/<path>` (POST). Anything else 404s without forwarding.
- Resolve the revision: `revision_id` must be present in the query
  string and must belong to `<app>`. Refuse if it does — no
  cross-app reuse.
- Refuse if `revision_id == application.live_revision_id`. Live
  invocation has its own public ingress URL; the proxy is
  draft-only by contract. Forces a hard separation between
  "production traffic" and "preview traffic" in metrics and logs.
- Forward to `INGRESS_URL/agents/<slug>-<rev-hex>/<rest>`, where
  `<rev-hex>` is the full 32-char UUID hex (dashes stripped). Single
  resolver code path on the ingress — no separate `?revision_id=`
  query handling. Attaches:
  - `x-agent-preview-token: <jwt>` — short-lived HS256 token,
    `aud=posthog:agent_preview`, claims `{ app, rev, sub=user-id,
exp=now+60s }`. The ingress verifies signature + claim-binding.
  - the request body, headers (minus `Host`, `Authorization`,
    `Cookie` — those identify the _Django_ caller, not the agent's
    caller).

The response streams back to the original caller. `StreamingHttpResponse`
handles SSE (`listen`) cleanly under granian / ASGI; chunked
proxying for the rest. Connection close on the original side
propagates to the upstream call via `requests.get(stream=True)` plus
`.close()` semantics.

## 4. The ingress gate

On any non-live resolution the resolver verifies the JWT:

1. Header `x-agent-preview-token` must be present.
2. `jose.jwtVerify(token, secret, { audience, algorithms: ['HS256'] })`
   — bad signature, wrong audience, or expired token all throw.
3. `payload.app === resolved.application.id` — token must be bound
   to the application being invoked.
4. `payload.rev === resolved.revision.id` — token must be bound to
   the specific revision being invoked.

Any check fails → `MissingPreviewSecretError` with a `reason` tag.
The trigger-side helper catches the error and returns a 401 with the
reason in the body, so debugging a misconfigured proxy is concrete:
`{ "error": "preview_token_required", "reason": "token_verify_failed: ..." }`.

The shared secret comes from `AGENT_PREVIEW_SECRET` env on both the
ingress and the Django side. Distinct from Django's `SECRET_KEY` —
the ingress shouldn't be trusted with Django's master key. v0 falls
back to `AGENT_JANITOR_SECRET` (which Django already shares with the
janitor) to keep dev setup simple.

The `previewSecret` value being unset (dev / harness path) bypasses
the gate entirely. Production wires it.

## 5. What about Slack / webhook drafts?

A Slack-trigger or webhook-trigger draft can't be tested via the
proxy because external callers (Slack event subscriptions, customer
Zapier flows) need to hit a stable public URL — they can't be
asked to authenticate through Django first.

Three options for those cases:

1. **Promote-to-test.** Draft a new app slug, promote it, test
   against that. Once verified, archive the test app. Heavy but
   clean.
2. **Slack app per environment.** Register a separate Slack app
   for staging; each draft is wired to its dedicated Slack app
   URL. Standard Slack dev workflow anyway.
3. **Time-bound exception URL.** A future plan could mint
   per-draft URLs for Slack / webhook with the token-in-URL
   approach for _this narrow case only_. Out of scope for v0 —
   tackle when a customer asks.

We expect (1) and (2) to cover the vast majority of dev workflows.
The proxy path covers (a) authoring-AI test runs, (b) UI preview
buttons, (c) human teammate-review of a chat draft — which are the
high-value cases.

## 6. Inner auth contract — unchanged

After the gate passes, `authorize()` runs against
`resolved.revision.spec.auth.mode` exactly as today. A draft with
`mode: 'public'` still treats the proxied invocation as anonymous —
but only callers who passed through Django's auth and the
preview-secret check ever reach `authorize()` for the draft.

This preserves the existing two-layer model:

1. **Ingress entry gate** — "who can talk to this surface at all".
   For live: the public DNS shape. For drafts: must come through
   Django's proxy (carrying the secret).
2. **Spec auth gate** — "what principal the session runs under".
   `spec.auth.mode` unchanged.

For the **live** path nothing changes. A live revision with
`auth.mode: 'public'` keeps being publicly invokable on its
ingress URL.

## 7. MCP integration

A new MCP tool `agent-applications-revisions-invoke-create`:

```text
agent-applications-revisions-invoke-create {
    "id": "<app-uuid>",
    "session_id": "<existing-uuid-or-omit-for-new>",
    "revision_id": "<draft-uuid>",
    "message": "string"
}
```

The tool calls the Django `preview-proxy/run` endpoint (for new
sessions) or `preview-proxy/send` (for follow-ups). MCP's auth is
already the user's PAT, which has team-scoped read access, so the
authorization-via-Django chain works naturally.

The authoring AI can now build, validate, and invoke drafts entirely
through MCP — no need to ever construct an ingress URL manually.

This makes the suggestion in
[`agent-authoring-flow.md`](agent-authoring-flow.md) §5 concrete:
the AI's "run a test against the draft" step is one tool call, not
a URL-construction exercise.

## 8. Surfaces that change

- **agent-ingress** — `previewSecret` on `ResolverOpts`; the gate
  inside `resolveBySlug`; env wiring for `AGENT_PREVIEW_SECRET`
  (reuses `INTERNAL_SECRET` value by convention in v0).
- **Django (`products/agent_platform/backend/api.py`)** — new
  `preview_proxy` action on `AgentApplicationViewSet`; uses
  `requests` with `stream=True` so SSE works. Same allowlist of
  `<rest>` paths shipped in code.
- **MCP YAML** — `agent-applications-revisions-invoke-create`
  tool entry. The proxy-path itself isn't a great MCP surface (it's
  too generic); the invoke tool wraps it as a chat-trigger send.
- **agent-tests harness** — no change required. The harness drives
  the ingress directly with an in-process `RevisionResolver`; the
  gate can be opt-in (`previewSecret: undefined` skips the check
  in dev).

## 9. Rollout

**v0 — observe.** Skipped in practice.

Originally planned as advisory mode (log-only) followed by a v1
flip to fail-closed. Implementation jumped straight to fail-closed
semantics because the gate is part of the same code path that does
revision resolution — there's no clean "warn but continue" branch
without duplicating the verifier. The compatibility risk this v0
mitigated (legacy bookmarks, undocumented automation) didn't
materialize: the override paths only ever existed for authoring AIs
hitting the MCP, all of which now go through Django's
`preview_proxy`.

**v1 — enforce.** ✅ shipped.

- Resolver verifies the JWT via `MissingPreviewSecretError` and
  refuses non-live invokes that fail any of: missing token, bad
  signature, expired, wrong audience, `app` or `rev` claim mismatch.
  See `services/agent-ingress/src/routing/resolver.ts`.
- Config: `AGENT_PREVIEW_SECRET` on ingress, mirrored to Django.
  When unset, the gate is bypassed (dev / harness behaviour) — this
  replaced the originally-planned `AGENT_PREVIEW_ENFORCED` knob; the
  presence/absence of the secret is the enforcement signal.
- Django `preview_proxy` action mints `{app, rev, aud='posthog:agent_preview',
exp=now+60s, sub=user-id}` and forwards the request.
- MCP tool surface: lands on the existing
  `agent-applications-preview-proxy` action (GET + POST) under
  `products/agent_platform/backend/api.py` rather than a new
  `agent-applications-revisions-invoke-create` tool — same effect,
  one fewer name.

**v2 — activity-log + observability.** Not yet built.

- Successful preview invokes write to the activity log (cross-cut
  introduced by B.1) with `preview_issuer` (Django user id),
  `application_id`, `revision_id`. So "who hit my draft" is
  answerable from PostHog.
- Per-team metric: count of preview invokes by issuer + revision,
  for dashboards.

## 10. Operational concerns

1. **Secret rotation.** `AGENT_PREVIEW_SECRET` rotates like the
   existing `INTERNAL_SECRET`: deploy the new secret first to the
   ingress (accepting either of two values during overlap), then
   to Django. No URLs to invalidate — secret lives only between
   Django and ingress.
2. **Cross-region.** US-deployment Django proxies to US ingress;
   EU Django to EU ingress. The proxy URL is `posthog.com`-scoped
   per region anyway.
3. **Latency.** Every preview invoke adds one Django hop. Acceptable
   for human-driven UI clicks; the authoring-AI testing loop is the
   higher-volume case but it's also the case where one extra hop
   inside a multi-second model call is noise. Stream-through the
   SSE response so `/listen` doesn't double-buffer.
4. **Audit logging.** The proxy lives inside Django so we get the
   PostHog request audit trail (user, IP, project) for free. The
   ingress side adds the agent-platform activity-log entry. Two
   logs join cleanly on `application_id + revision_id + ts`.
5. **Header allowlist.** Don't forward `Host`, `Authorization`,
   `Cookie` upstream — they reference Django session state, not
   the agent's caller. Do forward `Content-Type`, custom headers
   the body uses. Allowlist-not-blocklist.

## 11. Open questions

1. **`x-posthog-mcp-conversation-id` carry-through.** When MCP
   invokes a draft via the proxy, the conversation ID should
   propagate so the resulting session is linkable back to the MCP
   conversation that started it. Need to forward this header in
   the proxy path (allowlisted).
2. **Multipart bodies.** Webhook drafts could in theory accept
   multipart payloads. Django's proxy needs to stream the body
   without buffering. Skip for v0 — drafts are JSON-only.
3. **Long-lived `/listen` SSE under granian.** The proxy holds an
   upstream connection open. granian + ASGI can do this, but it
   ties up a worker. Worth benchmarking once we have a handful of
   simultaneous preview streams.
4. **Concurrency limits on the proxy.** Should the proxy share
   per-team rate-limit budget with the live ingress, or have its
   own? Composes with
   [`rate-limiting-sessions.md`](rate-limiting-sessions.md). Plan:
   preview invokes count against the same budget by default;
   teams that want to test heavily can lift the cap themselves.

## 12. Dependencies + what this enables

**Hard depends on:** nothing. Django proxy + ingress gate are new
code; the `INTERNAL_SECRET` reuse means no new env wiring.

**Composes with:**

- [`revision-routing.md`](revision-routing.md) — the proxy hits the
  ingress via the suffix form (`<slug>-<rev-hex>`), same code path
  that resolves the production subdomain shape. Single resolver
  branch for non-live invokes; the live path stays untouched.
- [`per-session-access-elevation.md`](per-session-access-elevation.md)
  §8 — activity-log integration captures `preview_issuer`.
- [`agent-authoring-flow.md`](agent-authoring-flow.md) — the
  authoring AI's "test the draft" step uses the new MCP tool.
- [`rate-limiting-sessions.md`](rate-limiting-sessions.md) —
  preview invokes share team budget by default.

**What this unblocks:**

- Closing the anonymous-draft-invoke gap surfaced in the audit.
- A real "preview" button in the authoring UI that doesn't
  require constructing or sharing secret URLs.
- MCP-driven `build → validate → invoke draft` as a single
  closed loop without ever exposing routing-layer secrets to the
  LLM.
