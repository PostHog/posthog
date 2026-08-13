# S3 query cache setup

Large cached query results (at least `QUERY_CACHE_S3_MIN_SIZE_BYTES` serialized bytes, default 1MB) can be stored as zstd-compressed S3 objects instead of inline Redis blobs. Redis then holds a small pointer record under the same cache key. See `posthog/query_cache/s3_blobs.py`.

## Semantics

- **Expiry is governed by the Redis pointer's TTL** (`CACHED_RESULTS_TTL`), not by S3. Once the pointer expires or is evicted, the entry is gone regardless of whether the S3 object still exists.
- **The S3 lifecycle rule is garbage collection only.** It deletes blobs once nothing can reference them (expired or evicted pointers, shadow-mode uploads, rolled-back teams).
- Rollout is controlled by the `query-cache-s3-writes` multivariate feature flag on the organization group: disabled = inline Redis writes as always, `shadow` = upload blobs while Redis stays authoritative, `on` = store pointers. Reads never evaluate the flag; they follow whatever the stored record says.

## Object layout and tagging

Objects are written to `s3://{QUERY_CACHE_S3_BUCKET}/{OBJECT_STORAGE_S3_QUERY_CACHE_FOLDER}/{team_id}/{cache_key}` with attribution tags (`cache_type=query_data`, `team_id=<id>`). Tags carry no expiry meaning.

## Required S3 lifecycle rule

One flat rule: expire every object after `CACHED_RESULTS_TTL_DAYS` (7) days. The buckets (`posthog-query-cache-<region>-<env>`) are managed in posthog-cloud-infra, `terraform/modules/s3/main.tf` (`enable_query_cache_lifecycle`).

**If `CACHED_RESULTS_TTL_DAYS` is ever raised, raise the bucket rule first**, otherwise S3 deletes blobs while their Redis pointers still live and large cache entries silently expire early. Lowering the setting is safe: blobs then just outlive their pointers by a few days before GC.

## Settings

| Setting | Default | Meaning |
| --- | --- | --- |
| `QUERY_CACHE_S3_BUCKET` | `OBJECT_STORAGE_BUCKET` | Bucket for cache blobs (`posthog-query-cache-<region>-<env>` in cloud) |
| `OBJECT_STORAGE_S3_QUERY_CACHE_FOLDER` | `query_cache` | Key prefix inside the bucket |
| `QUERY_CACHE_S3_MIN_SIZE_BYTES` | `1048576` | Minimum serialized size for S3 routing |
