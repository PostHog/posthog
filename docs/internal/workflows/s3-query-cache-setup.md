# S3 query cache setup

Large cached query results (at least `QUERY_CACHE_S3_MIN_SIZE_BYTES` serialized bytes, default 1MB) can be stored as zstd-compressed S3 objects instead of inline Redis blobs. Redis then holds a small pointer record under the same cache key. See `posthog/query_cache/s3_blobs.py`.

## Semantics

- **Expiry is governed by the Redis pointer's TTL** (`CACHED_RESULTS_TTL`), not by S3. Once the pointer expires or is evicted, the entry is gone regardless of whether the S3 object still exists.
- **S3 lifecycle rules are garbage collection only.** They delete orphaned blobs (expired or evicted pointers, shadow-mode uploads, rolled-back teams). They are not a correctness mechanism, so their day-granularity is fine.
- Rollout is controlled by the `query-cache-s3-writes` multivariate feature flag on the organization group: disabled = inline Redis writes as always, `shadow` = upload blobs while Redis stays authoritative, `on` = store pointers. Reads never evaluate the flag; they follow whatever the stored record says.

## Object layout and tagging

Objects are written to `s3://{QUERY_CACHE_S3_BUCKET}/{OBJECT_STORAGE_S3_QUERY_CACHE_FOLDER}/{team_id}/{cache_key}` with tags:

```text
ttl_days=7              # CACHED_RESULTS_TTL_DAYS at write time
cache_type=query_data
team_id=123
```

## Required S3 lifecycle rules

Every `ttl_days` value the app emits needs a matching lifecycle rule. **Objects with `ttl_days` values lacking lifecycle rules will never expire.** Today the app emits a single value, `CACHED_RESULTS_TTL_DAYS` (7); if that setting changes, add the matching rule before deploying the change (see the warning in `posthog/settings/schedules.py`).

### AWS CLI

```bash
cat > lifecycle-config.json << EOF
{
    "Rules": [
        {
            "ID": "query-cache-ttl-7-days",
            "Status": "Enabled",
            "Filter": {
                "And": {
                    "Tags": [
                        {"Key": "ttl_days", "Value": "7"},
                        {"Key": "cache_type", "Value": "query_data"}
                    ]
                }
            },
            "Expiration": {"Days": 7}
        }
    ]
}
EOF

aws s3api put-bucket-lifecycle-configuration \
    --bucket your-bucket-name \
    --lifecycle-configuration file://lifecycle-config.json
```

### Terraform

```hcl
resource "aws_s3_bucket_lifecycle_configuration" "query_cache" {
  bucket = aws_s3_bucket.query_cache.id

  # One rule block per ttl_days value the app emits (a single value today)
  rule {
    id     = "query-cache-ttl-7-days"
    status = "Enabled"
    filter {
      and {
        tags = {
          ttl_days   = "7"
          cache_type = "query_data"
        }
      }
    }
    expiration {
      days = 7
    }
  }
}
```

## Settings

| Setting                                | Default                 | Meaning                                                                         |
| -------------------------------------- | ----------------------- | ------------------------------------------------------------------------------- |
| `QUERY_CACHE_S3_BUCKET`                | `OBJECT_STORAGE_BUCKET` | Bucket for cache blobs; a dedicated bucket keeps lifecycle rules and IAM narrow |
| `OBJECT_STORAGE_S3_QUERY_CACHE_FOLDER` | `query_cache`           | Key prefix inside the bucket                                                    |
| `QUERY_CACHE_S3_MIN_SIZE_BYTES`        | `1048576`               | Minimum serialized size for S3 routing                                          |
