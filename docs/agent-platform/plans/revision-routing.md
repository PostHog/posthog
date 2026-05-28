# Design — revision routing (subdomain for prod, suffix for local-dev)

**Status:** v0 shipped; v1 partially shipped (resolver in place, deploy + UI pending); v2 not yet built. **Owner:** ben.

There is one way to address a non-live revision: with a hex prefix
attached to the slug. Two transport shapes — subdomain for prod,
path-suffix for local dev — that both fold into the same internal
slug-with-suffix form before resolution. The earlier `?revision_id=`
query param and `x-agent-revision` header were dropped to keep the
contract single-shaped.

## 1. Two transports, one canonical form

### 1.1 Production: subdomain

```text
https://<revision-prefix>.<slug>.agents.posthog.com/<trigger>/...
```

For example, draft `019e6f25-…` on slug `weekly-digest` becomes:

```text
https://019e6f25.weekly-digest.agents.posthog.com/chat/run
```

The subdomain form is canonical in prod because:

- `*.agents.posthog.com` is already the wildcard cert + ingress DNS
  pattern; no new DNS plumbing.
- It's the natural URL to share — "this is a draft of the agent at
  X.Y.agents.posthog.com" — and reads cleanly in chat / docs.
- Cookies / CORS scope cleanly per (revision, slug) because the
  origin differs from the live origin.

### 1.2 Local dev: slug-with-revision-suffix

```text
http://localhost:3030/agents/<slug>-<revision-prefix>/<trigger>/...
```

For example:

```text
http://localhost:3030/agents/weekly-digest-019e6f25/chat/run
```

The suffix form is the local-dev fallback because dev runs all agents
on one ingress port (3030) with `ROUTING_MODE=path` — no wildcard
DNS, no subdomain matching. The suffix collapses the same routing
information into a single path segment.

### 1.3 Internal (Django proxy) — full UUID hex in the suffix

The preview-proxy in Django talks to the ingress over an internal URL
in path mode regardless of public deployment shape. It uses the
**full** 32-char UUID hex in the suffix
(`/agents/<slug>-<32hex>/<rest>`) so the resolver's prefix lookup is
collision-free by construction (a 32-char hex match is effectively
a UUID-PK lookup, just via the dash-stripped form). The same code
path handles all three callers — users see short prefixes; the proxy
sends full hex; the resolver doesn't care.

The earlier `?revision_id=` query param and `x-agent-revision`
header are gone. They predated the suffix form, became redundant
the moment it landed, and made the resolver carry two interchangeable
override paths. Single-shaped contract is cleaner.

## 2. Prefix length + ambiguity

`<revision-prefix>` is the **leading 8 hex chars** of the revision id
(the first segment of the UUID). 8 chars = 4 bytes = 4.3B namespace.
Per agent, that's effectively collision-free until tens of thousands
of revisions on the same slug.

When two revisions on the same slug share a prefix:

- The resolver MUST refuse to pick — return `400 ambiguous_revision`
  with both candidate ids in the body so the caller can re-issue
  with a longer prefix or the full UUID.
- The error is observable in the activity log — repeat occurrences
  flag a slug whose revision history is dense enough to need >8
  chars.

Authors who hit ambiguity can also pass the full UUID via subdomain
(`019e6f25b9be78fb8114533a6f6ff714.slug.agents.posthog.com`) — any
prefix length 8–32 is accepted.

## 3. Resolver logic (path mode)

Order of resolution in `routing/resolver.ts`:

```typescript
async resolveBySlug(
    rawSlug: string,
    opts?: { providedToken?: string }
): Promise<ResolvedAgent | null> {
    // 1. Try suffix split: <slug>-<8..32 hex> ?
    const splitMatch = rawSlug.match(/^(.+)-([0-9a-f]{8,32})$/i)
    if (splitMatch) {
        const [, baseSlug, prefix] = splitMatch
        // 1a. Does <baseSlug> resolve to an application?
        const baseApp = await this.opts.revisions.getApplicationBySlug(
            this.opts.teamId,
            baseSlug
        )
        if (baseApp) {
            // Match non-archived revisions whose id starts with the prefix.
            const candidates = await this.opts.revisions.listRevisionsByIdPrefix(
                baseApp.id,
                prefix
            )
            const live = candidates.filter((c) => c.state !== 'archived')
            if (live.length === 1) {
                return this.gate(baseApp, live[0], opts?.providedToken)
            }
            if (live.length > 1) {
                throw new AmbiguousRevisionError(
                    baseApp.id,
                    prefix,
                    live.map((c) => c.id)
                )
            }
            // No prefix match — fall through. A legitimate slug like
            // "my-agent-abcdefab" ending in 8 hex chars should still
            // resolve as a top-level slug.
        }
    }

    // 2. Verbatim slug lookup → application's live revision.
    const application = await this.opts.revisions.getApplicationBySlug(
        this.opts.teamId,
        rawSlug
    )
    if (!application || application.archived || !application.live_revision_id) {
        return null
    }
    const revision = await this.opts.revisions.getRevision(application.live_revision_id)
    return revision ? { application, revision } : null
}
```

The preview-token gate (see `draft-preview-auth.md`) fires inside
the suffix branch on non-live resolutions. The verbatim-slug branch
always resolves live, so the gate is a no-op.

Two extension points required on `RevisionStore`:

- `listRevisionsByIdPrefix(applicationId: string, prefix: string):
Promise<AgentRevision[]>` — backed by `id::text LIKE $prefix || '%'`
  on the PG impl. Index already exists (the PK).
- An `AmbiguousRevisionError` class the ingress translates into a
  400 with the candidate list.

## 4. Resolver logic (domain mode)

`extractSlugFromHost` returns the same `<slug>` or `<slug>-<hex>`
string that path mode produces, so the resolver only has one
suffix-matching code path. The extractor collapses the two-label
host shape into the canonical form:

```typescript
extractSlugFromHost(host: string): string | null {
    const hostNoPort = host.split(':')[0]
    const suffix = this.opts.domainSuffix
    if (!suffix || !hostNoPort.endsWith(suffix)) {
        return null
    }
    const labels = hostNoPort
        .slice(0, -suffix.length)
        .split('.')
        .filter(Boolean)
    // <slug>.agents.posthog.com            → 'slug'
    // <hex>.<slug>.agents.posthog.com      → 'slug-hex'
    if (labels.length === 1) {
        return labels[0] || null
    }
    if (labels.length === 2 && /^[0-9a-f]{8,32}$/i.test(labels[0])) {
        return `${labels[1]}-${labels[0]}`
    }
    return null
}
```

The host-mode and path-mode entrypoints both call `resolveBySlug`
with the same string shape — one resolver branch, two transports.

## 5. Production deploy: wildcard cert + ingress

`*.agents.posthog.com` already exists. The two-label form
(`X.Y.agents.posthog.com`) needs the cert to be `*.agents.posthog.com`
**AND** `*.*.agents.posthog.com` — Let's Encrypt issues two-level
wildcards as separate orders, but it works. Document this in
[`docs/agent-platform/docs/deploy-runbook.md`](../docs/deploy-runbook.md)
when the plan lands.

(Alternative considered: collapse to one label via a separator other
than `.`, e.g. `019e6f25-weekly-digest.agents.posthog.com`. Rejected
— hyphens inside the agent slug already exist, so this conflicts.
Subdomains with `.` are unambiguous.)

## 6. Slack / webhook URL implications

- Slack event subscriptions and slash commands accept any HTTPS URL.
  Authors who want to test a Slack-trigger draft just register
  `https://019e6f25.my-agent.agents.posthog.com/slack/events` as a
  separate Slack app. Once promoted, register the bare slug URL.
- Webhook callers (GitHub Actions, customer Zapier flows) can hit
  the suffix / subdomain form directly — no per-revision auth flow
  needed beyond what `auth.mode` on the spec already covers.

## 7. Surfaces that benefit

- **Authoring UI** — the agent-detail page shows "preview URL" for
  every ready / draft revision, copy-able as a one-click share.
- **`agent-authoring-flow.md`'s preview-link step** — currently
  speculative; this plan gives it a concrete URL shape.
- **`self-healing-agents.md`** — when the self-heal lands a draft for
  review, it pastes the preview URL into the GitHub PR / Slack thread
  so the human reviewer can chat with the candidate before promoting.

## 8. Open questions

1. **Trailing-dash slugs in the suffix split.** A slug "my-agent-"
   followed by an 8-hex prefix would parse as `(slug='my-agent',
prefix='<8hex>')`. We already validate slugs to not end in `-`
   (`[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?` regex in the serializer),
   so this is safe — but worth documenting the constraint.
2. **Promotion races.** If a draft is being promoted while a request
   carries its prefix, the prefix should still resolve to the same
   revision (state transition draft → live is fine; the row's id
   doesn't change). Tested case in
   [services/agent-tests/](../../services/agent-tests/).
3. **Activity log integration.** When a session is started via the
   override (any of the three forms), record `revision_override:
true` + the resolution method (`uuid_query` / `suffix` /
   `subdomain`) so authors can see who's been hitting which form.
4. **Archived revisions.** Today
   `resolveBySlug({revisionId})` refuses archived. Same rule for the
   prefix path — if the only matching revision is archived, treat as
   404 (don't silently fall through to live).

## 9. Rollout

**v0 — local-dev suffix.** ✅ shipped.

- `extractSlugFromPath` collapses two-label `<slug>-<hex>` URLs into
  a canonical slug + prefix in `services/agent-ingress/src/routing/resolver.ts`.
- `RevisionStore.listRevisionsByIdPrefix()` landed on the interface
  with memory + PG impls.
- Ambiguity error path lands at the global ingress `errorHandler`
  via `AmbiguousRevisionError → 400 { error: "ambiguous_revision" }`.
- e2e case in `services/agent-tests/src/cases/`.
- Consolidation: `?revision_id=` query + `x-agent-revision` header
  retired; suffix is the only non-live override form. The plan's
  v0 originally kept the UUID-query side-by-side; that's the only
  intentional divergence from the doc as written.

**v1 — production subdomain.** Partially shipped.

- Domain-mode `extractSlugFromHost` ships in the resolver (handles
  `<hex>.<slug>.<suffix>` two-label form). ✅ shipped.
- Deploy: two-level wildcard cert add — out of scope for the code
  repo; tracked separately.
- Authoring UI: revision row showing the preview URL — not yet
  built.

**v2 — activity log + observability.** Not yet built.

- Activity log carries the resolution shape.
- Metric: per-team count of suffix vs subdomain vs UUID-query
  invocations. Want to know what authors actually reach for.

## 10. Dependencies + what this enables

**Hard depends on:** nothing significant. The
`listRevisionsByIdPrefix` query is a one-line addition to
`PgRevisionStore`.

**Composes with:**

- [`agent-authoring-flow.md`](agent-authoring-flow.md) — preview
  links become a concrete URL shape, not just a TODO.
- [`per-session-access-elevation.md`](per-session-access-elevation.md)
  — the auth principal check fires on the revision spec, so the
  override path inherits the same authz rules; no change needed.
- [`self-healing-agents.md`](self-healing-agents.md) — the
  human-review step emits the subdomain preview URL.

**What this unblocks:**

- Sharing a draft to a teammate over Slack without copy-pasting a
  UUID.
- A/B testing two drafts side by side via two distinct subdomains.
- A cleaner authoring UX in general — every revision row gets a
  preview button that "just works".
