# Integration Gateway

A standalone, hardened plugin-server service that owns third-party integration credentials. It is
the single place that decrypts integration secrets and refreshes OAuth tokens, so Fernet key
material and OAuth client secrets stop living in the environment of every service that happens to
touch an integration.

> Design context: [RFC — Shared integration & credential service](https://github.com/PostHog/requests-for-comments-internal/pull/1199).

## Why this exists

- **Blast radius.** Today every consumer that reads an integration (CDP, workflows, data warehouse,
  batch exports, …) holds the Fernet decryption keys and provider client secrets in its own env. If
  one pod is popped, we have to rotate _everything_. Centralising credential access into one
  isolated, audited service shrinks that surface to a single place we can cordon off and watch.
- **Consistency.** One standard way to access, refresh, and (eventually) connect and proxy
  integrations — instead of the bespoke, subtly-different implementation each consumer grows.

## What it does today

Runs as its own process: `PLUGIN_SERVER_MODE=integration-gateway` (see `src/servers/integration-gateway-server.ts`).

- **Credential access** — `POST /api/v1/credentials/fetch`. Callers present a short-lived,
  team-scoped JWT (never the internal API secret); the gateway returns the decrypted integrations
  for that team in a batch. Wrong-team / missing ids come back `null` (indistinguishable on
  purpose). Reads are served from a short-TTL in-process cache and every request emits a per-caller
  audit line — the durable "who read which credential, when, on whose behalf" trail. Plaintext
  credentials only ever live in this process's heap.
- **Just-in-time OAuth refresh** — when an owned integration's access token is past half-life, it is
  refreshed on the read path (Redis single-flight lock, re-encrypted, persisted, fail-open) before
  it is cached. Ownership is gated by `INTEGRATION_GATEWAY_REFRESH_KINDS` (capability contract) ×
  `INTEGRATION_GATEWAY_REFRESH_TEAMS` (rollout gate, ids or `*`). Django's Celery beat excludes
  exactly that `(kind, team)` set, so every row has precisely one refresher.
- **Consumer wiring** — the CDP reads through the gateway behind `CDP_INTEGRATION_GATEWAY_ROLLOUT`
  and fails open to Postgres if the gateway is disabled, misconfigured, or unreachable.

### File map

| File                      | Responsibility                                                              |
| ------------------------- | --------------------------------------------------------------------------- |
| `router.ts`               | `POST /api/v1/credentials/fetch` handler                                    |
| `auth.ts`                 | scoped-JWT verification (fails closed)                                      |
| `integration.service.ts`  | load → team-scope → JIT-refresh → decrypt → cache                           |
| `repository.ts`           | `posthog_integration` data access                                           |
| `cache.ts`                | short-TTL in-process decrypted-credential cache                             |
| `refresh/`                | JIT OAuth refresh: `expiry.ts`, `providers.ts`, `manager.ts` (Redis-locked) |
| `audit.ts` / `metrics.ts` | per-caller audit log + Prometheus counters                                  |
| `config.ts`               | gateway config + `(kind, team)` refresh gate parsing                        |

Crypto is the shared `EncryptedFields` helper at `common/utils/encryption-utils.ts` (byte-compatible
with Django's `EncryptedFieldMixin`). The Django side lives in `posthog/integration_gateway_jwt.py`,
`posthog/settings/integrations.py`, and `posthog/tasks/integrations.py`.

## Running locally

Enabled via the hogli capability `nodejs_integration_gateway` (attached to the `product_analytics`,
`workflows`, and `pipelines` intents). It listens on port `6747`; dev defaults set
`ENCRYPTION_SALT_KEYS` and `INTEGRATION_GATEWAY_JWT_SECRET=integration-gateway-dev-secret` so the
flow works out of the box. Standalone: `PLUGIN_SERVER_MODE=integration-gateway HTTP_SERVER_PORT=6747 ./bin/posthog-node`.

## Roadmap

The service is being built in phases. Each phase widens what it owns, and correspondingly narrows
what Django and the individual consumers have to hold.

### Phase 1 — Centralise access & refresh _(current)_

Stand the service up and route all integration credential **access** through it — most importantly
**refresh**. Refresh moves from Celery's periodic background sweep to **just-in-time** (refresh
on read, at half-life), so we can retire the Celery-based background refresh for the kinds and
teams the gateway owns. This is the work started here: the credential-fetch API, JIT refresh with
the `(kind, team)` rollout gate, CDP cutover behind a rollout flag, and auditing.

### Phase 2 — Own the connect / OAuth setup flow

Move integration **setup** here too. Django keeps only the web-UI element: a standardised entry
point that redirects into the gateway to "start connecting `<provider>`". The gateway owns the
whole OAuth flow — client ids/secrets, redirect URLs, scope negotiation, and storing the resulting
integration — then redirects back to wherever the caller wants via stored state / a return URL.
Django (and every other service) stops holding provisioning credentials; accounts get created under
engineering credentials with clear ownership rather than whoever happened to set them up.

### Phase 3 — Proxy mode

For providers we can support, callers stop loading credentials at all. Instead of "give me team X's
token so I can call the API", a caller asks the gateway to **make the call on its behalf**: the
gateway loads the credential, injects the right authorization header, and proxies the request to the
provider. Plaintext credentials never leave the service for proxied providers, and every outbound
call is attributable and audited. Direct credential fetch (Phase 1) stays for the cases that
genuinely need the raw secret (e.g. S3 for batch exports).

## Known follow-ups (before wider rollout)

- **Single source of truth for the refresh partition.** The `(kinds × teams)` split that decides
  who refreshes a row currently lives in two places — the gateway's `INTEGRATION_GATEWAY_REFRESH_*`
  env and Django's matching settings. Both drift directions fail silently: if they disagree, either
  nothing refreshes a row or _both_ do (racing refreshers can invalidate a rotating refresh token).
  Before enabling any kind for real, move the partition to one authority both sides read (or add an
  alert on disagreement). Until then, the two must be changed together as one operational step.
- **Durable audit sink.** The credential-access audit trail is emitted to logs, which is fine for
  Phase 1 but only as durable as log retention. If this becomes the authoritative "who accessed
  which credential, when" record, it needs a real sink (e.g. an append-only store) rather than logs.
