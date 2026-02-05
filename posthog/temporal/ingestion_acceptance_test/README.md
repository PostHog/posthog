# Ingestion Acceptance Tests

End-to-end tests that verify the PostHog ingestion pipeline is functioning correctly. These tests capture real events via the PostHog SDK and query them back via the HogQL API to ensure the full pipeline works as expected.

## Goal

Detect ingestion pipeline issues in production before users notice them. The tests run every 10 minutes via a Temporal scheduled workflow and send Slack notifications when failures occur.

## Architecture

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Temporal Workflow                                 │
│  (ingestion-acceptance-test, runs every 10 min)                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Activity                                       │
│  run_ingestion_acceptance_tests()                                           │
│    1. Load config from environment                                          │
│    2. Discover tests                                                        │
│    3. Run tests in parallel                                                 │
│    4. Send Slack notification (failures only)                               │
│    5. Return results                                                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
           ┌──────────────┐                ┌──────────────┐
           │ PostHog SDK  │                │  HogQL API   │
           │  (capture)   │                │   (query)    │
           └──────────────┘                └──────────────┘
                    │                               │
                    └───────────────┬───────────────┘
                                    ▼
                          ┌───────────────────┐
                          │ Ingestion Pipeline│
                          │  (Kafka, CH, etc) │
                          └───────────────────┘
```

## Test Discovery

Tests are discovered automatically by scanning for files matching `tests/acceptance_test_*.py`. Within each file:

1. Classes starting with `Test` that inherit from `AcceptanceTest` are found
2. Methods starting with `test_` within those classes are collected

**Example test structure:**

```python
# tests/acceptance_test_example.py
from ..runner import AcceptanceTest

class TestExample(AcceptanceTest):
    def test_something(self) -> None:
        event_uuid = self.client.capture_event("$test_event", "user-123")
        found = self.client.query_event_by_uuid(event_uuid)
        self.assert_event(found, event_uuid, "$test_event", "user-123")
```

## Writing New Tests

1. Create a file in `tests/` named `acceptance_test_<feature>.py`
2. Create a class starting with `Test` that inherits from `AcceptanceTest`
3. Add methods starting with `test_` for each test case
4. Use `self.client` for PostHog operations and `self.config` for configuration

**Available client methods:**

- `capture_event(name, distinct_id, properties)` - Send an event
- `alias(alias, distinct_id)` - Create an alias
- `merge_dangerously(into_id, from_id)` - Merge two persons
- `query_event_by_uuid(uuid)` - Poll for an event by UUID
- `query_person_by_distinct_id(distinct_id)` - Poll for a person
- `query_events_by_person_id(person_id, expected_count)` - Poll for events by person

**Available assertion methods:**

- `assert_event(event, uuid, name, distinct_id)` - Verify event fields
- `assert_properties_contain(actual, expected)` - Verify properties subset

## Configuration

All configuration is loaded from environment variables with the `INGESTION_ACCEPTANCE_TEST_` prefix:

| Variable                | Required | Default | Description                                       |
| ----------------------- | -------- | ------- | ------------------------------------------------- |
| `API_HOST`              | Yes      | -       | PostHog API host (e.g., `https://us.posthog.com`) |
| `PROJECT_API_KEY`       | Yes      | -       | Project API key for capturing events              |
| `PROJECT_ID`            | Yes      | -       | Project ID for querying events                    |
| `PERSONAL_API_KEY`      | Yes      | -       | Personal API key for HogQL queries                |
| `EVENT_TIMEOUT_SECONDS` | No       | 90      | Max time to wait for events to appear             |
| `POLL_INTERVAL_SECONDS` | No       | 10.0    | Interval between query attempts                   |
| `SLACK_WEBHOOK_URL`     | No       | -       | Slack incoming webhook for failure notifications  |

## Running Locally

```bash
# Set required environment variables
export INGESTION_ACCEPTANCE_TEST_API_HOST="https://us.posthog.com"
export INGESTION_ACCEPTANCE_TEST_PROJECT_API_KEY="phc_xxx"
export INGESTION_ACCEPTANCE_TEST_PROJECT_ID="12345"
export INGESTION_ACCEPTANCE_TEST_PERSONAL_API_KEY="phx_xxx"

# Run directly
python -m posthog.temporal.ingestion_acceptance_test
```

## File Structure

```text
ingestion_acceptance_test/
├── __init__.py
├── __main__.py              # CLI entry point for local runs
├── activities.py            # Temporal activity definition
├── client.py                # PostHog SDK wrapper with HTTP retry and HogQL queries
├── config.py                # Pydantic settings for environment config
├── results.py               # Test result dataclasses
├── runner.py                # Test execution engine
├── schedule.py              # Temporal schedule (every 10 min)
├── slack.py                 # Slack notification on failures
├── terminal_report.py       # Terminal output formatting
├── test_cases_discovery.py  # Auto-discovery of test files
├── workflows.py             # Temporal workflow definition
└── tests/
    ├── __init__.py
    ├── acceptance_test_alias.py
    ├── acceptance_test_basic_capture.py
    ├── acceptance_test_event_person_properties_capture.py
    └── acceptance_test_merge.py
```

Unit tests are located at `posthog/temporal/tests/ingestion_acceptance_test/`.

## HTTP Resilience

The client includes automatic retry for transient HTTP failures:

- **Timeout:** 30 seconds per request
- **Retries:** 3 attempts with exponential backoff
- **Retry on:** 500, 502, 503, 504 (server errors)
- **Retry on:** Connection errors and read timeouts
- **No retry on:** 429 (rate limiting) - retrying immediately won't help

## ClickHouse Query Optimization

Event queries include a timestamp filter (`timestamp >= test_start_date - 1 day`) to benefit from ClickHouse's table partitioning and ordering, ensuring fast query performance even on large tables.

## Notifications

Slack notifications are sent only when tests fail or error. Successful runs are silent to avoid noise. The notification includes:

- Pass/fail/error counts
- Failed test names with error messages
- Environment info (API host, project ID, duration)
