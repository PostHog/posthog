# Design — sessions world map (geo distribution of agent sessions)

**Status:** draft. **Owner:** Ben. **Tracking:** [`_TODO.md`](_TODO.md).

## 1. Problem

The agent-console agents page (`services/agent-console/src/screens/AgentsList.tsx`)
has no answer to "where in the world are sessions coming from?" That's a
high-signal at-a-glance view — useful for a fleet overview hero, a per-agent
overview tile, and for spotting unexpected geographies (compromised credentials,
mis-routed traffic, demand from a region we haven't targeted).

We can't ship it today because nothing in the pipeline records the originating
IP or any geo property on a session row. This doc covers what to capture, where,
how to roll it up, and how to render it.

## 2. What's missing

Walked end-to-end:

| Layer                                                     | Today                                                                                                                                                                                                         | Need                                                                                                                                    |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `services/agent-ingress/src/triggers/*.ts`                | Trigger handlers (`chat.ts`, `webhook.ts`, `slack.ts`, `mcp.ts`) build a `SessionPrincipal` + seed message and call `enqueueOrResume(...)`. No request IP, no `req.headers['x-forwarded-for']` read anywhere. | Pull client IP (XFF-aware, behind our proxy chain) per trigger; pass into `enqueueOrResume`.                                            |
| `services/agent-shared/src/spec/spec.ts` — `AgentSession` | `principal`, `trigger_metadata`, `external_key`, usage etc. No IP, no geo.                                                                                                                                    | Add `origin: { ip_hash, country_code, region, city, lat, lng, source } \| null` — fixed shape, not freeform JSON.                       |
| `services/agent-shared/src/persistence/pg-queue.ts`       | `enqueue(session)` writes the row; SQL schema is owned by `@posthog/agent-migrations` and has no `origin` column.                                                                                             | New migration adds `origin JSONB` (nullable). Skip-index by `(team_id, (origin->>'country_code'))` so the rollup is fast.               |
| GeoIP lookup                                              | `posthog/geoip.py` exists on the Django side (MaxMind GeoIP2 wrapper). Node services have no equivalent — no `geoip-lite` / `maxmind` dep.                                                                    | Pick one: see §5. Recommended: do lookup at write time in ingress against a bundled mmdb, fall back to country-only on miss.            |
| Janitor rollup                                            | `services/agent-janitor/src/server.ts` exposes `/fleet/stats`, `/sessions/stats`, `/sessions/live`. None of these surface geo.                                                                                | Add `GET /fleet/origin_breakdown?team_id=...&since=...` returning `{ results: [{ country_code, country_name, count, last_seen_at }] }`. |
| Django proxy + types                                      | `products/agent_platform/backend/api.py` proxies `AgentFleetViewSet` → janitor. Generated TS lands via `hogli build:openapi`.                                                                                 | Add a fleet action + drf-spectacular schema. Regen.                                                                                     |
| Frontend                                                  | No map dep today; `package.json` of `agent-console` has no `d3-geo` / `topojson` / `react-simple-maps`.                                                                                                       | Add a `<WorldMap />` screen + storyable component; pull rollup; render choropleth + optional pin clusters.                              |

## 3. Capture rules per trigger

Not every trigger has a usable origin — be explicit.

| Trigger                                          | Usable IP?                                            | What we record                                                                                  |
| ------------------------------------------------ | ----------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `chat` (`/run`)                                  | yes — real end-user browser/CLI                       | XFF-extracted client IP → geo                                                                   |
| `mcp`                                            | yes — MCP client (often a desktop / IDE)              | XFF-extracted client IP → geo                                                                   |
| `webhook`                                        | mixed — IP is the _caller server_, not their end user | record IP + label `source: 'webhook'` so the map can dim/filter these                           |
| `slack`                                          | no — Slack edge, not the user                         | `null` origin; if Slack workspace has a known timezone/region we could approximate, but skip v0 |
| `cron`                                           | no — scheduler                                        | `null` origin                                                                                   |
| `posthog_internal` / `shared_secret` / `service` | no                                                    | `null` origin                                                                                   |

`source` field disambiguates so the map UI can show "of N sessions, M had a usable origin."

## 4. Privacy

IP is PII. We do not need the raw IP to render the map — just the geo derivation.

- Persist `ip_hash` (HMAC-SHA256 with a per-team salt sourced from
  `ENCRYPTION_SALT_KEYS`), not the raw IP. Lets us answer "is this the same
  caller as that one?" without storing the IP itself.
- Persist coarse geo: `country_code`, `region`, `city` (string), plus
  `lat`/`lng` rounded to ~10km (2 decimal places) — enough for clustering, not
  enough to identify an address.
- Retention: `origin` cleared at the same point we clear `idempotency_key`
  (janitor sweep, 30-day retention — already in `cron-trigger-scheduler.md` §6).
- Opt-out: support `X-Agent-Geo-Disable: true` request header and a
  per-application spec field `spec.privacy.disable_origin_capture`. When set,
  `origin` is `null` regardless of trigger.
- Localhost / private-ranges short-circuit to `null` so dev sessions don't
  pollute the rollup with a single megacity.

## 5. GeoIP in Node — pick one

| Option                                        | Pros                                                            | Cons                                                                                       |
| --------------------------------------------- | --------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `maxmind` npm + bundled GeoLite2-City.mmdb    | Same data source as Django (`posthog/geoip.py`); offline; ~70MB | License compliance (need attribution + auto-refresh); image-size bump on agent-ingress     |
| `geoip-lite`                                  | Tiny, no extra deps, MIT                                        | DB is months stale; city accuracy poor; no continuous updates                              |
| Forward lookup to Django (`posthog/geoip.py`) | Reuses existing infra + update job                              | Adds a round-trip per session create; couples ingress (latency-sensitive) to Django uptime |
| Defer to janitor sweep (lazy)                 | Doesn't block enqueue path                                      | Adds a "geo missing" window where new sessions show no flag on the map until the sweep     |

**Recommendation:** `maxmind` npm with a daily refresh sidecar (same pattern
`posthog/geoip.py` uses on the Django side). Add the lookup to a shared
`@posthog/agent-shared/src/runtime/geoip.ts` so ingress + any future enricher
share one impl. ~70MB Docker layer is acceptable; this is a control-plane
service, not a hot loop.

## 6. Ingress changes

- `services/agent-ingress/src/lib.ts` — extract client IP from
  `req.headers['x-forwarded-for']` (first non-private hop) using a small
  `getClientIp(req, { trustedProxyCidrs })` helper. CIDR allowlist comes from
  `loadAgentIngressConfig` so prod can pin to our LB ranges.
- `src/triggers/chat.ts`, `mcp.ts`, `webhook.ts` — pass extracted IP into
  `enqueueOrResume`. `slack.ts` passes `null`.
- `src/enqueue/enqueue.ts` — accept `originIp?: string | null` on
  `EnqueueInput`; resolve via `GeoIpResolver` → build the `origin` object → set
  on the session row. Localhost / private-range → `null`.
- New `GeoIpResolver` interface in `agent-shared/src/runtime/geoip.ts`; one
  concrete impl `MaxMindGeoIpResolver`. Wired in `services/agent-ingress/src/index.ts`.

## 7. Storage

- New migration in `services/agent-migrations/`: `ALTER TABLE agent_session ADD
COLUMN origin JSONB NULL;` + `CREATE INDEX agent_session_origin_country ON
agent_session (team_id, ((origin->>'country_code'))) WHERE origin IS NOT NULL;`.
- `AgentSession.origin` typed in `services/agent-shared/src/spec/spec.ts`:

  ```ts
  export interface SessionOrigin {
    ip_hash: string
    source: 'chat' | 'webhook' | 'mcp'
    country_code: string | null
    country_name: string | null
    region: string | null
    city: string | null
    lat: number | null // rounded to 2dp
    lng: number | null // rounded to 2dp
  }
  ```

## 8. Janitor + Django rollup

- New janitor query
  `PgSessionQueue.aggregateOriginsForTeam(teamId, since): Promise<OriginBucket[]>`
  returning `{ country_code, country_name, count, last_seen_at, lat_centroid?, lng_centroid? }[]`.
  ClickHouse-shaped GROUP BY on the JSONB country field; the partial index above
  keeps this cheap.
- `services/agent-janitor/src/server.ts` adds
  `GET /fleet/origin_breakdown?team_id=...&since=...`.
- `products/agent_platform/backend/janitor_client.py` adds
  `aggregate_origins_for_team(...)`.
- `products/agent_platform/backend/api.py` — extend `AgentFleetViewSet` with
  `@action(detail=False, methods=["get"], url_path="origin_breakdown")`, with a
  drf-spectacular schema so generated types ([`frontend/generated/api.schemas.ts`](../../../frontend/generated/api.schemas.ts) +
  the MCP tool surface) get the new shape automatically.

## 9. Frontend

- `services/agent-console/src/lib/apiClient.ts` — add
  `getFleetOriginBreakdown(teamId): Promise<OriginBucket[]>` using the generated
  types.
- New component `src/components/WorldMap.tsx` — choropleth shaded by session
  count per country + tooltips. Use `react-simple-maps` (lightweight wrapper
  around d3-geo + topojson world-atlas); no need for a heavy mapping lib.
  Topojson is static — bundle once.
- New screen `src/screens/FleetMap.tsx` rendered at `/fleet/map`. Hooked into
  the dock as a new page kind so the concierge agent can navigate to it.
- Hero placement: also embed a compact `<WorldMap />` at the top of
  `AgentsList.tsx` between the `StatStrip` and the filter chips, ~120px tall,
  no labels — clickable through to the full map.
- Storybook: stories under
  `services/agent-console/src/components/WorldMap.stories.tsx` cover empty
  (no geo), single-country, global spread, top-10-cluster.

## 10. Tests

- `services/agent-ingress/src/enqueue/enqueue.test.ts` — `originIp` resolves
  through fake `GeoIpResolver` → row carries `origin`. Localhost short-circuit
  → `null`. Opt-out header / spec flag → `null`.
- `services/agent-shared/src/persistence/pg-impls.test.ts` —
  `aggregateOriginsForTeam` returns expected buckets.
- `services/agent-tests/src/cases/` — new e2e case
  `world-map-rollup.test.ts` drives a few sessions, hits the rollup, checks
  Django proxy + janitor agree.

## 11. Phasing

1. **Phase A — capture.** Migration + spec field + ingress XFF parse +
   `GeoIpResolver` interface (with a stub impl that returns `null`). Lands the
   schema change without a real geo lookup. **Why first:** lets us start
   collecting `ip_hash` so we have _some_ historical signal once the lookup
   ships.
2. **Phase B — lookup.** `MaxMindGeoIpResolver` + sidecar refresh. Past
   sessions stay `null`; new ones get geo. No backfill — historical IPs are
   already discarded.
3. **Phase C — rollup + map.** Janitor endpoint, Django proxy,
   `<WorldMap />`, fleet map screen, agents-list hero embed.
4. **Phase D (optional) — per-agent map.** Reuse the same rollup with
   `application_id` filter; embed under each agent's Overview tab.

## 12. Open questions

- Do we want any live "pin drops" (last N sessions with a flying-dot animation)
  on top of the choropleth? Cute, but the rollup endpoint is window-based —
  we'd need an SSE stream off `/sessions/live` plumbed into the map. Defer to
  Phase D.
- MaxMind GeoLite2 license requires public attribution. Where does that go —
  footer of the world-map page only, or app-wide? (Posture: footer of the
  world-map page only.)
- Slack origin: can we infer a country from the Slack workspace's metadata
  (`team.discovery.info` returns a region for Enterprise Grid)? Probably not
  worth the API call cost; map shows "Slack" in a "no geo" callout instead.
- Webhook origin: a customer's webhook caller is often AWS us-east-1 — the
  map would over-weight Virginia. Should webhook sessions be excluded from
  the default choropleth and only visible behind a "include service origins"
  toggle?
