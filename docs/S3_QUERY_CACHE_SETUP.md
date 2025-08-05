# S3 Query Cache Setup

PostHog's S3 query cache provides a durable, scalable alternative to Redis for storing query results.

## Overview

| Feature | Redis Cache | S3 Cache |
|---------|-------------|----------|
| TTL Granularity | Seconds | Days (rounded up) |
| Performance | Very fast (in-memory) | Slower (network requests) |
| Durability | Memory-based | Persistent storage |
| Scalability | Memory-limited | Unlimited |
| Cost | RAM costs | Storage + request costs |

The S3 cache stores query results as objects with automatic TTL via S3 lifecycle rules. Redis is only used for tracking stale insights metadata.

## Configuration

### Feature Flag
Enable `query-cache-use-s3` feature flag per organization/user:
- **OFF (default)**: Uses Redis
- **ON**: Uses S3

### Environment Variables
```bash
# Optional: dedicated bucket (defaults to OBJECT_STORAGE_BUCKET)
QUERY_CACHE_S3_BUCKET=my-query-cache-bucket

# Required: standard object storage settings
OBJECT_STORAGE_ENABLED=true
OBJECT_STORAGE_ENDPOINT=https://s3.amazonaws.com
OBJECT_STORAGE_BUCKET=my-bucket
OBJECT_STORAGE_ACCESS_KEY_ID=your-key
OBJECT_STORAGE_SECRET_ACCESS_KEY=your-secret
OBJECT_STORAGE_REGION=us-east-1
```

## TTL Implementation

### How It Works
1. **TTL Calculation**: `math.ceil(CACHED_RESULTS_TTL_seconds / 86400)`, minimum 1 day
2. **Object Tagging**: Each S3 object gets tags:
   ```
   ttl_days=1              # Calculated TTL in days
   cache_type=query_data   # Object type identifier
   team_id=123            # Team identifier
   ```
3. **Automatic Deletion**: S3 lifecycle rules delete objects matching tag criteria

### Required S3 Lifecycle Rules

**Critical**: You must create lifecycle rules for every `ttl_days` value your app generates.

#### Example Configuration
```bash
# Create rules for common TTL values: 1, 2, 7, 14, 30 days
cat > lifecycle-config.json << EOF
{
    "Rules": [
        {
            "ID": "query-cache-ttl-1-day",
            "Status": "Enabled",
            "Filter": {
                "And": {
                    "Tags": [
                        {"Key": "ttl_days", "Value": "1"},
                        {"Key": "cache_type", "Value": "query_data"}
                    ]
                }
            },
            "Expiration": {"Days": 1}
        },
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

#### Terraform
```hcl
resource "aws_s3_bucket_lifecycle_configuration" "query_cache" {
  bucket = aws_s3_bucket.query_cache.id

  # Repeat this rule block for each TTL value (1, 2, 7, 14, 30 days)
  rule {
    id     = "query-cache-ttl-1-day"
    status = "Enabled"
    filter {
      and {
        tags = {
          ttl_days   = "1"
          cache_type = "query_data"
        }
      }
    }
    expiration {
      days = 1
    }
  }
}
```

**Warning**: Objects with `ttl_days` values lacking lifecycle rules will never expire.

## Usage

```python
from posthog.hogql_queries.query_cache_factory import get_query_cache_manager

# Factory automatically chooses backend based on feature flag
cache_manager = get_query_cache_manager(
    team_id=team.pk,
    cache_key="query_hash",
    insight_id=123,
    dashboard_id=456,
    user=request.user,  # Optional: for user-specific flag evaluation
)

# Same interface regardless of backend
cache_manager.set_cache_data(response=data, target_age=datetime.now(UTC))
cached_data = cache_manager.get_cache_data()
```

## Migration Strategy

1. **Setup S3 bucket and lifecycle rules** for all expected TTL values
2. **Enable feature flag** for test organizations
3. **Monitor** cache hit rates, latency, costs
4. **Gradual rollout** to larger organizations
5. **Full migration** once stable

## Troubleshooting

### Objects Not Expiring
- Missing lifecycle rule for the `ttl_days` value
- Incorrect object tags (`cache_type=query_data`, `ttl_days=X`)
- Lifecycle rules take up to 24 hours to take effect

### Performance Issues
- Monitor network latency to S3
- Consider S3 Transfer Acceleration
- Use CloudWatch for request patterns

### High Costs
- Review lifecycle policies
- Consider storage classes (IA for longer TTLs)
- Monitor GET/PUT request volumes

## Security

- Use IAM roles with minimal S3 permissions
- Enable S3 bucket encryption
- Consider VPC endpoints for private access