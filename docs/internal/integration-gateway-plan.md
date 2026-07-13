# Implementation plan: shared integration gateway (`integration-gateway`)

> Internal design doc. Companion to the "Shared integration & credential service" RFC. This is the
> buildable, code-grounded spec for the first two PRs, written so a different engineer (or agent) can
> implement it directly. File paths are relative to the monorepo root.

## Context

Today the `Integration` model (`posthog/models/integration.py`, ~4100 lines) stores third-party
credentials (`sensitive_config`, Fernet-encrypted per-leaf) plus plaintext `config`, and **every
consumer reaches into the database and decrypts credentials in-process**:

- **CDP / hog functions** (plugin-server, TS): `nodejs/src/cdp/services/managers/integration-manager.service.ts` runs raw SQL over `posthog_integration` and decrypts with `EncryptedFields.decryptObject` (`nodejs/src/cdp/utils/encryption-utils.ts`).
- **Batch exports** (Temporal): `products/batch_exports/backend/temporal/destinations/*.py` call `Integration.objects.aget(id=..., team_id=...)`.
- **Warehouse sources** (Temporal): e.g. `products/warehouse_sources/backend/temporal/data_imports/sources/stripe/source.py`.

So Fernet key material (`ENCRYPTION_SALT_KEYS`) and DB credentials live in many services' environments.
The motivating risk: if a single pod's environment is compromised, every credential reachable through
that environment has to be rotated, which is costly and hard to verify. The goal is to **isolate
credential access behind one hardened, audited service**, then progressively move OAuth orchestration,
token refresh, proxying, and storage (OpenBao) behind it.

This plan is delivered as **two stacked PRs**:

- **PR 1 (v1) — read-only credential gateway.** Fetch + decrypt credentials by integration id behind
  an auth boundary + audit trail. **Pure pass-through**: returns the stored access token as-is;
  Django/Celery still owns refresh. No writes.
- **PR 2 (stacked) — token refresh behind a feature flag.** Flag **off** → identical pass-through to
  v1. Flag **on** → check token age/validity and run the JIT refresh flow before returning. This is
  where the service becomes a writer.

Nothing else (proxy, OpenBao, per-integration definitions, usage-based claiming) is in these two PRs;
they're scoped as later phases against the stable interface this establishes.

### Locked decisions
1. **Name: `integration-gateway`.** New Rust crate `rust/integration-gateway/`, binary `integration-gateway`.
2. **Language: Rust**, in the `rust/` workspace.
3. **PR 1 = direct credential-fetch read API only.** No OAuth orchestration, no proxy, no writes, no refresh.
4. **Storage = wrap the existing `posthog_integration` Postgres table**, reuse `ENCRYPTION_SALT_KEYS`. OpenBao is a later phase.
5. **Caching = short-lived TTL only (~30s), no invalidation.** Do **not** subscribe to the `reload-integrations` pub/sub in v1. A 30s TTL is the entire staleness story; we may add push invalidation back later but explicitly don't want it now.
6. **Migration = strangler behind a feature flag** — consumers dual-read and flip gradually.
7. **Refresh is a stacked PR 2**, feature-flagged (off = pass-through, on = age-check + refresh). Build PR 1 without it first.

## Corrections to initial assumptions (verified against source)

1. **`RECORDING_API_JWT_SECRET` mint/verify does not exist** — only a comment at `posthog/settings/data_stores.py:543`. The real scoped-JWT helper is **`posthog/jwt.py`** (`encode_jwt`/`decode_jwt`, HS256, `PosthogJwtAudience` enum, `JWT_SIGNING_KEY` + `JWT_SIGNING_KEY_FALLBACKS`). We mint a dedicated secret, see §6.
2. **The Rust JWT example is gRPC, not axum.** `rust/capture-logs/src/auth.rs` verifies HS256 with `jsonwebtoken` but as a `tonic` extractor. Reuse the decode call; write an **axum** extractor. **`jsonwebtoken` is NOT a workspace dep** — `capture-logs` pins `jsonwebtoken = "8.3"` locally; do the same.
3. **Key derivation** (`posthog/helpers/encrypted_fields.py::EncryptedFieldMixin.keys`): primary keys are `urlsafe_b64encode(k.encode())` for each `k` in `ENCRYPTION_SALT_KEYS` (each exactly 32 bytes). Legacy decrypt-only keys are `urlsafe_b64encode(PBKDF2HMAC(SHA256, len=32, salt=salt_key, iters=100_000).derive(secret_key))` for every `secret_key ∈ [SECRET_KEY, *SECRET_KEY_FALLBACKS]` × `salt_key ∈ SALT_KEY`, all in a `MultiFernet`. Do **not** copy `flag_payload_decryptor.rs`'s pad/truncate derivation — it's wrong for this field.
4. `sensitive_config` is a JSON object whose **every leaf scalar is an independent Fernet token** (confirmed by `EncryptedJSONField._decrypt_values` and node `decryptObject`). Decrypt = recursive walk, decrypt each string leaf, pass through non-strings and undecryptable leaves (mirrors `ignore_decrypt_errors=True`).
5. The **CDP node decryptor only implements the salt-keys path** (`encryption-utils.ts`), not the PBKDF2 legacy fallbacks — so CDP already can't read pre-salt-keys rows. We implement **both** so the gateway is a superset.
6. Django refreshes tokens proactively (`posthog/tasks/integrations.py::refresh_integrations`, Celery beat every minute — `posthog/tasks/scheduled.py:669`; providers refresh at ~half the token lifetime). So a credential that's up to 30s stale in our cache is still a valid token — the short TTL is safe without push invalidation.

## Architecture (v1 / PR 1)

```
   consumers (CDP plugin-server · batch-exports · warehouse-sources)
        │  POST /api/v1/credentials/fetch   (scoped JWT: team_id + caller)
        ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  integration-gateway  (new Rust crate, axum)                    │
   │   • verify scoped JWT  → team_id claim                          │
   │   • load row(s) from posthog_integration (sqlx, read pool)      │
   │   • ENFORCE row.team_id == claim.team_id  (per-row)             │
   │   • decrypt sensitive_config per-leaf (Fernet MultiFernet)      │
   │   • in-proc moka cache, ~30s TTL (no invalidation)              │
   │   • per-caller audit log + Prometheus metrics                   │
   │   • PASS-THROUGH: returns stored access_token as-is             │
   └───────────────────────────────────────────────────────────────┘
        │ read (SELECT only)
        ▼
   Postgres posthog_integration  ◄──── Django + Celery still write/refresh (refresh_integrations beat)
```

No Redis in v1 (no pub/sub, no locking). Redis returns in PR 2 for the refresh lock.

## 1. Crate skeleton (PR 1)

New crate `rust/integration-gateway/`, modeled on `rust/property-defs-rs` (simplest axum+lifecycle
skeleton) and `rust/feature-flags` (crypto + cache + sqlx). Register in `rust/Cargo.toml` `members`,
`.github/rust-images.yml` (+ deploy matrix in `.github/workflows/rust-docker-build.yml`),
`dockerfile: ./rust/Dockerfile`, own GCP `project` id (ask infra).

```
rust/integration-gateway/
  Cargo.toml            # deps below; [lints] workspace = true
  src/
    main.rs             # tracing, Config::init_from_env, lifecycle::Manager, build AppState,
                        #   axum::serve, guard.wait()  (copy property-defs-rs/src/main.rs — NO pubsub subscriber)
    config.rs           # #[derive(Envconfig)] Config (see §5)
    lib.rs              # module wiring / re-exports
    app_context.rs      # AppState { pool, decryptor, cache, config } (Arc-shared, .with_state)
    router.rs           # /_readiness /_liveness / (index) + /api/v1/credentials/fetch; then serve_metrics::setup_metrics_routes(app)
    auth/
      mod.rs            # axum extractor AuthedCaller { team_id, caller } verifying the scoped JWT (§6)
      claims.rs         # Claims { aud, team_id, caller, exp }
    crypto/
      mod.rs
      decryptor.rs      # IntegrationDecryptor: ENCRYPTION_SALT_KEYS + PBKDF2 legacy → MultiFernet (§4)
      json_walk.rs      # decrypt_sensitive_config(&Value) -> Value  (per-leaf recursive walk)
    integrations/
      mod.rs
      model.rs          # IntegrationRow { id, team_id, kind, config: Value, sensitive_config: Value }
      repository.rs     # sqlx: fetch_by_ids(ids) -> Vec<IntegrationRow>  (read pool)
      service.rs        # get(team_id, ids): cache → repo → decrypt → team-scope filter
    cache/
      mod.rs            # moka::future::Cache<i64, Arc<DecryptedIntegration>>, ~30s TTL + capacity bound
    audit.rs            # structured audit event emit (§7)
    metrics_consts.rs   # &'static str metric names
  tests/
    crypto_parity.rs    # decrypt Django-produced ciphertext fixtures (§8)
    api.rs              # seeded-row integration test
```

**`Cargo.toml` deps** (`{ workspace = true }` unless noted): `axum`, `tokio`, `tower`, `tower-http`,
`tracing`, `tracing-subscriber`, `serde`, `serde_json`, `thiserror`, `anyhow`, `envconfig`, `sqlx`
(postgres), `fernet` (`0.2`), `base64`, `sha2`, `hex`, `moka` (feature `future`), `uuid`, `metrics`,
`jsonwebtoken = "8.3"` (per-crate pin), `pbkdf2 = "0.12"` + `hmac` (legacy key derivation).
Path deps: `common-database`, `common-metrics`, `common-serve-metrics` (`serve_metrics`),
`common-health`, `lifecycle`, `common-alloc`, `common-continuous-profiling`.
**No `common-redis`/`redis` in PR 1** (added in PR 2). Dev-deps: `reqwest`, `rstest`.

Reuse common infra as `property-defs-rs/src/main.rs` does: `common_alloc::used!()`,
`lifecycle::Manager::builder("integration-gateway")`, `readiness_handler()/liveness_handler()`,
DB pool via `common_database` / `PgPoolOptions`, `serve_metrics::setup_metrics_routes(app)`.

## 2. v1 read API surface

```
POST /api/v1/credentials/fetch
Authorization: Bearer <scoped JWT>              # team_id + caller (§6)
{ "integration_ids": [123, 456] }

200 OK
{ "integrations": {
    "123": { "id":123, "team_id":42, "kind":"slack",
             "config": {...plaintext...}, "sensitive_config": {...decrypted, pass-through...} },
    "456": null } }                             # not found OR wrong team → null (never leak existence)
```

- **Team-scope isolation (critical):** JWT carries one `team_id`; the service filters every fetched
  row with `row.team_id == claim.team_id`; mismatches return `null`, byte-identical to not-found.
  Mirrors the CDP's inline `integration.team_id === hogFunction.team_id` check
  (`hog-inputs.service.ts:151`) and batch-exports' `team_id=` filter.
- **Batch semantics:** id→object|null map (cap ~100 ids); a missing/forbidden id is `null`, not a
  batch failure (matches `LazyLoader.getMany`). Optional `GET /api/v1/credentials/{id}` wraps it.
- **Response shape matches the node `IntegrationType`** (`nodejs/src/cdp/types.ts`:
  `{id, team_id, kind, config, sensitive_config}`) so the CDP swap is a drop-in.
- **Pass-through:** v1 returns whatever access token is stored; no age check, no refresh.
- Auth extractor runs before the handler; missing/invalid token → 401. A single leaf's decrypt
  failure is not an error (pass-through); a row-level DB error → 500 for that batch.

## 3. No cache invalidation in v1

The `reload-integrations` pub/sub subscriber is intentionally omitted. Staleness is bounded solely by
the moka TTL (§4). Safe because Django refreshes tokens well before expiry, so a ≤30s-stale token is
still valid. Push invalidation can be added later if the TTL proves too coarse.

## 4. Crypto module + cache

**Crypto (highest-risk — byte-exact with Django).** `crypto/decryptor.rs` builds the ordered key list:
1. **Primary:** each `k` in `ENCRYPTION_SALT_KEYS` (comma-split, non-empty) → Fernet key `URL_SAFE_b64(k.as_bytes())`.
2. **Legacy (decrypt-only, appended last):** each `secret_key ∈ [SECRET_KEY, *SECRET_KEY_FALLBACKS]` × `salt_key ∈ SALT_KEY` → `URL_SAFE_b64(PBKDF2_HMAC_SHA256(password=secret_key, salt=salt_key, iters=100_000, dklen=32))`.
3. Wrap in `fernet::MultiFernet`.

`crypto/json_walk.rs::decrypt_sensitive_config(&Value) -> Value`: object → decrypt each value; array →
each element; string → `MultiFernet.decrypt`, on `InvalidToken` return the original string unchanged
(mirrors `ignore_decrypt_errors=True`); non-string/null → pass through. Reuse the *shape* of
`flag_payload_decryptor.rs` (`MultiFernet`, `from_keys`, Django-ciphertext fixture tests), not its key
derivation. Fail fast at boot if the primary key list is empty; log primary-vs-legacy key counts.

**Cache (`cache/mod.rs`).** `moka::future::Cache<i64, Arc<DecryptedIntegration>>` with
`time_to_live(~30s)` + a capacity bound (as in `feature-flags/.../cohort_cache_manager.rs`,
`common/cookieless/src/salt_cache.rs`). Use `try_get_with(id, loader)` for per-key request coalescing.
Cache the **decrypted** value in-process only — never to Redis — so secrets never leave the pod and hot
paths avoid re-decrypting. Do **not** use `common/cache::ReadThroughCache` (Redis-backed).

## 5. Config / secrets (`config.rs`, envconfig)

| Env var | Purpose | Fail-closed |
|---|---|---|
| `DATABASE_URL` (read pool) | sqlx to `posthog_integration` | required |
| `ENCRYPTION_SALT_KEYS` | primary Fernet keys (comma-sep) | **required; empty → refuse to start** |
| `SECRET_KEY`, `SECRET_KEY_FALLBACKS`, `SALT_KEY` | legacy PBKDF2 decrypt fallbacks | optional (legacy rows) |
| `INTEGRATION_GATEWAY_JWT_SECRET` (+ `_FALLBACKS`) | verify caller JWTs (§6) | **empty in prod → reject all requests** |
| `BIND_HOST`/`BIND_PORT`, pool sizes, `CACHE_TTL_SECONDS` (default 30), cache capacity, max batch size | tuning | defaulted |

No `PLUGINS_RELOAD_REDIS_URL` / Redis in v1. Follows `.agents/security.md`: dedicated per-purpose
secret, empty-in-prod fail-closed, comma-separated rotation (newest first), unique per environment.
Never log a secret or decrypted value.

## 6. Auth: scoped JWT (`auth/`)

Per `.agents/security.md` ("mint a scoped JWT; do NOT extend `INTERNAL_API_SECRET`"):

- **New secret `INTEGRATION_GATEWAY_JWT_SECRET`** (own env var on Django and the gateway; empty-in-prod
  fail-closed; `_FALLBACKS` for rotation). Do not reuse `JWT_SIGNING_KEY`/`INTERNAL_API_SECRET`.
- **Django mint** (new helper `posthog/integration_gateway_jwt.py`, don't overload `posthog/jwt.py`'s
  `_signing_key`): HS256-encode `{ "aud": "posthog:integration_gateway", "team_id": <int>,
  "caller": "<cdp|batch_exports|warehouse>", "exp": now+short_ttl }`. Short-lived, minted per-team by
  the calling service.
- **Rust verify** (`auth/mod.rs`): axum `FromRequestParts` extractor using `jsonwebtoken`
  (`decode::<Claims>`, `Validation::new(HS256)`, `set_audience(["posthog:integration_gateway"])`, try
  primary then fallback keys — same loop as `decode_jwt`). Reference the decode in
  `rust/capture-logs/src/auth.rs`, written for axum. Yields `AuthedCaller { team_id, caller }`.

## 7. Observability + auditing (the near-term win)

- **Per-caller audit log:** every fetch emits a structured `tracing` event (JSON in prod) with
  `caller`, `team_id`, requested `integration_ids`, which resolved vs `null`, `cache_hit`, request id
  — but **never** credential values. From `audit.rs`. (Durable audit sink is a later phase; v1 = logs.)
- **Prometheus** via `common-metrics` + `serve_metrics`:
  `integration_gateway_fetch_total{caller,kind,result=hit|miss|not_found|forbidden}`,
  `integration_gateway_decrypt_failures_total`, fetch-latency histogram, cache-size gauge. Follow the
  `Arc<str>` label rule in `rust/AGENTS.md`.

## 8. Testing / verification (PR 1)

- **Crypto parity unit tests (`tests/crypto_parity.rs`)** — the most important test. Commit ciphertext
  produced by Django's `EncryptedJSONField` and assert the Rust decryptor reproduces plaintext for:
  (a) a salt-keys leaf, (b) a legacy PBKDF2/SECRET_KEY leaf, (c) a nested object with mixed
  encrypted/plaintext leaves, (d) an undecryptable leaf passing through. Same pattern as
  `flag_payload_decryptor.rs`'s test module.
- **API integration test (`tests/api.rs`)** — seed a `posthog_integration` row locally, mint a token
  for its `team_id`, assert fetch returns decrypted config; a different `team_id` → `null`; missing/
  invalid token → 401.
- **Run locally:** `cd rust && cargo run -p integration-gateway` with `DATABASE_URL`,
  `ENCRYPTION_SALT_KEYS`, `INTEGRATION_GATEWAY_JWT_SECRET` against the dev stack; `cargo test -p integration-gateway`.
- **Verify CDP dual-read (§9):** run plugin-server with the gate on for a test team, trigger a hog
  function using an integration (e.g. Slack), confirm the outbound call carries the right token and the
  gateway audit log shows the fetch; toggle the gate off → confirm fallback still works.

## 9. Strangler cutover (PR 1)

Migrate consumers one at a time; each keeps its in-process path and dual-reads behind a gate, falling
back on any gateway error. **Order: CDP → batch-exports → warehouse-sources.**

**CDP (first):** `nodejs/src/cdp/services/managers/integration-manager.service.ts` is the only place
CDP loads integrations (used by `hog-inputs.service.ts`, `email.service.ts`). When the per-team gate is
on, `fetchIntegrations(ids)` calls `POST /api/v1/credentials/fetch` (minting a scoped JWT for the
`team_id`) instead of raw SQL + `decryptObject`; on any non-200/timeout it falls back to the existing
SQL path and increments a counter (optionally compare-and-log before flipping fully). The existing
`LazyLoader` cache stays; note CDP's own `reload-integrations` subscription still busts *its* cache
independently — unaffected by our dropping pub/sub inside the gateway.

**Batch-exports / warehouse (later):** replace the `Integration.objects.aget(id=, team_id=)` calls in
`products/batch_exports/backend/temporal/destinations/*.py` and the warehouse Stripe source with a
small Python client (httpx) that mints the scoped JWT and hits the gateway (same gate + fallback).

Old paths are deleted only after each consumer soaks on the gateway with zero fallbacks.

## 10. PR 2 (stacked): token refresh behind a feature flag

Adds refresh to the gateway. A per-team/env feature flag controls behavior on the fetch path:

- **Flag OFF → identical to v1**: return the stored access token as-is (Django/Celery still refreshes).
- **Flag ON →** before returning, check the token's validity/age (reuse the semantics of
  `OauthIntegration.access_token_expired`, ~half-life threshold, in `posthog/models/integration.py`).
  If expired/near-expiry, run the provider refresh flow, persist the new token, and return it.

Implementation notes:
- **JIT refresh must be single-flight**: reintroduce `common-redis` and use `set_nx_ex` as a per-
  integration lock (one refresher at a time).
- **This makes the gateway a writer** → the **encryption-parity problem** returns: the Rust writer must
  produce `sensitive_config` ciphertext Django can still read (per-leaf Fernet, primary key), *or*
  Django must stop reading that row's `sensitive_config` directly. Sequence carefully; consider making
  the gateway the sole refresher for a given `kind` before flipping the flag broadly. This is why
  refresh is deliberately deferred to its own PR rather than bundled into v1.
- On refresh failure, surface it (mirror Django's `errors = ERROR_TOKEN_REFRESH_FAILED`) so the UI can
  show "reconnect needed".

## 11. Later phases (not PR 1/2)

- **Proxy / on-behalf-of gateway** — service makes the outbound call so tokens never leave it. Reuse
  the SSRF + same-origin-redirect patterns in `products/mcp_store/backend/proxy.py` and
  `posthog.security.url_validation.is_url_allowed`. Needs per-provider endpoint allowlists.
- **OpenBao storage** behind the now-stable interface (move `sensitive_config` out of Postgres);
  per-integration definitions (rotation capability per provider); usage-based "claiming" (answer "is
  this integration still used?" from the audit trail rather than scanning consumers like
  `get_enabled_hog_functions_using_integration`).
- **Consolidate scoping:** fold `OrganizationIntegration` and `UserIntegration` behind the gateway.

## 12. Risks / open questions

1. **Encryption key-derivation parity (highest risk).** A subtle mismatch (standard vs URL-safe base64,
   PBKDF2 params, key ordering) silently fails in prod. Mitigation: the Django-ciphertext fixture tests
   (§8) are mandatory and cover both salt-keys and legacy paths before any consumer flips.
2. **Staleness bounded only by the 30s TTL.** No push invalidation by design. Safe because Django
   refreshes proactively (tokens valid well past 30s). If a workload ever needs sub-30s freshness, add
   invalidation back (channel + payload already exist: `reload_integrations_on_workers`).
3. **Gateway availability = credential availability.** Every migrated consumer depends on it. Mitigation:
   the strangler fallback keeps the in-process path per consumer until soak completes; stateless +
   horizontally scalable; in-proc cache absorbs load.
4. **Public vs private.** v1 is internal-only (cluster DNS, scoped-JWT gated). Keep private until proven
   otherwise. **Open question for infra/security.**
5. **Ownership** (workflows vs data-sources vs security) — unresolved. Not blocking PR 1; decide before
   PR 2 (refresh) since that changes the write/refresh owner. **Open question.**
6. **PR 2 write-back parity** (see §10) — decide writer-ownership sequence before starting PR 2.
7. **`caller` identity is self-asserted** in the JWT claim. Fine for auditing intent; per-service
   sub-keys later if stronger provenance is needed. **Open question, low priority.**

## Critical files

**New (v1):** everything under `rust/integration-gateway/` (§1); Django mint helper
`posthog/integration_gateway_jwt.py`; `INTEGRATION_GATEWAY_JWT_SECRET` (+ fallbacks) settings in
`posthog/settings/`.

**Reference / reuse:**
- Skeleton: `rust/property-defs-rs/src/main.rs`, `.../config.rs`; `rust/feature-flags/Cargo.toml`.
- Crypto to match: `posthog/helpers/encrypted_fields.py`; Rust shape: `rust/feature-flags/src/flags/flag_payload_decryptor.rs`; node parity: `nodejs/src/cdp/utils/encryption-utils.ts`.
- Model / refresh (PR 2): `posthog/models/integration.py` (`OauthIntegration.access_token_expired`, `refresh_access_token`, `ERROR_TOKEN_REFRESH_FAILED`); `posthog/tasks/integrations.py`.
- Auth: `posthog/jwt.py` (mint pattern); `rust/capture-logs/src/auth.rs` (decode call, adapt to axum).
- Cache pattern: `rust/feature-flags/src/cohorts/cohort_cache_manager.rs`, `rust/common/cookieless/src/salt_cache.rs`.
- Refresh lock (PR 2): `common/redis` `set_nx_ex`.
- Consumers to migrate: `nodejs/src/cdp/services/managers/integration-manager.service.ts` (+ `hog-inputs.service.ts`, `email.service.ts`); `products/batch_exports/backend/temporal/destinations/*.py`; `products/warehouse_sources/backend/temporal/data_imports/sources/stripe/source.py`.
- Deploy: `rust/Dockerfile`, `.github/rust-images.yml`, `.github/workflows/rust-docker-build.yml`.
- Later-phase proxy prototype: `products/mcp_store/backend/proxy.py`.
- Conventions: `.agents/security.md`, `rust/AGENTS.md`.
