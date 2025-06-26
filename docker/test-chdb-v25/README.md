# chdb ClickHouse v25 Compatibility Test

This directory contains a **non-required** CI test that verifies chdb compatibility with ClickHouse v25 before PostHog migrates to the new version.

## What it tests

- **chdb version compatibility** with v25 features
- **Native format support** (critical for PostHog data exports)
- **PostHog warehouse patterns** (DESCRIBE, COUNT, Map queries)
- **AggregateFunction types** (uniqState, sumState, argMinState for web preaggregated data)
- **Complex aggregate patterns** (SimpleAggregateFunction, LowCardinality, DateTime64)
- **State/Merge function workflows** (how PostHog writes and reads preaggregated data)
- **Web analytics query patterns** (aggregations, time-based queries)
- **Integration with actual ClickHouse v25** (when available)

## When it runs

- **On PRs** that touch warehouse, web analytics, or chdb-related code
- **On master** pushes to affected areas
- **Weekly** on Sundays to catch version updates
- **Manually** via workflow dispatch

## PostHog components tested

- `posthog/warehouse/models/table.py` - S3 table introspection
- `posthog/hogql_queries/web_analytics/external/` - External web analytics
- `posthog/models/web_preaggregated/sql.py` - Web stats/bounces preaggregated tables
- `posthog/session_recordings/sql/` - Session replay aggregate states
- `posthog/hogql/transforms/state_aggregations.py` - State/Merge transformations
- `dags/web_preaggregated_asset_checks.py` - Export verification

## Running locally

```bash
# Build and run the test
docker build -t chdb-v25-test -f docker/test-chdb-v25/Dockerfile docker/test-chdb-v25/
docker run --rm chdb-v25-test

# Or with external ClickHouse v25 for integration testing
docker run -d --name ch25 -p 8123:8123 clickhouse/clickhouse-server:25.1.1.1
sleep 10  # Wait for startup
docker run --rm --network host -e CLICKHOUSE_HOST=localhost chdb-v25-test
docker stop ch25 && docker rm ch25
```

## Non-blocking design

This test uses `continue-on-error: true` so it won't block PRs if it fails. It's purely informational to help plan the ClickHouse v25 migration safely. 