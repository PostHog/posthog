# S3 Query Cache TTL Implementation

## How It Works

1 **Object Tagging**: Each S3 object gets tags:

```text
ttl_days=1              # Calculated TTL in days
team_id=123            # Team identifier
```

2 **Automatic Deletion**: S3 lifecycle rules delete objects matching tag criteria

## Required S3 Lifecycle Rules

**Critical**: You must create lifecycle rules for every `ttl_days` value your app generates.

### AWS CLI Configuration

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

### Terraform Configuration

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
