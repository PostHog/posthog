# S3 Query Cache Setup

This document describes how to configure and use the S3-based query cache manager as an alternative to Redis.

## Overview

The S3 Query Cache Manager stores query results in S3 objects with automatic TTL management via S3 lifecycle rules. This provides a durable, scalable alternative to Redis for query caching.

## Key Differences from Redis

| Feature | Redis | S3 |
|---------|-------|-----|
| TTL Granularity | Seconds | Days (rounded up) |
| Performance | In-memory, very fast | Network-based, slower |
| Durability | Memory-based, can lose data | Persistent storage |
| Scalability | Limited by memory | Virtually unlimited |
| Cost | RAM costs | Storage + request costs |
| Consistency | Immediate | Eventually consistent |

## Configuration

### Environment Variables

```bash
# Enable S3 query cache
QUERY_CACHE_BACKEND=s3

# Optional: Use specific bucket (defaults to OBJECT_STORAGE_BUCKET)
QUERY_CACHE_S3_BUCKET=my-query-cache-bucket

# Standard object storage settings
OBJECT_STORAGE_ENABLED=true
OBJECT_STORAGE_ENDPOINT=https://s3.amazonaws.com
OBJECT_STORAGE_BUCKET=my-bucket
OBJECT_STORAGE_ACCESS_KEY_ID=your-key
OBJECT_STORAGE_SECRET_ACCESS_KEY=your-secret
OBJECT_STORAGE_REGION=us-east-1
```

### Django Settings

```python
# In your settings file
QUERY_CACHE_BACKEND = "s3"  # or "redis" (default)
QUERY_CACHE_S3_BUCKET = "my-query-cache-bucket"  # optional
```

## Required S3 Lifecycle Configuration

For TTL functionality to work, you must configure S3 lifecycle rules that automatically delete objects based on their tags:

### Lifecycle Rule for Query Results

```json
{
    "Rules": [
        {
            "ID": "query-cache-ttl",
            "Status": "Enabled",
            "Filter": {
                "And": {
                    "Tags": [
                        {
                            "Key": "cache_type",
                            "Value": "query_results"
                        }
                    ]
                }
            },
            "Expiration": {
                "Days": 1
            }
        },
        {
            "ID": "query-cache-ttl-2-days",
            "Status": "Enabled",
            "Filter": {
                "And": {
                    "Tags": [
                        {
                            "Key": "ttl_days",
                            "Value": "2"
                        },
                        {
                            "Key": "cache_type",
                            "Value": "query_results"
                        }
                    ]
                }
            },
            "Expiration": {
                "Days": 2
            }
        },
        {
            "ID": "query-cache-ttl-7-days",
            "Status": "Enabled",
            "Filter": {
                "And": {
                    "Tags": [
                        {
                            "Key": "ttl_days",
                            "Value": "7"
                        },
                        {
                            "Key": "cache_type",
                            "Value": "query_results"
                        }
                    ]
                }
            },
            "Expiration": {
                "Days": 7
            }
        },
        {
            "ID": "query-cache-target-age-cleanup",
            "Status": "Enabled",
            "Filter": {
                "And": {
                    "Tags": [
                        {
                            "Key": "cache_type",
                            "Value": "target_age"
                        }
                    ]
                }
            },
            "Expiration": {
                "Days": 30
            }
        }
    ]
}
```

### AWS CLI Setup

```bash
# Save the lifecycle configuration to a file
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
                        {"Key": "cache_type", "Value": "query_results"}
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
                        {"Key": "cache_type", "Value": "query_results"}
                    ]
                }
            },
            "Expiration": {"Days": 7}
        },
        {
            "ID": "query-cache-target-age-cleanup",
            "Status": "Enabled",
            "Filter": {
                "And": {
                    "Tags": [
                        {"Key": "cache_type", "Value": "target_age"}
                    ]
                }
            },
            "Expiration": {"Days": 30}
        }
    ]
}
EOF

# Apply the lifecycle configuration
aws s3api put-bucket-lifecycle-configuration \
    --bucket your-bucket-name \
    --lifecycle-configuration file://lifecycle-config.json
```

### Terraform Configuration

```hcl
resource "aws_s3_bucket_lifecycle_configuration" "query_cache" {
  bucket = aws_s3_bucket.query_cache.id

  rule {
    id     = "query-cache-ttl-1-day"
    status = "Enabled"

    filter {
      and {
        tags = {
          ttl_days   = "1"
          cache_type = "query_results"
        }
      }
    }

    expiration {
      days = 1
    }
  }

  rule {
    id     = "query-cache-ttl-7-days"
    status = "Enabled"

    filter {
      and {
        tags = {
          ttl_days   = "7"
          cache_type = "query_results"
        }
      }
    }

    expiration {
      days = 7
    }
  }

  rule {
    id     = "query-cache-target-age-cleanup"
    status = "Enabled"

    filter {
      and {
        tags = {
          cache_type = "target_age"
        }
      }
    }

    expiration {
      days = 30
    }
  }
}
```

## Object Structure

### Cache Data Objects

```
query_cache/{team_id}/{cache_key}
```

Contains the serialized query results as JSON.

**Tags:**
- `ttl_days`: Number of days for TTL (1, 7, etc.)
- `cache_type`: "query_results"

### Target Age Tracking Objects

```
query_cache_timestamps/{team_id}/{insight_id}_{dashboard_id}
```

Contains target age metadata as JSON:

```json
{
    "target_age": "2024-01-15T10:30:00+00:00",
    "insight_id": 123,
    "dashboard_id": 456,
    "team_id": 789,
    "updated_at": "2024-01-14T12:00:00+00:00"
}
```

**Tags:**
- `cache_type`: "target_age"
- `ttl_days`: "30" (longer retention for tracking)

## Usage

```python
from posthog.hogql_queries.query_cache_factory import get_query_cache_manager

# Get the configured cache manager (Redis or S3 based on settings)
cache_manager = get_query_cache_manager(
    team_id=team.pk,
    cache_key="my_query_hash",
    insight_id=123,
    dashboard_id=456,
)

# Use the same interface regardless of backend
response_data = {"results": [...], "count": 42}
cache_manager.set_cache_data(response=response_data, target_age=datetime.now(UTC))

# Retrieve cached data
cached_data = cache_manager.get_cache_data()

# Get stale insights
stale_insights = cache_manager.get_stale_insights(team_id=team.pk, limit=10)
```

## Migration from Redis

1. **Parallel Running**: Both Redis and S3 cache managers implement the same interface, so you can run them in parallel during migration.

2. **Gradual Migration**: Use feature flags or settings to gradually migrate teams to S3.

3. **Monitoring**: Monitor S3 costs and performance compared to Redis.

## Performance Considerations

### Advantages
- **Durability**: Data persists across Redis restarts
- **Scalability**: No memory limitations
- **Cost**: Potentially lower cost for infrequently accessed data

### Disadvantages
- **Latency**: Network requests vs in-memory access
- **Eventual Consistency**: S3 operations are eventually consistent
- **TTL Granularity**: Day-level TTL vs second-level TTL in Redis

## Monitoring

Key metrics to monitor:

1. **S3 Request Costs**: GET, PUT, DELETE operations
2. **S3 Storage Costs**: Amount of data stored
3. **Cache Hit Rates**: Effectiveness of caching
4. **Latency**: Time to retrieve cached data
5. **Lifecycle Rule Effectiveness**: Objects being deleted as expected

## Troubleshooting

### Objects Not Expiring
- Check lifecycle rules are properly configured
- Verify object tags are being set correctly
- Lifecycle rules may take up to 24 hours to take effect

### Poor Performance
- Consider using S3 Transfer Acceleration
- Implement connection pooling
- Cache frequently accessed objects in Redis as well (hybrid approach)

### High Costs
- Review object lifecycle policies
- Consider different storage classes (IA, Glacier)
- Monitor request patterns

## Security

- Use IAM roles with minimal permissions
- Enable S3 bucket encryption
- Consider VPC endpoints for private network access
- Implement bucket policies to restrict access