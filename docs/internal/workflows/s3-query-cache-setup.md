# S3 query cache setup

The query cache zstd-compresses every entry it stores in Redis.
Entries whose compressed form is at least `QUERY_CACHE_S3_MIN_COMPRESSED_BYTES` (default 128KB) can be stored as S3 objects instead of inline Redis blobs; the same compressed bytes serve as the routing decision, the inline value, and the upload body.
Redis then holds a small pointer record under the same cache key.
The threshold applies to compressed bytes because that is what an entry actually costs in Redis.
See `posthog/query_cache/storage.py`.

## Semantics

- **Expiry is governed by the Redis pointer's TTL** (`CACHED_RESULTS_TTL`), not by S3. Once the pointer expires or is evicted, the entry is gone regardless of whether the S3 object still exists.
- **Blobs are deleted eagerly once nothing references them.** Replacing or evicting a pointer entry enqueues a best-effort Celery delete, delayed by `BLOB_DELETE_DELAY_SECONDS` (60s) so a reader that just fetched the pointer from Redis can still complete its S3 read. An upload whose pointer swap lost to a newer write deletes its own blob immediately, since that pointer never entered Redis.
- **The S3 lifecycle rule is the garbage collection backstop.** It deletes whatever the eager path misses: pointers that expired by TTL, shadow-mode uploads, rolled-back teams, failed deletes, and writes from a process that could not reach the Celery broker.
- Rollout is controlled by the `query-cache-s3-writes` multivariate feature flag on the organization group. It gates writes only; reads never evaluate the flag, they follow whatever the stored record says.
  - Disabled: every result is stored inline in Redis, as always.
  - `shadow`: write the cache entry to both S3 and Redis, testing the write path; nothing reads the S3 copy.
  - `on`: write the pointer to Redis and the entry to S3; reads fetch the blob from S3.

## Object layout and tagging

Objects are written to `s3://{QUERY_CACHE_S3_BUCKET}/{OBJECT_STORAGE_S3_QUERY_CACHE_FOLDER}/{team_id}/{cache_key}/{upload_id}` with attribution tags (`cache_type=query_data`, `team_id=<id>`). Tags carry no expiry meaning. The per-upload suffix keeps overlapping recomputes of one query from overwriting each other's blob. A superseded upload deletes its own object on the spot, and replaced or evicted pointers get theirs deleted by the delayed Celery task, so a frequently recomputed query does not accumulate a week of dead blobs.

## Required S3 lifecycle rule

One rule: expire objects after `CACHED_RESULTS_TTL_DAYS` (7) days.
The cloud buckets (`posthog-query-cache-<region>-<env>`) are dedicated to this cache, so their rule is bucket-wide; it is managed in posthog-cloud-infra, `terraform/modules/s3/main.tf` (`enable_query_cache_lifecycle`).

**On a shared bucket, scope the rule to the `OBJECT_STORAGE_S3_QUERY_CACHE_FOLDER` prefix** (`query_cache/` by default). `QUERY_CACHE_S3_BUCKET` falls back to the shared `OBJECT_STORAGE_BUCKET` when unset, and a bucket-wide expiry rule there would also delete exports, media uploads, and error-tracking source maps.

**If `CACHED_RESULTS_TTL_DAYS` is ever raised, raise the bucket rule first**, otherwise S3 deletes blobs while their Redis pointers still live and large cache entries silently expire early. Lowering the setting is safe: blobs then just outlive their pointers by a few days before GC.

## Settings

| Setting                                | Default                 | Meaning                                                                |
| -------------------------------------- | ----------------------- | ---------------------------------------------------------------------- |
| `QUERY_CACHE_S3_BUCKET`                | `OBJECT_STORAGE_BUCKET` | Bucket for cache blobs (`posthog-query-cache-<region>-<env>` in cloud) |
| `OBJECT_STORAGE_S3_QUERY_CACHE_FOLDER` | `query_cache`           | Key prefix inside the bucket                                           |
| `QUERY_CACHE_S3_MIN_COMPRESSED_BYTES`  | `131072`                | Minimum zstd-compressed size for S3 routing                            |

These are plain environment variables read at process start. Cloud runs the defaults; overriding one in production means plumbing it through the deployment charts first, the same as any other app setting.
