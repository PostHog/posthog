# Feature flag billing

This document explains how the Rust feature flags service tracks usage for billing purposes, including Redis counter management, scheduled aggregation, and event processing.

## Architecture overview

```text
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           Feature Flag Request Flow                                  │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  ┌──────────────┐     ┌─────────────┐     ┌───────────────┐     ┌───────────────┐  │
│  │ SDK Request  │────▶│ Rust /flags │────▶│ Redis Counter │────▶│ Time-bucketed │  │
│  │ (/decide)    │     │ Service     │     │ Increment     │     │ Hash Storage  │  │
│  └──────────────┘     └─────────────┘     └───────────────┘     └───────────────┘  │
│                                                                                     │
│  ┌──────────────────────────────────────────────────────────────────────────────┐  │
│  │                    Aggregation (every 30 minutes)                            │  │
│  │  ┌─────────────┐     ┌─────────────┐     ┌───────────────┐     ┌──────────┐  │  │
│  │  │ Celery Task │────▶│ Read Redis  │────▶│ Emit PostHog  │────▶│ Store in │  │  │
│  │  │             │     │ Counters    │     │ Events        │     │ CH       │  │  │
│  │  └─────────────┘     └─────────────┘     └───────────────┘     └──────────┘  │  │
│  └──────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                     │
│  ┌──────────────────────────────────────────────────────────────────────────────┐  │
│  │                    Usage Report Generation                                   │  │
│  │  ┌─────────────┐     ┌─────────────┐     ┌───────────────┐     ┌──────────┐  │  │
│  │  │ Query CH    │────▶│ Aggregate   │────▶│ Calculate     │────▶│ Send to  │  │  │
│  │  │ Events      │     │ by Team     │     │ Billable      │     │ Billing  │  │  │
│  │  └─────────────┘     └─────────────┘     └───────────────┘     └──────────┘  │  │
│  └──────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

## Step 1: Redis counter increment (Rust service)

When a feature flag request is processed, the Rust service increments Redis counters to track usage.

**Source files:**

- `rust/feature-flags/src/flags/flag_analytics.rs` - Counter increment logic
- `rust/feature-flags/src/handler/billing.rs` - Billable flag detection

### Redis key structure

The service stores counts in Redis hashes using time-bucketed fields:

| Request Type     | Team Key                                      | SDK Key                                                      |
| ---------------- | --------------------------------------------- | ------------------------------------------------------------ |
| `/decide`        | `posthog:decide_requests:{team_id}`           | `posthog:decide_requests:sdk:{team_id}:{sdk_name}`           |
| Local evaluation | `posthog:local_evaluation_requests:{team_id}` | `posthog:local_evaluation_requests:sdk:{team_id}:{sdk_name}` |

### Time bucketing

Counts are grouped into 2-minute (120-second) time buckets:

```rust
const CACHE_BUCKET_SIZE: u64 = 60 * 2; // 120 seconds

let time_bucket = SystemTime::now()
    .duration_since(UNIX_EPOCH)
    .unwrap()
    .as_secs()
    / CACHE_BUCKET_SIZE;
```

Each hash field is the time bucket number (Unix seconds / 120), and the value is the count for that bucket.

### Billable flag detection

Not all flag evaluations are billable. The following flags are excluded:

- **Survey targeting flags**: Keys starting with `survey-targeting-`
- **Product tour targeting flags**: Keys starting with `product-tour-targeting-`
- **Inactive flags**: Flags where `active = false`

A request is only counted for billing if it contains at least one active, non-survey, non-product-tour flag.

### SDK tracking

The service extracts the SDK type from the request's user-agent header and increments a separate SDK-specific counter. Supported SDKs:

| SDK Name               | Description             |
| ---------------------- | ----------------------- |
| `posthog-js`           | Web browsers            |
| `posthog-node`         | Server-side Node.js     |
| `posthog-python`       | Python SDK              |
| `posthog-php`          | PHP SDK                 |
| `posthog-ruby`         | Ruby SDK                |
| `posthog-go`           | Go SDK                  |
| `posthog-java`         | Java SDK                |
| `posthog-dotnet`       | .NET SDK                |
| `posthog-elixir`       | Elixir SDK              |
| `posthog-android`      | Android SDK             |
| `posthog-ios`          | iOS SDK                 |
| `posthog-react-native` | React Native SDK        |
| `posthog-flutter`      | Flutter SDK             |
| `other`                | Unknown or unrecognized |

### Redis pipelining

Both the team-level and SDK-level counters are incremented in a single Redis round-trip using pipelining:

```rust
let mut commands = vec![PipelineCommand::HIncrBy {
    key: team_key,
    field: time_bucket_str.clone(),
    count,
}];

if let Some(lib) = library {
    commands.push(PipelineCommand::HIncrBy {
        key: library_key,
        field: time_bucket_str,
        count,
    });
}

redis_client.execute_pipeline(commands).await?;
```

## Step 2: Scheduled aggregation task

A Celery task aggregates Redis counters and emits PostHog events every 30 minutes.

**Source files:**

- `posthog/models/feature_flag/flag_analytics.py` - Aggregation logic
- `posthog/tasks/tasks.py` - Task definition (`calculate_decide_usage`)
- `posthog/tasks/scheduled.py` - Schedule configuration

### Task schedule

```python
# posthog/tasks/scheduled.py
sender.add_periodic_task(
    crontab(minute="*/30"),
    calculate_decide_usage.s(),
    name="calculate decide usage",
)
```

### Aggregation process

For each team (excluding internal metrics and demo teams):

1. **Acquire distributed lock**: `posthog:decide_analytics:lock:{team_id}` with 60-second timeout
2. **Extract counters**: Read all time buckets except the current one (still being filled)
3. **Extract SDK breakdown**: Read all SDK-specific counters using pipelining
4. **Consume buckets**: Delete processed buckets from Redis
5. **Emit events**: Send `decide usage` and `local evaluation usage` events to PostHog

The "skip current bucket" behavior prevents counting requests that are still being recorded:

```python
# The latest bucket is still being filled, so we don't want to delete it nor count it.
# It will be counted in a later iteration, when it's not being filled anymore.
if time_buckets and len(time_buckets) > 1:
    for time_bucket in sorted(time_buckets, key=lambda bucket: int(bucket))[:-1]:
        # Process and delete this bucket
```

## Step 3: Event emission

The aggregation task emits events to PostHog's internal analytics instance.

### Event types

| Event Name               | Description                                    |
| ------------------------ | ---------------------------------------------- |
| `decide usage`           | Counts from `/decide` endpoint requests        |
| `local evaluation usage` | Counts from local evaluation endpoint requests |

### Event properties

```json
{
  "count": 1234,
  "team_id": 42,
  "team_uuid": "0189abcd-1234-5678-9abc-def012345678",
  "min_time": 1705000000,
  "max_time": 1705001800,
  "token": "<billing_token>",
  "sdk_breakdown": {
    "posthog-js": 800,
    "posthog-python": 300,
    "posthog-node": 134
  }
}
```

- **count**: Total number of requests in this aggregation period
- **team_id/team_uuid**: Team identifiers
- **min_time/max_time**: Unix timestamps of the earliest and latest buckets processed
- **token**: Billing validation token (`DECIDE_BILLING_ANALYTICS_TOKEN`)
- **sdk_breakdown**: Optional object mapping SDK names to request counts

### Storage location

Events are stored in ClickHouse under a specific team based on region:

- **EU region**: team_id = 1
- **Other regions**: team_id = 2

## Step 4: Usage report generation

The usage report task queries ClickHouse for aggregated billing data.

**Source file:** `posthog/tasks/usage_report.py`

### Billable calculation

Local evaluation requests are weighted 10x compared to decide requests:

```python
billable_feature_flag_requests_count_in_period = (
    decide_requests_count_in_period
    + (local_evaluation_requests_count_in_period * 10)
)
```

This reflects the higher resource cost of local evaluation requests, which return full flag definitions rather than just evaluation results.

### Token validation

Queries filter events by the billing token to ensure only legitimate usage events are counted:

```sql
AND has([%(validity_token)s], replaceRegexpAll(JSONExtractRaw(properties, 'token'), '^"|"$', ''))
```

## Key design decisions

| Decision                         | Rationale                                                                          |
| -------------------------------- | ---------------------------------------------------------------------------------- |
| 2-minute time buckets            | Balance between granularity and Redis memory usage                                 |
| Skip current bucket              | Avoid counting in-flight requests that may still be incrementing                   |
| Distributed lock                 | Prevent concurrent processing of the same team's data                              |
| Redis pipelining                 | Minimize network round-trips for better performance                                |
| 10x local evaluation weight      | Local evaluation returns full flag definitions, requiring more server resources    |
| Selective billing                | Survey and product tour flags are internal features, not customer-billable         |
| SDK breakdown for analytics only | Billing charges per request regardless of SDK; breakdown is for internal analytics |

## Billing service processing

The usage report is sent daily to the billing service (`billing.posthog.com`), which:

1. **Extracts** `billable_feature_flag_requests_count_in_period` from the report
2. **Stores** it as `feature_flag_requests` in the `UsageReport` model
3. **Aggregates** daily values across the billing period
4. **Reports to Stripe** via `stripe.SubscriptionItem.create_usage_record()`
5. **Triggers** usage limit emails (80%, 100% thresholds) and spike detection

The SDK breakdown (`sdk_breakdown` property) is stored in the events but not used by billing. Customers are charged per request regardless of which SDK made the request.

## Debugging

### Check Redis counters

```bash
# View current counters for a team
redis-cli HGETALL "posthog:decide_requests:123"
redis-cli HGETALL "posthog:decide_requests:sdk:123:posthog-js"

# View all SDK keys for a team
redis-cli KEYS "posthog:decide_requests:sdk:123:*"
```

### Query usage events

```sql
SELECT
    distinct_id as team_id,
    JSONExtractInt(properties, 'count') as count,
    JSONExtractString(properties, 'sdk_breakdown') as sdk_breakdown,
    timestamp
FROM events
WHERE event = 'decide usage'
  AND team_id = 1  -- or 2 for non-EU
  AND timestamp > now() - INTERVAL 1 DAY
ORDER BY timestamp DESC
LIMIT 100
```

### Force aggregation for a team

```python
from posthog.models.feature_flag.flag_analytics import capture_team_decide_usage
from posthoganalytics import Posthog

ph_client = Posthog(project_api_key='...', host='...')
capture_team_decide_usage(ph_client, team_id=123, team_uuid='...')
```
