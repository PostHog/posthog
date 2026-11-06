# Freeform React Canvases — Design Plan

> Status: edit-tier shipped; publish/sharing tiers (below) scoped, not yet built.
> Scope: canvases are agent-authored freeform React, executed in a sandboxed
> iframe, shareable externally without leaking credentials.

## Summary

A canvas is a freeform React app: the user talks to an agent, the agent writes a
single React file (JSX, runtime — no user-managed build step), and we render it in
a sandboxed iframe. Canvases are shareable with external people via a unique URL,
with PostHog credentials never present in the iframe.

Driven by all four motivations surfaced in grilling: arbitrary interactivity,
external shareability, easier/more reliable agent authoring, and the catalog's
expressiveness ceiling.

## Non-negotiable principle

**The real PostHog token never enters the iframe. The proxy's *scope* — not the
key's secrecy — is the security boundary.** Hiding the key only defeats the laziest
attacker; an open data path + open egress arms every real one. Every decision below
follows from this.

---

## Data access: insights, not `/query`

**To fetch PostHog data, go through insights — not the `/query` endpoint.** Insights
provide the data avenue that internally handles caching and cold-boot issues;
`/query` does not. So:

- Named, server-stored queries (see security model) are backed by **insights**, not
  raw HogQL against `/query`.
- The agent, during authoring, **creates/registers insights** and the canvas calls
  them by reference. The insight layer owns caching + cold-boot, which also makes the
  live public proxy cheap and resilient (external views hit cached insight results,
  not cold queries).
- Freeform canvases query through `canvasDataService` (`ph.query` → host →
  `/api/projects/{id}/query/`, cached `refresh: "blocking"`). The named-insight
  avenue above is the planned public-tier model (see the two-tier security model).

---

## Two-tier security model (keystone)

| | **Edit tier** | **Public tier** |
|---|---|---|
| Who | Authed author (own data) | Anyone with the share URL |
| Data | Full PostHog API via shim | **Named insights only**, allowlisted |
| Packages | esm.sh CDN | Self-hosted, bundled into artifact |
| Egress | Open | **Closed** (CSP `connect-src` = proxy only) |
| Token | Host process (app) | Cloud proxy |
| Iframe | sandboxed, null-origin | sandboxed, null-origin, usercontent domain |

A full-API proxy + open egress + external sharing cannot coexist safely (an external
viewer opening devtools on the iframe could replay the proxy call against any API
path = full token with extra steps). The two-tier split resolves this: full power for
the authed author, frozen + scoped + closed for public viewers.

### Publish = freeze step

`publish` transforms the canvas atomically:

1. **Bundle deps** — esbuild in **local workspace-server** rewrites esm.sh imports to
   pinned, self-hosted copies → one self-contained, inert artifact (egress can be
   closed). Static whitelist check re-runs here.
2. **Capture allowlist** — snapshot which named insights this canvas may call;
   public proxy rejects everything else.
3. **Pick freshness** (author choice, per canvas):
   - **Live** — public proxy re-runs the allowlisted insights on each view (cached
     via the insight layer, rate-limited, bounded params).
   - **Snapshot** — insight results captured at publish, inlined into the artifact;
     **no proxy at all** in public tier. Cheapest + safest default.

---

## Authoring loop

- **Agent-only in v1.** User talks; agent writes all code. No raw code editor yet.
  (Add later with a switch to targeted diffs so hand-edits and agent-edits stop
  fighting over the whole file.)
- **Full-file rewrite** per turn, single file.
- **Version history is first-class:** every turn snapshots the full file; undo/redo
  + revert to any prior version; the "current" pointer is what publishes. Undo
  semantics: **linear discard** (undo to v3 + new change discards v4/v5).
- **Error recovery** (to confirm during build): error boundary in iframe; compile +
  runtime errors piped back to the agent as an auto-fix turn; user keeps last-good
  render with a non-blocking "fixing…" toast rather than a white screen.

## Execution

- **Babel (in-browser)** transpiles JSX at render time.
- **esm.sh CDN packages in edit mode only.** Public artifacts are self-hosted/bundled.
- **Whitelist (curated, PostHog-anchored)** — start with:
  - `react`, `react-dom`
  - `@posthog/quill` (own design system, already self-hosted → on-brand shared canvases)
  - `recharts` (viz)
  - `dayjs` (format)
  - Expand only on real, observed demand.
- **Whitelist enforcement:** static import check at **save + publish**; reject any
  specifier not in the allowlist; **ban dynamic `import()` and inline `<script src>`**.

## Iframe sandbox & hosting

- **Public canvases served from a dedicated `*.posthog-usercontent.com` origin** —
  cookie/storage isolation is structural, not just attribute-dependent.
- `sandbox="allow-scripts"` with **`allow-same-origin` deliberately omitted** → null
  origin. (This is *why* data access must be postMessage: null origin can't share JS
  objects.)
- **CSP** locks `connect-src` to proxy only (public) / proxy + esm.sh (edit).
- Three independent isolation layers: sandbox attrs + separate origin + CSP.

## Data bridge

- Canvas holds only a **postMessage RPC shim** — never the real token.
  - Edit: `postMessage` → app host → `authService.authenticatedFetch` (token in host
    process).
  - Public: → **PostHog cloud proxy** endpoint, authed by a **per-canvas share/
    capability token** (not the API key), enforcing the insight allowlist + param
    bounds server-side.
- Same shim API surface in both tiers; transport target swaps.

## Hosting (cloud)

- **PostHog cloud serves** published canvases. Desktop/web's role shrinks to
  authoring + publishing.
  - Frozen bundle → cloud object storage on the usercontent CDN.
  - `{allowlist, freshness, share-token}` + named insights → persisted cloud-side.
  - Live proxy is a **cloud endpoint** (holds the real key).
- Share links work with the author's laptop closed. Snapshot canvases are pure static
  (no proxy).

## Architecture placement (per AGENTS.md layering)

| Piece | Home |
|---|---|
| esbuild bundle + static import check (Node) | `packages/workspace-server` |
| Canvas orchestration / agent driver / freshness + registry decisions | `packages/core` |
| iframe host + host-side shim | `packages/ui` |
| Publish upload, share-token proxy, named-insight registry | `@posthog/api-client` + **PostHog cloud (Django)** |

Build runs in **local workspace-server** (desktop + web), uploads an **inert**
artifact. The cloud owns the trust boundary (proxy + allowlist + token), so a
client-built bundle is safe — it can't exceed the server-side allowlist.

---

## Open items to resolve before/early in build

1. **Error-recovery loop** — confirm error-boundary + agent auto-fix-turn + last-good
   render behavior.
2. **Param-bounds spec** — how the agent declares typed/bounded params on named
   insights so the public proxy enforces ranges (`limit: 99999999` is soft exfil).
3. **Live-proxy abuse controls** — rate limits, cost caps, cache TTL (insight layer
   helps here).
4. **Permissions** — who can publish/share externally (org/project setting)? Does a
   shared canvas leak the *existence* of internal insight names?
5. **Undo branching** — confirm linear-discard vs branch-on-edit-after-undo.
6. **Snapshot staleness UX** — "data as of <date>" badge; how republish is triggered.

## Suggested phasing

- **Phase 1 — Edit-tier authoring.** Freeform React Blank canvas: agent-only loop,
  full-file rewrite, version history, Babel + esm.sh, in-app sandboxed iframe,
  postMessage shim → host (full API, author only). Insight-backed data. No sharing.
- **Phase 2 — Publish (snapshot).** Freeze step: local esbuild bundle + static check,
  upload inert artifact to usercontent CDN, static snapshot share links (no proxy).
- **Phase 3 — Publish (live).** Named-insight registry + cloud share-token proxy with
  allowlist + param bounds + rate/cost caps + closed egress.
- **Phase 4 — Polish.** Permissions, raw code editor (with diff-based edits),
  whitelist expansion, error-recovery refinements.
