# Rust feature flags service

The Rust feature flags service (`rust/feature-flags/`) handles all runtime feature flag evaluation. It serves the `/flags`, `/decide`, and `/flags/definitions` endpoints that SDKs call. Django remains the admin API for flag CRUD operations (`/api/projects/{id}/feature_flags/`).

## Infrastructure routing

Traffic routing happens at the Kubernetes infrastructure level using **Contour HTTPProxy** resources (Envoy-based). The Rust service never receives requests through Django -- they are routed directly by Contour.

```text
Client
  │
  ▼
AWS ALB
  │
  ▼
Contour / Envoy (path-based routing)
  │
  ├── /decide/*              ──▶ posthog-feature-flags:3001  (Rust)
  ├── /flags/?               ──▶ posthog-feature-flags:3001  (Rust)
  ├── /flags/definitions/?   ──▶ posthog-feature-flags:3001  (Rust)
  ├── /api/feature_flag/local_evaluation ──▶ posthog-local-evaluation:8000 (Django, dedicated deployment)
  ├── /api/*                 ──▶ posthog-web-django:8000     (Django, catch-all)
  └── /*                     ──▶ posthog-web-django:8000     (Django, final catch-all)
```

Key routing details:

- The `decide` and `feature-flags` proxy blocks are **included before** the `api` block in Contour, so they match first
- `/decide` adds an `X-Original-Endpoint: decide` header so the Rust service can adjust response format
- A **dedicated subdomain** (`us-d.i.posthog.com` / `eu-d.i.posthog.com`) routes only to `decide` + `feature-flags` with no Django fallback
- All flag routes have a **5-second timeout** and 2 retries on `reset`/`cancelled`
- Canary rollouts are supported via Argo Rollouts adjusting weights on the HTTPProxy resources

Routing config lives in the `charts` repo: `argocd/contour-ingress/values/values.prod-us.yaml` (and `prod-eu`, `dev` variants).

## Architecture overview

```text
┌─────────────────────────────────────────────────────────────────┐
│                          SDK Request                            │
│                    POST /flags or /decide                       │
└─────────────────────────────────────────────────────────────────┘
                               │
                        Contour / Envoy
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Rust Feature Flags Service                  │
│                     (Axum, port 3001)                           │
├─────────────────────────────────────────────────────────────────┤
│  Rate limiting ──▶ Auth ──▶ Decode ──▶ Evaluate ──▶ Response   │
└─────────────────────────────────────────────────────────────────┘
        │                │                    │
        ▼                ▼                    ▼
  ┌──────────┐   ┌──────────────┐   ┌──────────────────┐
  │  Redis   │   │  PostgreSQL  │   │   S3 (fallback)  │
  │ (cache)  │   │  (source of  │   │   via HyperCache │
  │          │   │   truth)     │   │                  │
  └──────────┘   └──────────────┘   └──────────────────┘
```

## Project structure

| Directory         | Purpose                                                                                        |
| ----------------- | ---------------------------------------------------------------------------------------------- |
| `src/api/`        | HTTP endpoint handlers, auth, rate limiting, request/response types                            |
| `src/handler/`    | Request processing pipeline: decoding, billing, evaluation, session recording, config assembly |
| `src/flags/`      | Core domain: flag models, matching engine, property filters, analytics, dependency graph       |
| `src/cohorts/`    | Cohort models, DB operations, in-memory cache (moka)                                           |
| `src/properties/` | Property models, operator matching, relative date parsing                                      |
| `src/team/`       | Team model and DB operations                                                                   |
| `src/database/`   | Connection management, persons DB routing                                                      |
| `src/metrics/`    | Prometheus metric constants and utilities                                                      |
| `src/utils/`      | User-agent parsing, graph algorithms                                                           |
| `src/site_apps/`  | Site apps support                                                                              |
| `tests/`          | Integration tests (flag matching, HTTP methods, rate limiting, experience continuity)          |

## HTTP endpoints

All routes are defined in `rust/feature-flags/src/router.rs`.

| Route                | Method | Handler                               | Purpose                                                                                   |
| -------------------- | ------ | ------------------------------------- | ----------------------------------------------------------------------------------------- |
| `/flags`             | POST   | `endpoint::flags`                     | Feature flag evaluation (primary endpoint)                                                |
| `/flags`             | GET    | `endpoint::flags`                     | Returns minimal response with empty flags                                                 |
| `/decide`            | POST   | `endpoint::flags`                     | Same handler as `/flags`, response format varies via `X-Original-Endpoint: decide` header |
| `/flags/definitions` | GET    | `flag_definitions::flags_definitions` | Flag definitions for local SDK evaluation (requires secret token or personal API key)     |
| `/`                  | GET    | `index`                               | Returns `"feature flags"` (basic health check)                                            |
| `/_readiness`        | GET    | `readiness`                           | Kubernetes readiness probe, tests all 4 DB pool connections                               |
| `/_liveness`         | GET    | `liveness`                            | Kubernetes liveness probe, heartbeat-based                                                |
| `/_startup`          | GET    | `startup`                             | Kubernetes startup probe, warms DB pools                                                  |
| `/metrics`           | GET    | Prometheus                            | Metrics scrape endpoint (when `ENABLE_METRICS=true`)                                      |

All flag routes accept trailing slashes.

### `/flags` request processing

The POST handler follows this pipeline:

1. **Rate limiting**: IP-based check (DDoS defense), then token-based check (per-project limits)
2. **Body decoding**: JSON, base64, or gzip-compressed bodies
3. **Authentication**: Extracts API token from body, query params, or headers
4. **Team lookup**: HyperCache (Redis -> S3) with PostgreSQL fallback
5. **Flag definitions fetch**: HyperCache (Redis -> S3) with PostgreSQL fallback
6. **Billing check**: Verifies the team's feature flag quota hasn't been exceeded
7. **Flag evaluation**: Core matching logic (see [flag-evaluation-engine.md](flag-evaluation-engine.md))
8. **Config assembly**: Session recording settings, error tracking, site apps
9. **Response formatting**: Version-specific serialization

### Response versioning

The response format depends on the `v` query parameter and the endpoint:

| Version   | Endpoint  | Response format                                                                              |
| --------- | --------- | -------------------------------------------------------------------------------------------- |
| (default) | `/flags`  | `LegacyFlagsResponse`: flat `feature_flags: { key: value }` map                              |
| `v=2`     | `/flags`  | `FlagsResponse`: detailed `flags: { key: FlagDetails }` map with reasons, metadata, payloads |
| `v=1`     | `/decide` | `DecideV1Response`: list of active flag keys                                                 |
| `v=2`     | `/decide` | `DecideV2Response`: flat `feature_flags: { key: value }` map                                 |

### `/flags/definitions` endpoint

Serves flag definitions for SDKs that evaluate flags locally (server-side SDKs). Requires authentication via:

- Team secret API token (`Authorization: Bearer phx_...`), or
- Personal API key with `feature_flag:read` scope

Returns flag definitions with cohort data from HyperCache. No PostgreSQL fallback -- if cache misses, the endpoint returns an error. Rate limited per team (default 600/minute).

## Request and response types

### `FlagRequest` (POST body)

```rust
pub struct FlagRequest {
    pub token: Option<String>,               // aliases: $token, api_key
    pub distinct_id: Option<String>,         // alias: $distinct_id
    pub geoip_disable: Option<bool>,
    pub disable_flags: Option<bool>,
    pub person_properties: Option<HashMap<String, Value>>,
    pub groups: Option<HashMap<String, Value>>,
    pub group_properties: Option<HashMap<String, HashMap<String, Value>>>,
    pub anon_distinct_id: Option<String>,    // alias: $anon_distinct_id
    pub device_id: Option<String>,           // alias: $device_id
    pub flag_keys: Option<Vec<String>>,      // evaluate only these flags
    pub timezone: Option<String>,
    pub evaluation_contexts: Option<Vec<String>>,
    pub evaluation_runtime: Option<EvaluationRuntime>,
}
```

### `FlagsResponse` (v2 response)

```rust
pub struct FlagsResponse {
    pub errors_while_computing_flags: bool,
    pub flags: HashMap<String, FlagDetails>,
    pub quota_limited: Option<Vec<String>>,
    pub request_id: Uuid,
    pub evaluated_at: i64,
    pub config: ConfigResponse,
}

pub struct FlagDetails {
    pub key: String,
    pub enabled: bool,
    pub variant: Option<String>,
    pub reason: FlagEvaluationReason,
    pub metadata: FlagDetailsMetadata,
}
```

## Rate limiting

Three independent rate limiters, all implemented in-process using the `governor` crate (token bucket algorithm):

| Limiter     | Scope         | Default config             | Purpose                            |
| ----------- | ------------- | -------------------------- | ---------------------------------- |
| IP-based    | Per source IP | 1000 burst / 50 per second | DDoS defense                       |
| Token-based | Per API token | 500 burst / 10 per second  | Per-project limits                 |
| Definitions | Per team ID   | 600 per minute             | `/flags/definitions` rate limiting |

All three support a **log-only** mode (`*_LOG_ONLY=true`) for safe rollout -- violations are logged and metered but requests are not blocked.

A background task runs every 60 seconds to clean up stale rate limiter entries.

## Server initialization

The `serve()` function in `rust/feature-flags/src/server.rs` orchestrates startup:

1. **Redis clients**: Shared `ReadWriteClient` (auto-routes reads to replica). Optional dedicated flags Redis with 3-mode migration: shared-only -> dual-write -> dedicated-only.
2. **Database pools**: `PostgresRouter` with 4 pools (persons reader/writer, non-persons reader/writer). See [database-interaction-patterns.md](database-interaction-patterns.md).
3. **GeoIP**: MaxMind database for IP geolocation.
4. **Cohort cache**: In-memory `CohortCacheManager` (moka, 256 MB default, 5-minute TTL).
5. **HyperCache readers**: 4 pre-initialized readers for flags, flags+cohorts, team metadata, and config.
6. **Billing limiters**: Redis-backed quota enforcement for feature flags and session replay.
7. **Cookieless manager**: Redis-backed cookieless identity resolution.
8. **Background tasks**: DB pool monitoring, cohort cache monitoring, rate limiter cleanup, health heartbeat.

## Configuration reference

All values come from environment variables via the `envconfig` crate. Defined in `rust/feature-flags/src/config.rs`.

### Server

| Variable          | Default          | Purpose                                           |
| ----------------- | ---------------- | ------------------------------------------------- |
| `ADDRESS`         | `127.0.0.1:3001` | Listen address                                    |
| `MAX_CONCURRENCY` | `1000`           | Max concurrent flag evaluation requests           |
| `DEBUG`           | `false`          | Pretty console logging vs JSON structured logging |
| `ENABLE_METRICS`  | `false`          | Expose `/metrics` endpoint                        |

### PostgreSQL

| Variable                                  | Default                                             | Purpose                               |
| ----------------------------------------- | --------------------------------------------------- | ------------------------------------- |
| `WRITE_DATABASE_URL`                      | `postgres://posthog:posthog@localhost:5432/posthog` | Main database primary                 |
| `READ_DATABASE_URL`                       | same                                                | Main database replica                 |
| `PERSONS_WRITE_DATABASE_URL`              | (empty, aliases to main)                            | Persons database primary              |
| `PERSONS_READ_DATABASE_URL`               | (empty, aliases to main)                            | Persons database replica              |
| `MAX_PG_CONNECTIONS`                      | `10`                                                | Max connections per pool              |
| `ACQUIRE_TIMEOUT_SECS`                    | `5`                                                 | Connection acquisition timeout        |
| `IDLE_TIMEOUT_SECS`                       | `300`                                               | Close idle connections after this     |
| `NON_PERSONS_READER_STATEMENT_TIMEOUT_MS` | `2000`                                              | Statement timeout for flag/team reads |
| `PERSONS_READER_STATEMENT_TIMEOUT_MS`     | `3000`                                              | Statement timeout for person lookups  |
| `WRITER_STATEMENT_TIMEOUT_MS`             | `3000`                                              | Statement timeout for writes          |

### Redis

| Variable                      | Default                     | Purpose                                  |
| ----------------------------- | --------------------------- | ---------------------------------------- |
| `REDIS_URL`                   | `redis://localhost:6379/`   | Shared Redis primary                     |
| `REDIS_READER_URL`            | (falls back to `REDIS_URL`) | Shared Redis replica                     |
| `FLAGS_REDIS_URL`             | (empty)                     | Dedicated flags Redis primary            |
| `FLAGS_REDIS_READER_URL`      | (empty)                     | Dedicated flags Redis replica            |
| `FLAGS_REDIS_ENABLED`         | `false`                     | Read from dedicated flags Redis          |
| `REDIS_RESPONSE_TIMEOUT_MS`   | `100`                       | Redis response timeout (capped at 30s)   |
| `REDIS_CONNECTION_TIMEOUT_MS` | `5000`                      | Redis connection timeout (capped at 60s) |

### S3 / HyperCache

| Variable                  | Default     | Purpose                          |
| ------------------------- | ----------- | -------------------------------- |
| `OBJECT_STORAGE_BUCKET`   | `posthog`   | S3 bucket name                   |
| `OBJECT_STORAGE_REGION`   | `us-east-1` | AWS region                       |
| `OBJECT_STORAGE_ENDPOINT` | (empty)     | Custom S3 endpoint for local dev |

### Rate limiting

| Variable                                   | Default | Purpose                               |
| ------------------------------------------ | ------- | ------------------------------------- |
| `FLAGS_RATE_LIMIT_ENABLED`                 | `false` | Enable token-based rate limiting      |
| `FLAGS_BUCKET_CAPACITY`                    | `500`   | Token bucket capacity                 |
| `FLAGS_BUCKET_REPLENISH_RATE`              | `10.0`  | Tokens per second                     |
| `FLAGS_IP_RATE_LIMIT_ENABLED`              | `false` | Enable IP-based rate limiting         |
| `FLAGS_IP_BURST_SIZE`                      | `1000`  | IP bucket capacity                    |
| `FLAGS_IP_REPLENISH_RATE`                  | `50.0`  | Tokens per second                     |
| `FLAGS_RATE_LIMIT_LOG_ONLY`                | `true`  | Log violations without blocking       |
| `FLAG_DEFINITIONS_DEFAULT_RATE_PER_MINUTE` | `600`   | Default rate for `/flags/definitions` |
| `FLAG_DEFINITIONS_RATE_LIMITS`             | (empty) | Per-team overrides as JSON            |

### Caching

| Variable                         | Default              | Purpose                   |
| -------------------------------- | -------------------- | ------------------------- |
| `COHORT_CACHE_CAPACITY_BYTES`    | `268435456` (256 MB) | Moka cache memory limit   |
| `CACHE_TTL_SECONDS`              | `300`                | Cohort cache TTL          |
| `BILLING_LIMITER_CACHE_TTL_SECS` | `5`                  | Billing limiter cache TTL |

### Observability

| Variable                      | Default                 | Purpose                                                                               |
| ----------------------------- | ----------------------- | ------------------------------------------------------------------------------------- |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | (disabled)              | OpenTelemetry collector endpoint                                                      |
| `OTEL_TRACES_SAMPLER_ARG`     | `0.001`                 | Trace sampling rate (0.1%)                                                            |
| `OTEL_SERVICE_NAME`           | `posthog-feature-flags` | Service name in traces                                                                |
| `TEAM_IDS_TO_TRACK`           | `all`                   | Teams to emit detailed metrics for (`all`, `none`, comma-separated, or range `1:100`) |

### Other

| Variable                                 | Default                    | Purpose                                |
| ---------------------------------------- | -------------------------- | -------------------------------------- |
| `MAXMIND_DB_PATH`                        | `share/GeoLite2-City.mmdb` | GeoIP database path                    |
| `OPTIMIZE_EXPERIENCE_CONTINUITY_LOOKUPS` | `true`                     | Skip DB lookups for 100%-rollout flags |
| `FLAGS_SESSION_REPLAY_QUOTA_CHECK`       | `false`                    | Check session replay quota             |

## Key dependencies

| Crate                                   | Purpose                                                           |
| --------------------------------------- | ----------------------------------------------------------------- |
| `axum`                                  | HTTP framework                                                    |
| `sqlx`                                  | Async PostgreSQL driver                                           |
| `tokio`                                 | Async runtime                                                     |
| `serde` / `serde_json` / `serde-pickle` | Serialization (pickle for HyperCache interop with Python)         |
| `governor`                              | Token-bucket rate limiting                                        |
| `moka`                                  | Concurrent in-memory cache (cohorts)                              |
| `sha1` / `sha2`                         | Hashing for flag rollout and variant selection                    |
| `petgraph`                              | Dependency graph (flag-on-flag dependencies, cohort dependencies) |
| `fancy-regex`                           | Regex property matching with backtrack limits                     |
| `semver`                                | Semantic versioning operator support                              |
| `rayon`                                 | Parallel flag evaluation within dependency stages                 |
| `tokio-retry`                           | Exponential backoff for DB operations                             |

## Middleware

Applied in order via Axum layers (defined in `router.rs`):

1. **ConcurrencyLimitLayer**: Caps concurrent flag evaluation requests (default 1000)
2. **TraceLayer**: HTTP request tracing with spans
3. **CorsLayer**: Permissive CORS (mirrors request origin, allows credentials)
4. **track_metrics**: Prometheus HTTP request metrics

## Related files

| File                                             | Purpose                                           |
| ------------------------------------------------ | ------------------------------------------------- |
| `rust/feature-flags/src/main.rs`                 | Binary entry point, tracing setup                 |
| `rust/feature-flags/src/server.rs`               | Service initialization, resource creation         |
| `rust/feature-flags/src/router.rs`               | Axum router, routes, shared state                 |
| `rust/feature-flags/src/config.rs`               | Environment variable configuration                |
| `rust/feature-flags/src/api/endpoint.rs`         | `/flags` and `/decide` handler                    |
| `rust/feature-flags/src/api/flag_definitions.rs` | `/flags/definitions` handler                      |
| `rust/feature-flags/src/api/auth.rs`             | Authentication (secret tokens, personal API keys) |
| `rust/feature-flags/src/api/types.rs`            | Request/response types                            |
| `rust/feature-flags/src/handler/flags.rs`        | Core request processing pipeline                  |

## See also

- [Flag evaluation engine](flag-evaluation-engine.md) - How flags are matched and evaluated
- [Database interaction patterns](database-interaction-patterns.md) - PostgreSQL connection pooling and query routing
- [HyperCache system](hypercache-system.md) - Multi-tier caching with Redis, S3, and PostgreSQL
- [Experience continuity](experience-continuity.md) - Hash key overrides for consistent flag values across identity changes
- [Django API endpoints](django-api-endpoints.md) - CRUD and management endpoints served by Django
