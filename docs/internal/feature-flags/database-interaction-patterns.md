# Database Interaction Patterns

This document explains how the Rust feature flags service interacts with PostgreSQL, including connection pooling, query routing, error handling, and observability.

## Architecture overview

The service uses a four-pool architecture to separate concerns and optimize for different access patterns:

```text
┌─────────────────────────────────────────────────────────────────┐
│                      PostgresRouter                             │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐                       │
│  │ persons_reader  │  │ persons_writer  │  ← Persons database   │
│  └─────────────────┘  └─────────────────┘    (optional)         │
│  ┌─────────────────┐  ┌─────────────────┐                       │
│  │ non_persons_    │  │ non_persons_    │  ← Main database      │
│  │ reader          │  │ writer          │                       │
│  └─────────────────┘  └─────────────────┘                       │
└─────────────────────────────────────────────────────────────────┘
```

When the persons database is not configured separately, the persons pools alias to the non-persons pools, effectively creating a two-pool architecture.

## Connection pooling

### Pool configuration

The service uses SQLx's `PgPool` with configurable parameters per pool:

```rust
pub struct PoolConfig {
    pub min_connections: u32,        // Minimum idle connections to maintain
    pub max_connections: u32,        // Maximum connections in the pool
    pub acquire_timeout: Duration,   // Timeout for acquiring a connection
    pub idle_timeout: Option<Duration>, // Close idle connections after this duration
    pub test_before_acquire: bool,   // Validate connection health before use
    pub statement_timeout_ms: Option<u64>, // PostgreSQL statement_timeout per connection
}
```

### Default values

| Parameter              | Library default | Service default | Purpose                                    |
| ---------------------- | --------------- | --------------- | ------------------------------------------ |
| `min_connections`      | 0               | 0 per pool      | Start with no connections, scale on demand |
| `max_connections`      | 10              | 10              | Maximum connections per pool               |
| `acquire_timeout`      | 10s             | 3s (test)       | Wait time for connection from pool         |
| `idle_timeout`         | 300s (5 min)    | 300s            | Close unused connections                   |
| `test_before_acquire`  | true            | true            | Validate connection before use             |
| `statement_timeout_ms` | None            | 5000ms          | Cancel queries exceeding this duration     |

### Per-pool statement timeouts

Different pools can have different statement timeouts to match their workload:

| Pool                 | Config key                                | Typical use                       |
| -------------------- | ----------------------------------------- | --------------------------------- |
| `non_persons_reader` | `NON_PERSONS_READER_STATEMENT_TIMEOUT_MS` | Flag definitions, team data       |
| `persons_reader`     | `PERSONS_READER_STATEMENT_TIMEOUT_MS`     | Person lookups, cohort membership |
| `persons_writer`     | `WRITER_STATEMENT_TIMEOUT_MS`             | Hash key override writes          |
| `non_persons_writer` | `WRITER_STATEMENT_TIMEOUT_MS`             | Same as persons_writer            |

Statement timeouts are set via `SET statement_timeout = {ms}` on each new connection using SQLx's `after_connect` hook.

### Total connection count

```text
With persons DB routing enabled:  4 pools × max_connections
With persons DB routing disabled: 2 pools × max_connections (pools are aliased)
```

For production with `max_connections=10`:

- **Routing enabled**: 40 connections max per service instance
- **Routing disabled**: 20 connections max per service instance

## Query routing

The `PostgresRouter` routes queries to the appropriate pool based on the table being accessed:

```rust
pub struct PostgresRouter {
    pub persons_reader: PostgresReader,
    pub persons_writer: PostgresWriter,
    pub non_persons_reader: PostgresReader,
    pub non_persons_writer: PostgresWriter,
}
```

### Routing rules

| Tables                                                                              | Pool            |
| ----------------------------------------------------------------------------------- | --------------- |
| `posthog_person`, `posthog_persondistinctid`, `posthog_featureflaghashkeyoverride`  | `persons_*`     |
| `posthog_featureflag`, `posthog_team`, `posthog_grouptypemapping`, `posthog_cohort` | `non_persons_*` |

### Usage pattern

```rust
// Read person data - always include team_id for partition efficiency
let mut conn = router.get_persons_reader().get_connection().await?;
let person = sqlx::query(
    "SELECT * FROM posthog_person WHERE team_id = $1 AND id = $2"
)
    .bind(team_id)
    .bind(person_id)
    .fetch_optional(&mut *conn)
    .await?;

// Read flag definitions
let mut conn = router.get_non_persons_reader().get_connection().await?;
let flags = sqlx::query("SELECT * FROM posthog_featureflag WHERE team_id = $1")
    .bind(team_id)
    .fetch_all(&mut *conn)
    .await?;
```

**Important**: Always include `team_id` in queries against persons tables. These tables are partitioned by `team_id`, and queries without it will scan all partitions instead of targeting the correct one via the index.

## Error handling

### Transient error detection

The `common_database` crate provides error classification for retry logic:

```rust
pub fn is_transient_error(error: &SqlxError) -> bool
```

Transient errors (suitable for retry):

| SQLSTATE class | Meaning                                             |
| -------------- | --------------------------------------------------- |
| `08***`        | Connection exception                                |
| `53***`        | Insufficient resources                              |
| `57***`        | Operator intervention (includes query cancellation) |
| `58***`        | System error                                        |
| `40001`        | Serialization failure                               |
| `40003`        | Statement completion unknown                        |
| `40P01`        | Deadlock detected                                   |

Non-transient errors (fail immediately):

| SQLSTATE class | Meaning                          |
| -------------- | -------------------------------- |
| `23***`        | Integrity constraint violation   |
| `42***`        | Syntax error or access violation |
| `22***`        | Data exception                   |

### Timeout detection

```rust
pub fn is_timeout_error(error: &SqlxError) -> bool
pub fn extract_timeout_type(error: &SqlxError) -> Option<&'static str>
```

Timeout types detected:

| Type                          | Source                             |
| ----------------------------- | ---------------------------------- |
| `pool_timeout`                | Pool acquisition timed out         |
| `io_timeout`                  | Network/socket timeout             |
| `protocol_timeout`            | Protocol-level timeout             |
| `query_canceled`              | SQLSTATE 57014 (statement_timeout) |
| `lock_not_available`          | SQLSTATE 55P03 (lock_timeout)      |
| `idle_in_transaction_timeout` | SQLSTATE 25P03                     |

### Foreign key constraint detection

```rust
pub fn is_foreign_key_constraint_error(error: &SqlxError) -> bool
```

Used for retrying hash key override writes when a person is deleted during the operation (race condition).

## Retry strategies

The service uses the `tokio-retry` crate with exponential backoff:

### Read operations

```rust
let retry_strategy = ExponentialBackoff::from_millis(50)
    .max_delay(Duration::from_millis(300))
    .take(3)  // 3 attempts total
    .map(jitter);
```

- **Initial delay**: 50ms
- **Max delay**: 300ms
- **Max attempts**: 3
- **Retry on**: Transient errors only

### Write operations

```rust
let retry_strategy = ExponentialBackoff::from_millis(100)
    .max_delay(Duration::from_millis(300))
    .take(2)  // 2 attempts for writes
    .map(jitter);
```

- **Initial delay**: 100ms (slower to avoid overwhelming)
- **Max delay**: 300ms
- **Max attempts**: 2 (more conservative)
- **Retry on**: Foreign key constraint errors (person deletion race)

## Observability

### Prometheus metrics

| Metric                              | Labels                 | Purpose                        |
| ----------------------------------- | ---------------------- | ------------------------------ |
| `flags_db_connection_time`          | `pool`, `operation`    | Connection acquisition latency |
| `flags_person_query_time`           | -                      | Person lookup query duration   |
| `flags_definition_query_time`       | -                      | Flag definition query duration |
| `flags_pool_utilization_ratio`      | `pool`                 | Pool utilization (0.0-1.0)     |
| `flags_connection_hold_time_ms`     | `pool`, `operation`    | How long connections are held  |
| `flags_hash_key_retries_total`      | `team_id`, `operation` | Retry counter                  |
| `flags_flag_evaluation_error_total` | `error_type`           | Error counter                  |

### Pool stats

Each pool exposes stats via `get_pool_stats()`:

```rust
pub struct PoolStats {
    pub size: u32,      // Current number of connections
    pub num_idle: usize, // Connections not currently in use
}
```

Utilization is calculated as: `(size - num_idle) / size`

### Slow query warnings

Queries exceeding 500ms are logged at WARN level with timing information.

## Configuration reference

### Environment variables

| Variable                                  | Default      | Purpose                                         |
| ----------------------------------------- | ------------ | ----------------------------------------------- |
| `READ_DATABASE_URL`                       | required     | Main database read replica URL                  |
| `WRITE_DATABASE_URL`                      | required     | Main database primary URL                       |
| `PERSONS_READ_DATABASE_URL`               | empty        | Persons database read replica (enables routing) |
| `PERSONS_WRITE_DATABASE_URL`              | empty        | Persons database primary (enables routing)      |
| `MAX_PG_CONNECTIONS`                      | 10           | Max connections per pool                        |
| `MIN_NON_PERSONS_READER_CONNECTIONS`      | 0            | Min idle connections for non-persons reader     |
| `MIN_NON_PERSONS_WRITER_CONNECTIONS`      | 0            | Min idle connections for non-persons writer     |
| `MIN_PERSONS_READER_CONNECTIONS`          | 0            | Min idle connections for persons reader         |
| `MIN_PERSONS_WRITER_CONNECTIONS`          | 0            | Min idle connections for persons writer         |
| `ACQUIRE_TIMEOUT_SECS`                    | 10           | Connection acquisition timeout                  |
| `IDLE_TIMEOUT_SECS`                       | 300          | Idle connection timeout                         |
| `TEST_BEFORE_ACQUIRE`                     | true         | Validate connections before use                 |
| `NON_PERSONS_READER_STATEMENT_TIMEOUT_MS` | 0 (disabled) | Statement timeout for non-persons reads         |
| `PERSONS_READER_STATEMENT_TIMEOUT_MS`     | 0 (disabled) | Statement timeout for persons reads             |
| `WRITER_STATEMENT_TIMEOUT_MS`             | 0 (disabled) | Statement timeout for writes                    |

### Tuning guidance

**High traffic deployment**:

```bash
MAX_PG_CONNECTIONS=25  # Increase pool size
MIN_NON_PERSONS_READER_CONNECTIONS=5  # Keep connections warm
MIN_PERSONS_READER_CONNECTIONS=5
```

**Bursty traffic**:

```bash
IDLE_TIMEOUT_SECS=600  # Keep connections warm longer
MIN_NON_PERSONS_READER_CONNECTIONS=3  # Pre-warm some connections
```

**Strict timeout enforcement**:

```bash
NON_PERSONS_READER_STATEMENT_TIMEOUT_MS=5000  # 5s for reads
PERSONS_READER_STATEMENT_TIMEOUT_MS=5000
WRITER_STATEMENT_TIMEOUT_MS=2000  # 2s for writes (should be fast)
```

## Related files

| File                                                  | Purpose                                  |
| ----------------------------------------------------- | ---------------------------------------- |
| `rust/common/database/src/lib.rs`                     | Pool configuration, error classification |
| `rust/feature-flags/src/database_pools.rs`            | Four-pool architecture                   |
| `rust/feature-flags/src/database/postgres_router.rs`  | Query routing                            |
| `rust/feature-flags/src/config.rs`                    | Environment configuration                |
| `rust/feature-flags/src/flags/flag_matching_utils.rs` | Query patterns, retry logic              |
| `rust/feature-flags/src/metrics/consts.rs`            | Metric constants                         |
