# HyperCache System

PostHog's HyperCache provides multi-tier caching with Redis → S3 → Database fallback. It's designed for high-traffic, read-heavy endpoints where pre-caching every possible value is worth the storage cost.

## Architecture overview

```text
┌─────────────────────────────────────────────────────────────────┐
│                         Client Request                          │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Redis (Layer 1)                          │
│                        TTL: 30 days                             │
│                        Latency: ~1-2ms                          │
└─────────────────────────────────────────────────────────────────┘
                                │ miss
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                         S3 (Layer 2)                            │
│                        Latency: ~50-100ms                       │
│                        Warms Redis on hit                       │
└─────────────────────────────────────────────────────────────────┘
                                │ miss
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Database (Layer 3)                         │
│                        Latency: ~200-500ms                      │
│                        Warms Redis + S3                         │
└─────────────────────────────────────────────────────────────────┘
```

## Core components

| Component        | File                                              | Purpose                          |
| ---------------- | ------------------------------------------------- | -------------------------------- |
| HyperCache class | `posthog/storage/hypercache.py`                   | Multi-tier cache with fallback   |
| Local evaluation | `posthog/models/feature_flag/local_evaluation.py` | Feature flag caching for SDKs    |
| Remote config    | `posthog/models/remote_config.py`                 | Client configuration caching     |
| Team caching     | `posthog/models/team/team_caching.py`             | Authentication team lookup cache |

## HyperCache class

The `HyperCache` class in `posthog/storage/hypercache.py` provides the core caching logic.

### Creating an instance

```python
from posthog.storage.hypercache import HyperCache

cache = HyperCache(
    namespace="feature_flags",           # Category name for metrics
    value="flags_with_cohorts.json",     # Value identifier for metrics
    load_fn=lambda key: load_data(key),  # Fallback loader when cache misses
    token_based=False,                   # Use team ID (False) or API token (True)
    cache_ttl=60 * 60 * 24 * 30,        # 30 days for cache hits
    cache_miss_ttl=60 * 60 * 24,        # 1 day for cache misses
    enable_etag=True,                    # Enable HTTP 304 support
)
```

### Cache key formats

The `token_based` parameter determines the cache key structure:

- **Team ID-based** (`token_based=False`): `cache/teams/{team_id}/{namespace}/{value}`
- **Token-based** (`token_based=True`): `cache/team_tokens/{api_token}/{namespace}/{value}`

### Key methods

| Method                            | Purpose                                                         |
| --------------------------------- | --------------------------------------------------------------- |
| `get_from_cache(key)`             | Get cached data, returns `None` on miss                         |
| `get_from_cache_with_source(key)` | Returns `(data, source)` where source is `redis`, `s3`, or `db` |
| `get_if_none_match(key, etag)`    | ETag support for HTTP 304 responses                             |
| `update_cache(key)`               | Force refresh from database                                     |
| `set_cache_value(key, data)`      | Write to both Redis and S3                                      |
| `clear_cache(key)`                | Delete from Redis and S3 (tests only)                           |

### ETag support

HyperCache supports HTTP 304 "Not Modified" responses to reduce bandwidth:

```python
data, etag, modified = cache.get_if_none_match(team, client_etag)

if not modified:
    return HttpResponse(status=304, headers={"ETag": etag})
else:
    return JsonResponse(data, headers={"ETag": etag})
```

ETags are computed as SHA256 hashes of the JSON content.

## Local evaluation caching

Feature flag local evaluation uses two separate HyperCache instances in `posthog/models/feature_flag/local_evaluation.py`:

```python
# Full flags with cohort definitions (for smart clients)
flags_hypercache = HyperCache(
    namespace="feature_flags",
    value="flags_with_cohorts.json",
    load_fn=lambda key: _get_flags_response_for_local_evaluation(team, include_cohorts=True),
    enable_etag=True,
)

# Simplified flags without cohorts (legacy)
flags_without_cohorts_hypercache = HyperCache(
    namespace="feature_flags",
    value="flags_without_cohorts.json",
    load_fn=lambda key: _get_flags_response_for_local_evaluation(team, include_cohorts=False),
    enable_etag=True,
)
```

All current SDKs support cohort evaluation locally, so the dual-cache strategy is legacy. The `flags_without_cohorts` cache exists for older SDK versions that couldn't handle cohort definitions. Once requests for flags without cohorts decline sufficiently, this cache can be removed.

### Cache invalidation

Django signals trigger cache updates when models change:

```python
@receiver([post_save, post_delete], sender=FeatureFlag)
def feature_flag_changed(sender, instance, **kwargs):
    transaction.on_commit(lambda: update_team_flags_cache.delay(instance.team_id))
```

Models that invalidate the flags cache:

- `FeatureFlag` - Flag created, updated, or deleted
- `Cohort` - Cohort properties changed
- `FeatureFlagEvaluationTag` - Evaluation tags changed
- `Tag` - Tag renamed

## Remote config caching

Remote config uses a different caching strategy than local evaluation. It prioritizes zero-overhead cache hits by using Redis-only caching for serving, with HyperCache used only for background sync operations.

### Cache lookup flow

```python
def _get_config_via_cache(cls, token: str) -> dict:
    key = f"remote_config/{token}/config"

    data = cache.get(key)  # Direct Redis lookup
    if data:
        return data  # Cache hit - zero database calls

    # Cache miss - query database and warm cache
    remote_config = RemoteConfig.objects.select_related("team").get(team__api_token=token)
    data = remote_config.build_config()
    cache.set(key, data, timeout=CACHE_TIMEOUT)  # 1 day

    return data
```

### No authentication

Remote config endpoints have no authentication (`authentication_classes = []`). The token in the URL is treated as a public identifier, not a credential. This eliminates all authentication overhead for cache hits.

### CDN integration

When remote config changes, the system:

1. Updates the database record
2. Warms the HyperCache (Redis + S3)
3. Updates the Redis serving cache
4. Purges Cloudflare CDN cache

## Team authentication caching

Team objects are cached by API token in `posthog/models/team/team_caching.py` to avoid database lookups during authentication.

### Cache format

```python
# Cache key
f"team_token:{api_token}"

# TTL: 5 days
FIVE_DAYS = 60 * 60 * 24 * 5
```

### Usage

```python
from posthog.models.team.team_caching import get_team_in_cache, set_team_in_cache

# Check cache first
team = get_team_in_cache(api_token)
if team is None:
    team = Team.objects.get(api_token=api_token)
    set_team_in_cache(api_token, team)
```

The cached team is serialized using `CachingTeamSerializer` and reconstructed as a `Team` instance on retrieval.

## Cache TTL settings

| Cache                 | Hit TTL | Miss TTL              |
| --------------------- | ------- | --------------------- |
| HyperCache (default)  | 30 days | 1 day                 |
| Remote config serving | 1 day   | 1 day                 |
| Team authentication   | 5 days  | N/A (deleted on miss) |

## Performance characteristics

| Scenario                     | Latency    | Database calls        |
| ---------------------------- | ---------- | --------------------- |
| Local evaluation (Redis hit) | ~1-2ms     | 0 (but auth overhead) |
| Remote config (Redis hit)    | ~1ms       | 0                     |
| S3 fallback                  | ~50-100ms  | 0                     |
| Database fallback            | ~200-500ms | 1+                    |

## Prometheus metrics

| Metric                                     | Labels                         | Purpose                         |
| ------------------------------------------ | ------------------------------ | ------------------------------- |
| `posthog_hypercache_get_from_cache`        | `result`, `namespace`, `value` | Cache hit/miss tracking         |
| `posthog_hypercache_sync`                  | `result`, `namespace`, `value` | Cache sync task outcomes        |
| `posthog_hypercache_sync_duration_seconds` | `result`, `namespace`, `value` | Cache sync timing               |
| `posthog_remote_config_via_cache`          | `result`                       | Remote config cache performance |

Result labels: `hit_redis`, `hit_s3`, `hit_db`, `missing`, `batch_miss`

## Debugging

### Check Redis cache

```bash
# Local evaluation flags
redis-cli get "cache/teams/{team_id}/feature_flags/flags_with_cohorts.json"

# Remote config
redis-cli get "remote_config/{api_token}/config"

# Team authentication
redis-cli get "team_token:{api_token}"
```

### Check cache source in responses

Local evaluation responses include cache source information via Prometheus metrics. Check the `posthog_hypercache_get_from_cache` metric with the appropriate labels.

### Force cache refresh

```python
from posthog.models.feature_flag.local_evaluation import update_flag_caches
from posthog.models.team import Team

team = Team.objects.get(id=123)
update_flag_caches(team)
```

## Common issues

| Symptom                      | Likely cause                         | Solution                              |
| ---------------------------- | ------------------------------------ | ------------------------------------- |
| Stale data after flag change | Signal not firing                    | Check transaction.on_commit is used   |
| Cache misses in production   | Redis connection issues              | Check Redis connectivity and metrics  |
| S3 fallback errors           | Object storage misconfigured         | Verify OBJECT_STORAGE_ENABLED setting |
| ETag mismatches              | Non-deterministic JSON serialization | HyperCache uses `sort_keys=True`      |

## Dedicated flags Redis

The feature-flags Rust service can use a separate Redis instance for caching, isolated from the shared Django cache. This prevents flag cache operations from affecting other cache users.

### Enabling dedicated Redis

```bash
FLAGS_REDIS_URL=redis://flags-redis:6379  # Separate instance for flags
```

When `FLAGS_REDIS_URL` is set, the system uses a dual-write pattern:

```python
# posthog/caching/flags_redis_cache.py
def write_flags_to_cache(key: str, value: Any, timeout: Optional[int] = None) -> None:
    # Always write to shared cache (Django reads from here)
    cache.set(key, value, timeout)

    # Also write to dedicated cache if configured (Rust service reads from here)
    if has_dedicated_cache:
        dedicated_cache = caches[FLAGS_DEDICATED_CACHE_ALIAS]
        dedicated_cache.set(key, value, timeout)
```

### Why dual-write?

| Consumer     | Reads from      | Purpose                         |
| ------------ | --------------- | ------------------------------- |
| Django       | Shared cache    | Local evaluation, SDK endpoints |
| Rust service | Dedicated cache | High-throughput flag evaluation |

The dual-write pattern is temporary while the Rust port is being completed. Once the Rust service handles all flag evaluation, Django will stop writing to the shared cache for local evaluation, and only the dedicated cache will be used.

The Rust service only operates when `FLAGS_REDIS_URL` is configured. All cache update functions check this setting and skip operations if not set.

## Scheduled tasks

Cache freshness is maintained through scheduled Celery tasks.

| Task                                       | Schedule         | Purpose                                              |
| ------------------------------------------ | ---------------- | ---------------------------------------------------- |
| `refresh_expiring_flags_cache_entries`     | Hourly at :15    | Refresh caches with TTL < 24h before they expire     |
| `cleanup_stale_flags_expiry_tracking_task` | Daily at 3:15 AM | Remove expired team entries from tracking sorted set |
| `verify_and_fix_flags_cache_task`          | Every 30 min     | Compare cache to database and fix mismatches         |

### Refresh task

The hourly refresh job prevents cache misses by proactively refreshing entries before they expire:

```python
# posthog/tasks/feature_flags.py
@shared_task
def refresh_expiring_flags_cache_entries():
    successful, failed = refresh_expiring_flags_caches(
        ttl_threshold_hours=settings.FLAGS_CACHE_REFRESH_TTL_THRESHOLD_HOURS,  # Default: 24
        limit=settings.FLAGS_CACHE_REFRESH_LIMIT,  # Default: 5000
    )
```

The task uses a Redis sorted set (`flags_cache_expiry`) to efficiently find expiring entries without scanning all keys.

### Verification task

The verification task compares cached data against the database and fixes discrepancies:

1. Samples teams from the cache
2. Compares cached flags to current database state
3. Auto-fixes mismatches by refreshing the cache
4. Reports metrics on match/mismatch/miss rates

Configuration:

```bash
FLAGS_CACHE_VERIFICATION_GRACE_PERIOD_MINUTES=5  # Skip recently updated flags
```

### For initial cache build

Scheduled tasks only maintain existing caches. For initial population or schema migrations, use the management command:

```bash
python manage.py warm_flags_cache [--invalidate-first]
```

## Signal handlers

Django signals automatically invalidate the cache when models change.

### Models that trigger cache updates

| Model                      | Signal      | Action                             |
| -------------------------- | ----------- | ---------------------------------- |
| `FeatureFlag`              | post_save   | Refresh team's flags cache         |
| `FeatureFlag`              | post_delete | Refresh team's flags cache         |
| `Team`                     | post_save   | Warm cache for new team            |
| `Team`                     | post_delete | Clear team's flags cache           |
| `FeatureFlagEvaluationTag` | post_save   | Refresh team's flags cache         |
| `FeatureFlagEvaluationTag` | post_delete | Refresh team's flags cache         |
| `Tag`                      | post_save   | Refresh caches for teams using tag |

### Transaction safety

All signal handlers use `transaction.on_commit()` to avoid race conditions:

```python
# posthog/models/feature_flag/flags_cache.py
@receiver([post_save, post_delete], sender=FeatureFlag)
def feature_flag_changed_flags_cache(sender, instance, **kwargs):
    transaction.on_commit(lambda: update_team_service_flags_cache.delay(instance.team_id))
```

This ensures the cache update task runs after the database transaction commits, not before.

### Cohort invalidation

The local evaluation cache (for SDKs) also invalidates when cohorts change. See `posthog/models/feature_flag/local_evaluation.py` for the full signal handler list.

## Configuration

```bash
# Required
REDIS_URL=redis://localhost:6379

# Dedicated flags Redis (optional, enables dual-write)
FLAGS_REDIS_URL=redis://flags-redis:6379

# Cache TTL settings
FLAGS_CACHE_TTL=604800             # 7 days (default)
FLAGS_CACHE_MISS_TTL=86400         # 1 day (default)

# Scheduled task settings
FLAGS_CACHE_REFRESH_TTL_THRESHOLD_HOURS=24  # Refresh caches expiring within 24h
FLAGS_CACHE_REFRESH_LIMIT=5000              # Max teams per refresh run
FLAGS_CACHE_VERIFICATION_GRACE_PERIOD_MINUTES=5  # Skip recently updated flags

# For S3 fallback
OBJECT_STORAGE_ENABLED=true
AWS_S3_BUCKET_NAME=posthog-cache

# Remote config CDN purge (optional)
REMOTE_CONFIG_CDN_PURGE_ENDPOINT=https://api.cloudflare.com/...
REMOTE_CONFIG_CDN_PURGE_TOKEN=...
REMOTE_CONFIG_CDN_PURGE_DOMAINS=["cdn.example.com"]
```

## Related files

- `posthog/storage/hypercache.py` - Core HyperCache implementation
- `posthog/models/feature_flag/local_evaluation.py` - Local evaluation caching
- `posthog/models/feature_flag/flags_cache.py` - Flags cache, signal handlers, verification
- `posthog/caching/flags_redis_cache.py` - Dual-write pattern for dedicated Redis
- `posthog/models/remote_config.py` - Remote config caching
- `posthog/models/team/team_caching.py` - Team authentication caching
- `posthog/tasks/feature_flags.py` - Cache update and refresh Celery tasks
- `posthog/tasks/hypercache_verification.py` - Cache verification task
- `posthog/tasks/remote_config.py` - Remote config sync tasks
- `posthog/tasks/scheduled.py` - Task schedule definitions

## See also

- [Server-side local evaluation](https://posthog.com/docs/feature-flags/local-evaluation) - Public docs on local evaluation
- [Local evaluation in distributed environments](https://posthog.com/docs/feature-flags/local-evaluation/distributed-environments) - Using external cache providers
- [Remote config](https://posthog.com/docs/feature-flags/remote-config) - Client-side configuration delivery
- [Cutting feature flag costs](https://posthog.com/docs/feature-flags/cutting-costs) - Cost optimization strategies
