# Design — revision routing (subdomain for prod, suffix for local-dev)

**Status:** draft. **Owner:** ben.

Today draft / ready revisions are reachable for testing via
`?revision_id=<full-uuid>` on the chat trigger (added in
[`per-turn-cost-capture.md`](per-turn-cost-capture.md)'s sibling commit,
shipped in [services/agent-ingress/src/routing/resolver.ts]). That
works but it's ugly:

- Sharing a draft link to a teammate means pasting a 36-character UUID.
- Slack mentions, webhook URLs, and emails don't render UUIDs nicely.
- The override is invisible in the URL path — easy to miss in logs.

This plan adds two ergonomic alternatives that resolve to the same
codepath.

## 1. Two forms, one resolver

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

### 1.3 Existing `?revision_id` override

Still works in both modes for callers that have the full UUID and
don't want to think about prefixes. UUID wins if both forms are
present (subdomain says one revision but `?revision_id=` says
another → the query param's revision is used).

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
async resolveBySlug(rawSlug: string, opts?: { revisionId?: string }): Promise<ResolvedAgent | null> {
    // 1. Explicit override always wins.
    if (opts?.revisionId) {
        return this.resolveExplicitRevision(rawSlug, opts.revisionId)
    }

    // 2. Try suffix split: <slug>-<8-32 hex> ?
    const splitMatch = rawSlug.match(/^(.+)-([0-9a-f]{8,32})$/)
    if (splitMatch) {
        const [, baseSlug, prefix] = splitMatch
        // 2a. Does <baseSlug> resolve to an application?
        const baseApp = await this.opts.revisions.getApplicationBySlug(this.opts.teamId, baseSlug)
        if (baseApp) {
            // Match revisions on this app whose id starts with the prefix.
            const candidates = await this.opts.revisions.listRevisionsByIdPrefix(baseApp.id, prefix)
            if (candidates.length === 1) {
                return this.ownershipCheck(baseApp, candidates[0])
            }
            if (candidates.length > 1) {
                throw new AmbiguousRevisionError(baseApp.id, prefix, candidates.map((c) => c.id))
            }
            // No candidate — fall through and try the slug verbatim. This is
            // important: a slug "my-agent-abcdefab" might legitimately exist
            // as a top-level slug ending in 8 hex chars.
        }
    }

    // 3. Verbatim slug lookup (today's path).
    const application = await this.opts.revisions.getApplicationBySlug(this.opts.teamId, rawSlug)
    if (!application || application.archived || !application.live_revision_id) {
        return null
    }
    const revision = await this.opts.revisions.getRevision(application.live_revision_id)
    if (!revision) {
        return null
    }
    return { application, revision }
}
```

Two extension points required on `RevisionStore`:

- `listRevisionsByIdPrefix(applicationId: string, prefix: string):
Promise<AgentRevision[]>` — backed by `id::text LIKE $prefix || '%'`
  on the PG impl. Index already exists (the PK).
- An `AmbiguousRevisionError` class the ingress translates into a
  400 with the candidate list.

## 4. Resolver logic (domain mode)

Domain-mode `extractSlugFromHost` already strips `.agents.posthog.com`
and treats the remainder as the slug. Today that means a single label.

After:

```typescript
extractSlugAndRevisionFromHost(host: string): { slug: string; revisionPrefix?: string } | null {
    const hostNoPort = host.split(':')[0]
    const suffix = this.opts.domainSuffix
    if (!suffix || !hostNoPort.endsWith(suffix)) {
        return null
    }
    const labels = hostNoPort.slice(0, -suffix.length).split('.')
    // <revision>.<slug>.agents.posthog.com → labels = ['<revision>', '<slug>']
    // <slug>.agents.posthog.com            → labels = ['<slug>']
    if (labels.length === 2 && /^[0-9a-f]{8,32}$/.test(labels[0])) {
        return { slug: labels[1], revisionPrefix: labels[0] }
    }
    if (labels.length === 1 && labels[0].length > 0) {
        return { slug: labels[0] }
    }
    return null  // 3+ labels or unrecognized shape → reject
}
```

The resolver then takes that shape, applies the same prefix lookup
as path mode if `revisionPrefix` is present.

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

**v0 — local-dev suffix.**

- `extractSlugFromPath` → `extractSlugAndRevisionFromPath`, returns
  `{ slug, revisionPrefix? }`.
- `RevisionStore.listRevisionsByIdPrefix()` lands on the interface
  - memory + PG impls.
- Ambiguity error path with helpful body.
- e2e case: `tier-2/suffix-route.test.ts` against the local cluster.

**v1 — production subdomain.**

- Domain-mode `extractSlugAndRevisionFromHost`.
- Deploy: two-level wildcard cert added.
- Authoring UI shows the subdomain preview URL on the revision row.

**v2 — activity log + observability.**

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
