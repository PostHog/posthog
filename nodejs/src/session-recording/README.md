# Session Recording Ingestion

This module handles ingestion of session recording data, processing it, and storing it for later playback.

## Overview

The `SessionRecordingIngester` consumes session recording events from Kafka and:

- **Validates and filters** messages (team checks, rate limiting, restrictions)
- **Batches events** by session for efficient storage
- **Writes session data** to object storage (S3) as compressed blocks
- **Publishes metadata** to ClickHouse for querying and playback
- **Extracts console logs** for separate storage and search
- **Handles failures** via dead letter queue and overflow topics

## Local Development

### Prerequisites

- Docker (for local infrastructure)
- Python environment (for Django migrations)

### Setup

1. Start the required services (Kafka, MinIO, Postgres, Redis, ClickHouse):

   ```bash
   hogli dev:setup
   ```

   Or manually:

   ```bash
   docker compose -f docker-compose.dev.yml up
   ```

2. Set up the test database (creates test_posthog DB and runs migrations):

   ```bash
   pnpm setup:test
   ```

## Testing

### Running E2E Tests

```bash
pnpm jest src/session-recording/consumer.e2e.test.ts
```

Tests will fail if required infrastructure is not available, with a message indicating which services are missing.

To skip E2E tests when running the full suite:

```bash
pnpm jest --testPathIgnorePatterns=e2e
```

### Test Coverage

The E2E tests validate the full pipeline by:

- Producing test messages to the input Kafka topic
- Verifying data is correctly written to S3
- Verifying metadata is correctly aggregated in ClickHouse
- Using snapshot testing to capture and verify behavior

### Adding New Test Cases

1. Add a new entry to the `testCases` array in `consumer.e2e.test.ts`:
   - `name`: Short identifier used in the snapshot name
   - `description`: What the test verifies
   - `createPayloads`: Function returning `PayloadConfig[]` with test data
   - `expectedOutcome`: `'written'` (data should appear in S3) or `'dropped'` (rejected)

2. Run tests with the update flag to generate the new snapshot:

   ```bash
   pnpm jest src/session-recording/consumer.e2e.test.ts -u
   ```

3. Review the generated snapshot in `__snapshots__/` to ensure it captures expected behavior.

### Updating Snapshots

If refactoring changes the output format (but behavior is correct), update snapshots:

```bash
pnpm jest src/session-recording/consumer.e2e.test.ts -u
```

Always review snapshot diffs carefully - they should reflect intentional changes only.
