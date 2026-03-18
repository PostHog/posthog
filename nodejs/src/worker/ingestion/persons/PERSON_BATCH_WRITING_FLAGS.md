# Person batch writing configuration flags

This document describes the configuration flags that control person batch writing behavior during the transition period.

## Flag matrix

| Flag                                                       | Type                              | Default       | Description                                 |
| ---------------------------------------------------------- | --------------------------------- | ------------- | ------------------------------------------- |
| `PERSON_BATCH_WRITING_DB_WRITE_MODE`                       | `'NO_ASSERT' \| 'ASSERT_VERSION'` | `'NO_ASSERT'` | Controls concurrency handling strategy      |
| `PERSON_BATCH_WRITING_USE_BATCH_UPDATES`                   | `boolean`                         | `true`        | Use batch SQL queries vs individual queries |
| `PERSON_BATCH_WRITING_OPTIMISTIC_UPDATES_ENABLED`          | `boolean`                         | `false`       | Enable optimistic locking with retries      |
| `PERSON_BATCH_WRITING_MAX_CONCURRENT_UPDATES`              | `number`                          | `10`          | Max concurrent individual update queries    |
| `PERSON_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES`       | `number`                          | `5`           | Max retries for optimistic update conflicts |
| `PERSON_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS` | `number`                          | `50`          | Delay between retry attempts (ms)           |

## Mode combinations

### `NO_ASSERT` mode (default)

Writes the latest in-memory value to the database without version checks.

| `USE_BATCH_UPDATES` | Behavior                                                                                     |
| ------------------- | -------------------------------------------------------------------------------------------- |
| `true` (default)    | Single batch SQL query for all updates. Falls back to individual queries on partial failure. |
| `false`             | Individual queries per person, with merge retry logic.                                       |

### `ASSERT_VERSION` mode

Asserts the database version matches the in-memory version before writing. Enables optimistic concurrency control.

| `USE_BATCH_UPDATES` | Behavior                                                  |
| ------------------- | --------------------------------------------------------- |
| `true`              | **Not supported** - falls through to individual queries   |
| `false`             | Individual queries with version assertion and retry logic |

## Dependency constraints

```text
ASSERT_VERSION mode
    └── Requires: USE_BATCH_UPDATES = false (batching not compatible with version assertions)
    └── Uses: MAX_OPTIMISTIC_UPDATE_RETRIES for conflict resolution

USE_BATCH_UPDATES = true
    └── Only works with: NO_ASSERT mode
    └── Fallback: Individual queries on batch partial failure
```

## Flush code paths

```text
flush()
├── NO_ASSERT + USE_BATCH_UPDATES=true  → flushBatchNoAssert()
│   └── On partial failure             → individual fallback with withMergeRetry()
├── NO_ASSERT + USE_BATCH_UPDATES=false → flushIndividualNoAssert()
│   └── Each update                    → withMergeRetry(updatePersonNoAssert)
└── ASSERT_VERSION                      → flushIndividualAssertVersion()
    └── Each update                    → withOptimisticRetry(updatePersonAssertVersion)
```

## Rollout strategy

1. **Current state**: `NO_ASSERT` + `USE_BATCH_UPDATES=true` (batch writes, no version checks)
2. **Transition**: Can disable batching with `USE_BATCH_UPDATES=false` to test individual writes
