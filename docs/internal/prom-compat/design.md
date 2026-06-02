# prom-compat — PromQL read plane for PostHog metrics

Status: draft
Author: metrics team
Date: 2026-06-02

## 1. Context

PostHog ingests OpenTelemetry metrics into a ClickHouse table (`metrics1`) on the logs cluster.
Today users query that data through a bespoke product UI (`products/metrics/`) backed by a custom Python query runner (`metric_query_runner.py`) that supports a fixed set of aggregations (`sum`, `avg`, `count`, `p95`) over a single metric name with no group-by and no label filters.

We want PostHog metrics to be a credible drop-in target for the Prometheus ecosystem.
Concretely:

- A user installs the **Prometheus data source** in Grafana, points it at PostHog, and existing dashboards work.
- A team's existing PromQL queries and alerting rules continue to evaluate against PostHog.
- Tools that speak the Prom HTTP API (`promtool`, `prometheus-api-client`, every k8s dashboard plugin, every PromQL-querying CLI) work without a PostHog-specific shim.

This document specifies **Track A** — the PromQL read plane.
The remote_write ingest plane is Track B and lives outside this doc.

### 1.1 Non-goals (Track A)

- **Replacing the native metrics UI.**
  The native HogQL-based query path remains the primary user-facing surface.
  PromQL is an ecosystem adapter sitting next to it on the same `metrics1` table.
  See §3 architecture overview.
- **Prometheus rules engine.**
  Recording and alerting rules are out of scope; PostHog already has its own alerting product.
- **Federation / `/metrics` exposition.**
  We are a sink, not a source. No `/federate` endpoint.
- **PromQL inside the PostHog UI.**
  Users do not type PromQL into our app; they use the metrics scene.
  PromQL is for tools.

### 1.2 Success criteria

1. A Grafana Prometheus data source pointed at PostHog renders an out-of-the-box "node-exporter" dashboard (counters, gauges, classic histograms) using PostHog-ingested OTel data without query errors.
2. `histogram_quantile(0.95, ...)` returns numerically equivalent results to our native percentile overlay (within rounding).
3. `rate(some_counter[5m])` is correct for both cumulative and delta OTel sums.
4. Multi-tenant: one deployment serves all teams, scoped per request via a personal API key.
5. p95 of `/api/v1/query_range` over a 1-hour window for a single metric stays under 1.5 s at our typical row volume on the logs cluster.

## 2. Why this is the right move

### 2.1 PromQL is the standard contract for time-series tooling

Every observability tool in the open-source ecosystem reads or writes Prometheus protocols.
Grafana, alertmanager, vmagent, Thanos, Mimir, Cortex, every "deploy a dashboard on day one" template, every k8s plugin.
Owning a compatible read plane lets us claim "drop-in replacement for Prometheus storage" without forking each tool.

This is a strategic differentiator: PostHog already has a unique exemplar story (metrics → trace correlation via the same `trace_id` column) that no Grafana stack ships natively.
That value is only legible to users if their existing tools can talk to us.

### 2.2 The translation work is small and well-scoped

The first investigation pass confirmed that our `metrics1` schema is already **byte-identical** to Snuffle's `posthog` storage layout (column-by-column, including the projection, sort key, partition key, and `cityHash64(resource_attributes)` series fingerprint).
The author models on PostHog conventions; this isn't coincidence.
No schema migration is required to expose `metrics1` over PromQL.

### 2.3 Doing it ourselves is cheaper than re-implementing PromQL

Building a PromQL engine from `promql-parser` (the alternative path raised in the Slack thread) means re-implementing ~70 functions, range and instant evaluation semantics, vector matching, subqueries, the `@`/`offset` modifiers, native histogram math.
Embedding the upstream Prometheus engine (the pattern Snuffle demonstrates) gets all of that for free and tracks the spec for us forever.
The engine is a library inside `github.com/prometheus/prometheus`; we own only the `storage.Querier` adapter and the HTTP routing.

### 2.4 Precedent: PostHog already has a Go service

`livestream/` is a production Go service in this repo with its own CI workflow (`.github/workflows/ci-livestream.yml`).
Go is an acceptable language for new services; we are not introducing a new runtime to the stack.
The Prometheus engine ships only as a Go library, so Go is the only sensible choice for this service.

## 3. Architecture overview

```text
                                  ┌────────────────────────────────────────┐
                                  │  Native PostHog UI (products/metrics)  │
                                  │  HogQL → metric_query_runner.py        │
                                  └───────────────┬────────────────────────┘
                                                  │
                                                  │ reads
                                                  ▼
  Grafana / promtool / ────► prom-compat ───►  metrics1 (ClickHouse, logs cluster)
  alertmanager / Mimir       (Go service)       ▲
                                                  │ writes
                                                  │
                              Rust capture-logs ──┘   (OTel ingest path, unchanged)
```

Two read planes over one storage.
The native plane stays the primary product UX.
`prom-compat` is purely an ecosystem adapter.

Service identity:

- **Name:** `prom-compat`
- **Location:** `services/prom-compat/`
  Rationale: `docs/internal/monorepo-layout.md` defines `services/` as "independent deployments with their own DNS name, owning domain logic that isn't product-specific and isn't shared infrastructure."
  This matches exactly.
  `livestream/` lives at the root for historical reasons; new services follow the documented layout.
- **Language:** Go (currently latest stable; pin in `go.mod`)
- **Public URL:** `https://prometheus.posthog.com` (cloud) — see §5 for the URL contract.

## 4. Service shape

### 4.1 Source tree

```text
services/prom-compat/
├── cmd/
│   └── prom-compat/
│       └── main.go              # entry point — ~30 lines
├── internal/
│   ├── api/                     # HTTP handlers
│   │   ├── server.go            # router, middleware wiring
│   │   ├── auth.go              # PostHog API key validation
│   │   ├── query.go             # /api/v1/query, /query_range
│   │   ├── labels.go            # /labels, /label/{name}/values, /series
│   │   ├── metadata.go          # /metadata
│   │   ├── exemplars.go         # /query_exemplars
│   │   └── health.go            # /_readiness, /_liveness, /metrics
│   ├── storage/                 # ClickHouse storage adapter
│   │   ├── queryable.go         # implements prometheus/storage.Queryable
│   │   ├── querier.go           # implements storage.Querier
│   │   ├── seriesset.go         # storage.SeriesSet for metrics1 rows
│   │   ├── histograms.go        # synthesize _bucket{le=...} series (Blocker 1)
│   │   ├── temporality.go       # delta → cumulative normalization (Blocker 2)
│   │   ├── pushdown.go          # SQL generation, projection awareness (Blocker 4)
│   │   ├── sql.go               # SQL builders shared across files
│   │   └── client.go            # clickhouse-go/v2 wrapper, pooling
│   ├── auth/                    # token cache + Postgres fallback (mirrors rust/feature-flags)
│   │   ├── cache.go             # Redis read-through
│   │   └── pg.go                # Postgres fallback query
│   ├── tenant/                  # per-request team context
│   │   └── context.go
│   ├── config/
│   │   └── config.go            # env var → typed Config
│   └── engine/
│       └── engine.go            # promql.Engine construction
├── go.mod
├── go.sum
├── Dockerfile                   # multi-stage, distroless runtime
├── README.md
└── tests/
    ├── integration_test.go      # e2e against real ClickHouse + Postgres + Redis
    └── fixtures/                # canonical OTel metrics for testing
```

Estimated total ~3-4k LOC across handlers, storage, and auth, plus tests.

### 4.2 Dependencies

| Module                                   | Version  | Purpose                                                    |
| ---------------------------------------- | -------- | ---------------------------------------------------------- |
| `github.com/prometheus/prometheus`       | v0.311.3 | `promql` engine, `storage` interfaces, `prompb`, `labels`  |
| `github.com/prometheus/client_golang`    | v1.23.x  | Self-metrics exposition                                    |
| `github.com/ClickHouse/clickhouse-go/v2` | v2.46.x  | Native CH protocol client                                  |
| `github.com/redis/go-redis/v9`           | latest   | Auth cache (mirrors `rust/feature-flags`)                  |
| `github.com/jackc/pgx/v5`                | latest   | Postgres fallback for auth                                 |
| `github.com/cespare/xxhash/v2`           | v2.x     | Series-ID hashing (matches Snuffle's identity scheme)      |
| `github.com/go-chi/chi/v5`               | v5.x     | HTTP router with middleware ergonomics                     |
| `go.opentelemetry.io/otel/*`             | latest   | Distributed tracing emission (matches `rust/capture-logs`) |

No new operational dependency beyond the Prom engine itself.
Redis and Postgres clients are required because we mirror the `rust/feature-flags` auth pattern.

Decision point: chi vs stdlib mux.
Snuffle uses stdlib; capture-logs uses Axum (Rust).
Chi is the most idiomatic Go choice and gives us middleware composition for the auth → tenant → query chain without writing it ourselves.
Worth the 500 KB dep.

### 4.3 Why fork vs build-from-scratch vs vendor

Recommendation: **fork the structural template, vendor the engine.**

| Component                                   | Source                                                                     | Why                                                                                                                                                                  |
| ------------------------------------------- | -------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `internal/storage/*` (Querier adapter)      | New — write from scratch, structurally modeled on Snuffle                  | The adapter is ~400 LOC; we'd write it line-for-line anyway. Owning the code from day one means no upstream-drift surprises, and we get to fix Blockers 1-4 cleanly. |
| `cmd/prom-compat/main.go`, `internal/api/*` | New                                                                        | Snuffle's HTTP layer is stdlib mux + hand-rolled routing; we want our own auth/tenant middleware integrated, which is easier from scratch with chi.                  |
| `internal/auth/*`                           | New, mirrors `rust/feature-flags/src/api/auth.rs`                          | PostHog-specific. Snuffle has no auth.                                                                                                                               |
| `internal/engine/engine.go`                 | Calls `promql.NewEngine` from the upstream `prometheus/prometheus` library | The engine is the load-bearing piece. We vendor (via `go.mod`), don't fork.                                                                                          |

Treat Snuffle as a **structural reference**, not a dependency.
Read its `storage.go`, `posthog_storage.go`, `clickhouse.go`, and `api.go` as the worked example.
Vendor the upstream Prometheus engine that Snuffle vendors.
Write our own adapter from scratch so we own the four blocker fixes and the auth integration cleanly.

This avoids the operational risk of tracking a single-author, 4-week-old, no-prod-users repo as an upstream.

## 5. URL contract & auth

### 5.1 Public URL shape

`https://prometheus.posthog.com/p/{project_id}/api/v1/{endpoint}`

Examples:

- `GET /p/42/api/v1/query?query=...&time=...`
- `GET /p/42/api/v1/query_range?query=...&start=...&end=...&step=...`
- `GET /p/42/api/v1/label/__name__/values`
- `GET /p/42/api/v1/series?match[]=...`

Rationale:

- Grafana's Prometheus data source takes a single URL prefix.
  The user enters `https://prometheus.posthog.com/p/42` in the URL field, and Grafana appends `/api/v1/query` automatically.
  Clean separation between PostHog identity (`/p/{project_id}/`) and Prometheus protocol (`/api/v1/...`).
- Mirrors the PostHog convention of project-scoped URLs (`/api/projects/:project_id/...` is the Django convention) without doubling `/api/`.
- Matches Snuffle's `/t/{team_id}/` shape, but uses `project_id` to align with PostHog's external identifier (we resolve `project_id → team_id` server-side; see §5.3).

Self-hosted users override `prometheus.posthog.com` with their own DNS via service config.

### 5.2 Auth

- **Header:** `Authorization: Bearer <phx_... personal API key>` — standard Grafana data source auth field.
- **Validation precedent:** the `rust/feature-flags` service.
  Hash the token (SHA-256), read-through Redis (`posthog:auth_token:{hash}`), fall back to a Postgres query against `posthog_personalapikey` (`posthog/auth.py` lines 179-328 for the Python equivalent).
- **Scope:** the personal API key must carry the `metrics:read` scope.
  This scope already exists in `posthog/scopes.py` (line 72) but is hidden from OAuth consent screens (`OAUTH_HIDDEN_SCOPE_OBJECTS`).
  We promote it to a user-grantable scope in a small Django PR before launch.
- **Team check:** the resolved `team_id` for `{project_id}` must be present in the key's `scoped_teams` array (or `scoped_teams` must be empty, meaning "all teams").
  Mirrors `APIScopePermission` in `posthog/permissions.py` lines 465-600.
- **Failure mode:** 401 with `WWW-Authenticate: Bearer realm="prometheus.posthog.com"`, body `{"status":"error","errorType":"unauthorized","error":"invalid API key"}` (Prom API error envelope).

### 5.3 Project → team resolution

The URL carries `project_id` (visible to users in PostHog).
Most database state is keyed by `team_id`.
The mapping `project_id → team_id` is resolved by reading `posthog_team.project_id` once per request, then cached in Redis for 60s.

Cache key: `posthog:project_team:{project_id}` → `team_id` (int).

Stale-on-error: if Postgres is unavailable but we have a cached entry, serve it.
Hard fail if both Redis and Postgres are unreachable.

### 5.4 CORS

Same as `rust/capture-logs`: `CorsLayer` with `AllowOrigin::mirror_request()` and `allow_credentials(true)`.
Equivalent Go config using `github.com/rs/cors`:

```go
cors.New(cors.Options{
    AllowOriginFunc: func(_ string) bool { return true },
    AllowedMethods:  []string{"GET", "POST", "OPTIONS"},
    AllowedHeaders:  []string{"Authorization", "Content-Type"},
    AllowCredentials: true,
})
```

Grafana runs in the browser; mirror-request CORS is the only sane choice.

### 5.5 Rate limiting

Per-key QPS limiter, Redis-backed, mirroring `rust/feature-flags`'s `flags_token_rate_limit_overrides` pattern.
Default: 10 QPS per key, 100 burst.
Tunable per-team via the same Redis override pattern that capture uses.

Per-query cost limit is enforced at the ClickHouse layer — see §6.

## 6. ClickHouse access

### 6.1 Cluster

`metrics1` lives on the **logs cluster**, not the main analytics cluster.
Cluster name comes from `CLICKHOUSE_LOGS_CLUSTER` (default `posthog_single_shard`); database from `CLICKHOUSE_LOGS_CLUSTER_DATABASE`.
Single-shard, replicated.

Verified at `posthog/clickhouse/metrics/metrics1.py`.
The native query runner explicitly passes `workload=Workload.LOGS` (`products/metrics/backend/metric_query_runner.py` line 128); prom-compat must use the same cluster credentials.

### 6.2 Connection

- Native protocol, port 9000 (`clickhouse-go/v2` default).
- Connection string: `CLICKHOUSE_LOGS_CLUSTER_HOST:9000`, user from `CLICKHOUSE_LOGS_CLUSTER_USER` or a new `CLICKHOUSE_LOGS_CLUSTER_READONLY_USER` (preferred — request a dedicated read-only user in infra to limit blast radius).
- Pool: `MaxOpenConns=32`, `MaxIdleConns=8`, `MaxLifetime=1h` (matches Snuffle defaults; conservative for the logs cluster which is single-shard and shared with logs+tracing reads).
- Per-service-instance concurrent query ceiling: **8** (semaphore at the storage layer).
  The logs cluster has 1000 max connections globally; an unbounded service would starve adjacent workloads.

### 6.3 Server-side query limits

Applied as ClickHouse settings on every request issued by prom-compat:

| Setting              | Value   | Rationale                                                                                               |
| -------------------- | ------- | ------------------------------------------------------------------------------------------------------- |
| `max_execution_time` | `30s`   | Matches Prom's default query timeout                                                                    |
| `max_memory_usage`   | `10 GB` | Conservative for shared cluster                                                                         |
| `max_bytes_to_read`  | `50 GB` | Mirrors `HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES` (`posthog/hogql/database/schema/metrics.py`) |
| `max_threads`        | `8`     | Half the analytics-cluster default; we share the logs cluster                                           |
| `readonly`           | `2`     | Hard guarantee against accidental writes                                                                |

Returned to client as Prom-style errors when exceeded:

```json
{ "status": "error", "errorType": "timeout", "error": "query exceeded max_execution_time" }
```

### 6.4 Projection exploitation

`metrics1` ships with `projection_aggregate_counts` pre-aggregating `count`, `sum`, `min`, `max` by `(team_id, time_bucket, toStartOfMinute(timestamp), service_name, metric_name, metric_type, resource_fingerprint)`.

Snuffle's PostHog adapter does **not** exploit this — it pulls raw samples and aggregates client-side.
For Blocker 4 (pushdown) we explicitly route the common shapes (`sum`, `count`, `rate` over 1-minute or longer windows) through SQL aggregations that match the projection key.
ClickHouse will automatically read from the projection when the WHERE/GROUP BY match.

See §7.4 for the engine integration.

## 7. The four blockers — concrete plan

Each blocker is a discrete pull request stack inside the prom-compat service.

### 7.1 Blocker 1: histogram bucket synthesis

**Problem.** Our `metrics1` table stores OTel histograms as `histogram_bounds Array(Float64)` + `histogram_counts Array(UInt64)`.
The Prometheus engine expects classic histograms as a _family of time series_ — `metric_bucket{le="0.05"}`, `metric_bucket{le="0.1"}`, ... `metric_count`, `metric_sum`.
Without the family, `histogram_quantile(0.95, rate(metric_bucket[5m]))` returns nothing.

**Solution.** Synthesize the bucket family at the storage adapter.

For a row in `metrics1` with `metric_type IN ('histogram', 'exponential_histogram')` and arrays `(bounds, counts)`, the Querier emits N+2 virtual series:

- `{__name__="<metric>_bucket", le="<bound_i>", ...labels}` with value = cumulative sum of counts up to bucket i
- `{__name__="<metric>_count", ...labels}` with value = `sum(counts)`
- `{__name__="<metric>_sum", ...labels}` with value = `value` column (which is the OTel sum field)

Series-ID hashing folds `le` into the identity so consecutive samples for the same bucket form a coherent time series.

**Where the SQL changes.**
The label-name index needs to expose synthetic names: when a `LabelValues("__name__")` call returns `http_server_duration`, it must _also_ return `http_server_duration_bucket`, `_count`, `_sum`.
This is a deterministic transform on the metric_name list and is computed in the adapter, not in ClickHouse.

**Native histogram path.**
Optional v1.1: if a row has `metric_type='exponential_histogram'`, we could synthesize a native Prom histogram (`prompb.Histogram` proto with sparse buckets) instead of the explicit form.
Better fidelity, requires Prom engine native-histogram support (already present in v0.311.3).
Defer to a follow-up because explicit buckets give us correct quantiles today.

**Estimated effort.** ~1 week (storage adapter changes + Prom engine plumbing + tests).

### 7.2 Blocker 2: delta → cumulative normalization

**Problem.** Prom's `rate()` and `increase()` assume cumulative monotonic counters.
Our `metrics1` rows tag temporality via `aggregation_temporality` ∈ `{'delta', 'cumulative', 'unspecified'}`.
Delta sums passed raw to the engine produce wrong answers — `rate(delta_metric[5m])` divides the already-rate-like delta by another 5m.

**Solution.** Wrap delta SeriesSets with a `cumulativeAdapter` that maintains a running sum per series ID at read time.

Pseudocode in the Querier:

```go
func (q *querier) wrapTemporality(s storage.Series, temp string) storage.Series {
    if temp != "delta" { return s }
    return &cumulativeAdapter{inner: s, runningSum: 0}
}
```

The running sum is per-(series-id, query) and resets between independent `Select()` calls — Prom queries always carry a `mint`/`maxt`, and we accumulate from `mint` forward.

**Caveat.** Cumulative reconstruction from delta is only correct if no points are missing.
We document this as a known approximation.
The alternative — normalizing at ingest — is a much bigger change and locks us into one temporality forever.

**Estimated effort.** ~2 days.

### 7.3 Blocker 3: per-request team scoping

**Problem.** Snuffle reads `team_id` from process-level config (`SNUFFLE_DEFAULT_TEAM_ID`).
One process per team is not viable at PostHog scale.

**Solution.** Plumb team through the chi middleware chain:

```text
incoming request
    → auth middleware: validate Bearer token, attach PersonalAPIKey to ctx
    → tenant middleware: read /p/{project_id}/, resolve to team_id via Redis-cached lookup,
                         verify project's team_id ∈ key.scoped_teams,
                         inject team_id into ctx
    → handler: pass team_id into Querier construction
    → storage adapter: emit team_id = ? in every WHERE clause
```

The Querier is constructed per-request, not per-process.
The `cfg.TeamID` field becomes a request-scoped value.

**Where it differs from Snuffle.** Snuffle's `clickhouse.go::teamFilter()` returns a hardcoded `"team_id = <cfg.TeamID>"`.
We replace it with a parameterized `"team_id = $N"` and bind from request context.
This is the single biggest functional divergence from Snuffle's design.

**Estimated effort.** ~3 days (middleware + storage adapter parameter threading + tests).

### 7.4 Blocker 4: aggregation pushdown & projection use

**Problem.** Snuffle pulls raw samples and aggregates in-process.
For a query like `sum by (service_name) (rate(http_server_duration_count[5m]))` over a 1-hour window with 50 services and 1-second samples, that's ~180k rows out of ClickHouse.
The `projection_aggregate_counts` projection on `metrics1` already has the answer pre-aggregated by minute — we just don't ask for it.

**Solution.** Two levels of pushdown:

**Level 1 (cheap, day-one).** When the Prom engine asks for samples with a `SelectHints.Func` ∈ `{"rate", "increase", "sum", "count", "avg", "min", "max"}` and a `Step >= 60s`, the storage adapter generates SQL with `GROUP BY toStartOfMinute(timestamp), team_id, metric_name, service_name, resource_fingerprint`.
ClickHouse routes this through the projection automatically.

```sql
SELECT
    toStartOfMinute(timestamp) AS ts,
    metric_name, service_name, resource_fingerprint,
    sum(value) AS s, count() AS c, min(value) AS mn, max(value) AS mx
FROM metrics1
WHERE team_id = ? AND metric_name = ?
  AND timestamp >= ? AND timestamp < ?
GROUP BY ts, metric_name, service_name, resource_fingerprint
ORDER BY ts
```

The engine then computes `rate` over these pre-aggregated samples.
Numerical loss is negligible because Prom's rate is already a windowed slope.

**Level 2 (follow-up).** Quantile pushdown.
For `quantile_over_time` or histogram_quantile inputs, ClickHouse's `quantileExactWeighted(0.95)(value, count)` natively operates on our `histogram_counts` array.
Implementing this requires teaching the Querier to recognize the call site, which is done via `SelectHints.By` + `Func`.
Defer to v1.1 because the explicit-bucket synthesis from Blocker 1 already handles most quantile queries correctly.

**Estimated effort.** ~1-2 weeks (Level 1 only; Level 2 is a separate work item).

## 8. Self-observability

Mirror the Rust services' pattern (`common-metrics`, `common-health`, `common-continuous-profiling`):

- **Logs.** Structured JSON via `log/slog`, with `request_id`, `team_id`, `query_hash`, `duration_ms` on every query log.
- **Metrics.** Self-exposed at `/metrics` via `prometheus/client_golang`.
  Critical metrics:
  - `prom_compat_http_requests_total{endpoint,status,team_id}`
  - `prom_compat_query_duration_seconds{endpoint}` (histogram)
  - `prom_compat_clickhouse_query_duration_seconds`
  - `prom_compat_clickhouse_rows_read_total`
  - `prom_compat_auth_cache_hits_total`, `_misses_total`
  - `prom_compat_engine_eval_duration_seconds`
- **Traces.** OpenTelemetry SDK via OTLP gRPC, exporting to PostHog's tracing pipeline.
  Each PromQL evaluation emits a parent span; ClickHouse calls are child spans with the SQL hash as an attribute.
- **Profiling.** Pyroscope continuous profiling, gated by `CONTINUOUS_PROFILING_ENABLED`.
- **Health.** `/_readiness` (checks CH + Redis + Postgres are reachable), `/_liveness` (always 200 unless shutting down).

These metrics get scraped by the existing observability stack — no new dashboards required for ops.
We add a prom-compat-specific Grafana dashboard for query performance triage as part of the launch checklist.

## 9. Deployment & CI

### 9.1 Build

`services/prom-compat/Dockerfile`, multi-stage:

```dockerfile
FROM golang:<latest-stable> AS builder
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /out/prom-compat ./cmd/prom-compat

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=builder /out/prom-compat /prom-compat
USER nonroot
EXPOSE 9090
ENTRYPOINT ["/prom-compat"]
```

Distroless static base — smaller image, smaller attack surface.
Single static binary, no runtime CGO.

### 9.2 CI workflows

Mirror the Rust precedent (`.github/workflows/_rust-build-images.yml` + `.github/rust-images.yml`):

1. **`.github/workflows/ci-prom-compat.yml`** — runs on `services/prom-compat/**` path filter.
   - `go vet`, `go test -race -coverprofile=cover.out ./...`
   - Integration test job: spins up ClickHouse + Postgres + Redis via Docker, seeds fixtures, runs `tests/integration_test.go` which exercises the public API surface end-to-end.
   - golangci-lint with the project's standard config.

2. **`.github/workflows/cd-prom-compat-image.yml`** — on master:
   - Depot build to AWS ECR (multi-arch: amd64 + arm64).
   - On success, `repository-dispatch` to `PostHog/charts` with `event-type=commit_state_update`, `release=prom-compat`, `values_key=image`, image digest.

This is identical to how `services/mcp/` and `rust/capture-logs/` ship today.
No new infrastructure pattern.

### 9.3 Dev environment

Add `prom-compat` to the `flox`-managed dev stack as an optional service:

- `hogli start --with prom-compat` brings up the binary alongside Django and capture-logs.
- Listens on `localhost:9090`.
- Connects to the local ClickHouse instance at `localhost:9000`, database `default`, user `default`, no password.
- Auth in dev: a bypass mode (`PROM_COMPAT_DEV_AUTH_BYPASS=1`) that treats every request as `team_id=1` and skips key validation.

Add a hogli command: `hogli prom-compat smoke` that runs a canned PromQL query against the dev instance and prints the result.

### 9.4 Public DNS

New DNS record: `prometheus.posthog.com` → ingress → prom-compat service.
This is configured in the private `PostHog/charts` repo, not here.
The chart name `prom-compat` (set in the deploy dispatch payload) maps to that ingress.

Self-hosted users get a Helm value to override the hostname; default is `prometheus.posthog.com` only on PostHog Cloud.

## 10. Configuration

All config from env vars (matches the Rust precedent).

| Variable                           | Default       | Required | Purpose                               |
| ---------------------------------- | ------------- | -------- | ------------------------------------- |
| `HOST`                             | `0.0.0.0`     | no       | Bind address                          |
| `PORT`                             | `9090`        | no       | HTTP listen port                      |
| `CLICKHOUSE_LOGS_CLUSTER_HOST`     | —             | yes      | CH host                               |
| `CLICKHOUSE_LOGS_CLUSTER_PORT`     | `9000`        | no       | CH native port                        |
| `CLICKHOUSE_LOGS_CLUSTER_USER`     | —             | yes      | CH user (prefer dedicated read-only)  |
| `CLICKHOUSE_LOGS_CLUSTER_PASSWORD` | —             | yes      | CH password                           |
| `CLICKHOUSE_LOGS_CLUSTER_DATABASE` | —             | yes      | CH database                           |
| `POSTGRES_URL`                     | —             | yes      | Postgres DSN for auth fallback        |
| `REDIS_URL`                        | —             | yes      | Redis URL for auth cache + rate limit |
| `PROMQL_MAX_SAMPLES`               | `50000000`    | no       | Engine sample ceiling                 |
| `PROMQL_LOOKBACK_DELTA`            | `5m`          | no       | Engine lookback                       |
| `PROMQL_QUERY_TIMEOUT`             | `30s`         | no       | Engine timeout                        |
| `CH_MAX_CONCURRENT_QUERIES`        | `8`           | no       | Per-instance concurrency              |
| `CH_MAX_BYTES_TO_READ`             | `53687091200` | no       | 50 GB                                 |
| `AUTH_CACHE_TTL`                   | `60s`         | no       | Token cache TTL                       |
| `RATE_LIMIT_QPS`                   | `10`          | no       | Per-key QPS                           |
| `RATE_LIMIT_BURST`                 | `100`         | no       | Per-key burst                         |
| `PROM_COMPAT_DEV_AUTH_BYPASS`      | `false`       | no       | Dev-only                              |
| `CONTINUOUS_PROFILING_ENABLED`     | `false`       | no       | Pyroscope toggle                      |
| `OTEL_EXPORTER_OTLP_ENDPOINT`      | —             | no       | Self-tracing target                   |

## 11. Testing

### 11.1 Unit tests

- `internal/storage/*_test.go` for SQL generation and SeriesSet conversion (table-driven).
- `internal/auth/*_test.go` for token cache and Postgres fallback (mocked).
- `internal/api/*_test.go` for handler routing and error envelopes.

### 11.2 Integration tests

`tests/integration_test.go` against real services in Docker:

- ClickHouse seeded with canonical OTel fixtures (one of each metric type: gauge, sum cumulative, sum delta, histogram, exponential_histogram, summary).
- Postgres seeded with a personal API key scoped to team 1.
- Redis empty (forces Postgres fallback path on first auth).
- Full end-to-end exercising every endpoint, including:
  - `histogram_quantile(0.95, rate(http_server_duration_bucket[5m]))` returning numerically correct values (compared against an in-test computation from the raw bucket arrays).
  - `rate(delta_metric[1m])` on a delta sum returning the cumulative-equivalent rate.
  - Cross-team request blocked with 403.

### 11.3 Conformance test

Run `promtool tsdb create-blocks-from rules` is not applicable, but we will run the **Prometheus compliance test suite** (`github.com/prometheus/compliance/promql`) against prom-compat as a CI job.
That suite enumerates spec-mandated PromQL behaviors; passing it is our objective definition of "Prometheus-compatible."

### 11.4 Performance test

`tests/perf_test.go` exercises:

- p95 latency for `/query_range` over 1h with 5 metrics × 10 services = 50 series.
- Memory ceiling held under 1 GB for worst-case `sum by (service_name) (rate(metric[5m]))` over a 24h window.
- Concurrent-query semaphore under load (16 concurrent identical queries, none should error).

Targets: p95 ≤ 1.5s (per §1.2), throughput ≥ 50 RPS per instance.

## 12. Rollout

| Phase                     | Scope                                                                                 | Gate                                                                            |
| ------------------------- | ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| **0. Internal alpha**     | prom-compat in staging, pointed at synthetic OTel data, used by team-internal Grafana | All unit + integration tests green; conformance suite passes baseline endpoints |
| **1. Cloud beta (gated)** | Feature flag `prom-compat-enabled` for a handful of design partners                   | p95 < 1.5s on real traffic for 1 week; no auth incidents                        |
| **2. Cloud GA**           | Public docs, `prometheus.posthog.com` advertised                                      | Compliance suite passes 95%+; rate-limit overrides documented                   |
| **3. Self-hosted**        | Helm value in PostHog chart for self-hosted users                                     | GA stable for 30 days                                                           |

Feature flag at every layer:

- `prom_compat_enabled` (server-side) gates the service entirely — when off, the service still runs but returns 503 on all endpoints.
- `prom_compat_pushdown_enabled` gates Blocker 4's SQL pushdown so we can revert quickly if numerical regressions appear.

## 13. Risks

| Risk                                                       | Likelihood | Mitigation                                                                                                     |
| ---------------------------------------------------------- | ---------- | -------------------------------------------------------------------------------------------------------------- |
| Numerical drift between native UI and PromQL percentiles   | Medium     | Conformance suite + side-by-side comparison test against the existing `metric_query_runner` for p50/p95/p99    |
| Logs cluster contention with logs+tracing reads            | Medium     | Per-instance concurrency cap (8), per-key rate limit (10 QPS), `max_bytes_to_read=50GB`                        |
| Auth cache stampede on Redis cold start                    | Low        | Same pattern as `rust/feature-flags`; Postgres fallback is bounded by `pgx` pool size                          |
| Personal API key revocation latency                        | Low        | Existing Django cache-invalidation path (`posthog/storage/team_access_cache.py`) is reused                     |
| Delta-temporality `rate()` accuracy with gaps              | Medium     | Document as known limitation; the native UI doesn't need this so users hitting it are explicitly Grafana users |
| Snuffle author churn — schema layout could change upstream | High       | We don't depend on Snuffle as code. The schema is ours; we control it                                          |
| Go version drift in CI                                     | Low        | Pin in `go.mod` and `Dockerfile`, update via dependabot                                                        |
| Operational surprises (memory leaks, goroutine leaks)      | Medium     | Pyroscope continuous profiling enabled from day one; alert on RSS > 2 GB                                       |

## 14. Open questions

These must be resolved before Track A ships:

1. **Public DNS.** `prometheus.posthog.com` vs `metrics.posthog.com` vs `app.posthog.com/prom/...`?
   I lean toward `prometheus.posthog.com` because Grafana's default data-source name lookup matches and self-hosted operators recognize the convention.

2. **CH user.** Do we want a brand-new `prom_compat_readonly` CH user, or reuse the existing `READONLY_CLICKHOUSE_USER`?
   The former is cleaner for audit; the latter is one fewer secret to manage.
   Infra team decision.

3. **Personal API key scope name.** `metrics:read` already exists.
   Promote it from hidden to user-grantable, or introduce a new `prometheus:read` scope?
   I lean toward reusing `metrics:read` — same data, no point splitting.

4. **Recording rules.** Out of scope for v1 per §1.1, but worth deciding now whether v1.1 adds them.
   PostHog's existing alerting product overlaps; we should not build a parallel rules engine without consulting that team.

5. **Multi-region.** Cloud serves US + EU.
   `prometheus.posthog.com` resolves to which?
   Likely needs `us.prometheus.posthog.com` and `eu.prometheus.posthog.com`, matching `us.posthog.com` / `eu.posthog.com`.

## 15. Appendix — Snuffle file map for reviewers

For reviewers verifying the design against the structural reference, here are the Snuffle files to read:

- `cmd/snuffle/main.go` — 8-line trampoline; our `cmd/prom-compat/main.go` mirrors this shape.
- `internal/snuffle/api.go` (~27 KB) — HTTP router and handler wiring; our `internal/api/server.go` adapts this with chi + auth/tenant middleware.
- `internal/snuffle/storage.go` (~35 KB) — generic Querier; our `internal/storage/querier.go` follows the same `storage.Queryable` contract.
- `internal/snuffle/posthog_storage.go` (~14 KB) — the PostHog SQL builders; our `internal/storage/sql.go` will be derived from these with the four blocker fixes.
- `internal/snuffle/clickhouse.go` (~7.6 KB) — `clickhouse-go/v2` wrapper; our `internal/storage/client.go` mirrors with pool config calibrated to the logs cluster.
- `scripts/create_metrics_posthog_schema.sql` — the schema Snuffle expects; verified byte-identical to our `posthog/clickhouse/metrics/metrics1.py`.

Apache-2.0. Compatible with PostHog's MIT licensing.
Where structural code is derived from Snuffle, attribution comment in the relevant file.

## 16. Summary

A new Go service `services/prom-compat/` exposes a PromQL-compatible HTTP API over our existing `metrics1` table on the logs cluster.
It is an ecosystem adapter, not a replacement for the native metrics UI.
The structural template comes from `rorylshanks/snuffle`; the engine is the upstream `prometheus/prometheus` PromQL library.
Auth, multi-tenancy, and rate limiting mirror `rust/feature-flags`.
Deployment mirrors `services/mcp/` and `rust/capture-logs/` — Depot build, ECR push, `repository-dispatch` to charts.

The work is bounded: four well-scoped blocker fixes (histogram synthesis, delta normalization, per-request team, projection pushdown), ~3-4k LOC, ~6 weeks of one engineer's time including tests and rollout.
The strategic payoff is that PostHog metrics becomes a credible drop-in target for the entire Prometheus ecosystem without forking any of those tools.
