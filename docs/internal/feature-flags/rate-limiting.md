# Rate limiting

The Rust feature flags service uses three independent rate limiters, all implemented in-process using the `governor` crate (token bucket algorithm):

| Limiter     | Scope         | Default config             | Purpose                            |
| ----------- | ------------- | -------------------------- | ---------------------------------- |
| IP-based    | Per source IP | 1250 burst / 50 per second | DDoS defense                       |
| Token-based | Per API token | 625 burst / 10 per second  | Per-project limits                 |
| Definitions | Per team ID   | 600 per minute             | `/flags/definitions` rate limiting |

Rate limiting runs before body decoding and authentication in the `/flags` request pipeline. IP is checked first, then token. The definitions limiter is a simple allow/deny gate with no warn tier.

## Warn-then-enforce model

The `/flags` IP and token limiters use a three-outcome model: `Allowed`, `Warned`, or `Blocked`. The definitions limiter does not use this model.

- **Allowed**: Request is below all thresholds — served normally.
- **Warned**: Request exceeds the warn capacity but is below enforce. The request succeeds, but the response includes `X-PostHog-Rate-Limit-Warning: true` so callers can react proactively. A `rate_limit_warned` field is also set in the canonical request log.
- **Blocked**: Request exceeds the enforce capacity — returns HTTP 429 with `{"type": "validation_error", "code": "rate_limit_exceeded"}`.

The CORS layer exposes `x-posthog-rate-limit-warning` via `Access-Control-Expose-Headers` so browser SDKs can read the warning header on cross-origin requests.

## Configuration modes

By default, the warn tier is derived at 80% of the enforce capacity (`FLAGS_WARN_CAPACITY_RATIO=0.8`). Operators only need to set the enforce capacity (`FLAGS_BUCKET_CAPACITY` / `FLAGS_IP_BURST_SIZE`) and the warn tier follows automatically. The ratio applies to both token and IP limiters.

Resolution logic lives in `resolve_rate_limit_capacities()` in `router.rs`. The mode is determined by `log_only` and the warn ratio:

| Mode                | Condition                         | Behavior                                                                                                                  |
| ------------------- | --------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| **Default**         | `log_only == false`, `ratio > 0`  | Warn tier is derived at `ratio` of enforce capacity. Operators get warning signals before hard 429s.                      |
| **Warn disabled**   | `log_only == false`, `ratio == 0` | No warn tier. Hard block at enforce capacity with no prior warning.                                                       |
| **Legacy log-only** | `log_only == true`                | Same thresholds as default mode, but never blocks (`warn_only` mode). Metrics show what _would_ happen under enforcement. |

### Migration path

To move from legacy log-only to full enforcement:

1. **Start** with the defaults: `FLAGS_RATE_LIMIT_LOG_ONLY=true` (observe via metrics)
2. **Monitor** using the `flags_rate_limit_exceeded_total` counter — two orthogonal labels:
   - `mode`: `log_only` (observe-only) or `enforcing` (actually blocking)
   - `action`: `warned` (crossed warn tier) or `blocked` (crossed enforce tier)
     In log-only mode, `action="blocked"` shows what _would_ be blocked without actually rejecting requests.
3. **Switch to enforce mode**: set `FLAGS_RATE_LIMIT_LOG_ONLY=false` — thresholds stay the same, but requests are now actually blocked
4. _(Optional)_ Adjust `FLAGS_WARN_CAPACITY_RATIO` if the default 80% doesn't fit your traffic pattern (0.0 disables the warn tier)
5. **Remove** the deprecated `FLAGS_RATE_LIMIT_LOG_ONLY` env var once satisfied

## Per-token overrides

The `FLAGS_TOKEN_RATE_LIMIT_OVERRIDES` env var accepts a JSON map of token → rate string for per-token custom rate limits:

```json
{ "phc_abc123": "1200/minute", "phc_xyz789": "2400/hour" }
```

These create dedicated enforce-only limiters that take precedence over the default token limiter for matching tokens. Maximum 100 overrides. Token values are redacted in logs (prefix + suffix only).

Rate strings follow the Django throttle format: `<count>/<period>` where period is one of `second`, `minute`, `hour`, or `day`.

## Lifecycle

A background task runs every 60 seconds (`RATE_LIMITER_CLEANUP_INTERVAL_SECS`) to call `retain_recent()` and `shrink_to_fit()` on all limiter stores, preventing unbounded memory growth from accumulated per-key entries.

## Configuration reference

| Variable                                   | Default | Purpose                                                            |
| ------------------------------------------ | ------- | ------------------------------------------------------------------ |
| `FLAGS_RATE_LIMIT_ENABLED`                 | `false` | Enable token-based rate limiting                                   |
| `FLAGS_BUCKET_CAPACITY`                    | `625`   | Token bucket enforce capacity (warn at 80% = 500)                  |
| `FLAGS_BUCKET_REPLENISH_RATE`              | `10.0`  | Tokens per second                                                  |
| `FLAGS_IP_RATE_LIMIT_ENABLED`              | `false` | Enable IP-based rate limiting                                      |
| `FLAGS_IP_BURST_SIZE`                      | `1250`  | IP bucket enforce capacity (warn at 80% = 1000)                    |
| `FLAGS_IP_REPLENISH_RATE`                  | `50.0`  | Requests per second per IP                                         |
| `FLAGS_WARN_CAPACITY_RATIO`                | `0.8`   | Warn tier as fraction of enforce capacity (0.0 disables warn tier) |
| `FLAGS_RATE_LIMIT_LOG_ONLY`                | `true`  | _(deprecated)_ Set to `false` and use `FLAGS_WARN_CAPACITY_RATIO`  |
| `FLAGS_IP_RATE_LIMIT_LOG_ONLY`             | `true`  | _(deprecated)_ Set to `false` and use `FLAGS_WARN_CAPACITY_RATIO`  |
| `FLAGS_TOKEN_RATE_LIMIT_OVERRIDES`         | (empty) | Per-token rate limit overrides as JSON (max 100)                   |
| `RATE_LIMITER_CLEANUP_INTERVAL_SECS`       | `60`    | Stale entry cleanup interval                                       |
| `FLAG_DEFINITIONS_DEFAULT_RATE_PER_MINUTE` | `600`   | Default rate for `/flags/definitions`                              |
| `LOCAL_EVAL_RATE_LIMITS`                   | (empty) | Per-team overrides for `/flags/definitions` as JSON                |

## Key files

| File                                               | Purpose                                                                |
| -------------------------------------------------- | ---------------------------------------------------------------------- |
| `rust/feature-flags/src/api/flags_rate_limiter.rs` | `FlagsRateLimiter`, `IpRateLimiter`, `KeyedRateLimiter` implementation |
| `rust/feature-flags/src/router.rs`                 | `resolve_rate_limit_capacities()`, limiter construction, cleanup task  |
| `rust/feature-flags/src/api/endpoint.rs`           | Request-time rate limit checks, warning header insertion               |
| `rust/feature-flags/src/config.rs`                 | Env var definitions, `FlagsTokenRateLimitOverrides` parsing            |
| `rust/feature-flags/tests/test_rate_limiting.rs`   | Integration tests                                                      |
