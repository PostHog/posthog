# PostHog API Acceptance Tests

Acceptance tests that run against PostHog APIs to verify end-to-end functionality.

## Prerequisites

- Python 3.10+
- Access to a PostHog instance
- A project with API keys

## Required Environment Variables

```bash
# PostHog API host (e.g., https://app.posthog.com or http://localhost:8000)
export POSTHOG_API_HOST="https://app.posthog.com"

# Project API key (used for capturing events)
export POSTHOG_PROJECT_API_KEY="phc_..."

# Project ID (used for querying events)
export POSTHOG_PROJECT_ID="12345"

# Personal API key (used for private API access like HogQL queries)
export POSTHOG_PERSONAL_API_KEY="phx_..."
```

### Optional Environment Variables

```bash
# Timeout for waiting for events to appear (default: 30 seconds)
export POSTHOG_EVENT_TIMEOUT_SECONDS="30"

# Interval between polling attempts (default: 2.0 seconds)
export POSTHOG_POLL_INTERVAL_SECONDS="2.0"
```

## Running Tests

### Run All Tests

```bash
cd common/ingestion/acceptance_tests_v2
pytest
```

### Run Tests in Parallel

```bash
pytest -n auto  # Requires pytest-xdist
```

### Run Specific Test Groups

```bash
# Run only capture tests
pytest tests/capture/

# Run a specific test file
pytest tests/capture/test_basic_capture.py

# Run a specific test
pytest tests/capture/test_basic_capture.py::TestBasicCapture::test_capture_event_and_query
```

### Output Results for Alerting

```bash
pytest --results-output=results.json
```

This generates a JSON file with structured results:

```json
{
  "results": [
    {
      "test_name": "test_capture_event_and_query",
      "test_file": "tests/capture/test_basic_capture.py",
      "status": "passed",
      "duration_seconds": 5.23,
      "timestamp": "2024-01-15T10:30:00Z",
      "error_message": null,
      "error_details": null
    }
  ],
  "total_duration_seconds": 5.45,
  "environment": {
    "api_host": "https://app.posthog.com",
    "project_id": "12345",
    "project_api_key": "phc_abcd...wxyz",
    "personal_api_key": "phx_abcd...wxyz"
  },
  "summary": {
    "total": 1,
    "passed": 1,
    "failed": 0,
    "errors": 0,
    "skipped": 0,
    "success": true
  }
}
```

## Adding New Tests

### Test Structure

```text
tests/
├── conftest.py          # Shared fixtures
├── capture/             # Event capture tests
│   └── test_*.py
├── query/               # Query API tests (future)
│   └── test_*.py
└── feature_flags/       # Feature flag tests (future)
    └── test_*.py
```

### Creating a New Test

1. Create a new test file in the appropriate directory:

```python
# tests/capture/test_my_feature.py

from ...client import PostHogClient
from ...config import Config


class TestMyFeature:
    def test_something(self, client: PostHogClient, config: Config) -> None:
        # Use unique identifiers to avoid collision
        import uuid
        test_id = uuid.uuid4().hex[:8]

        # Your test logic here
        pass
```

2. Run your test:

```bash
pytest tests/capture/test_my_feature.py -v
```

### Best Practices

1. **Use unique identifiers**: Always generate unique event names and distinct IDs to avoid collision with concurrent tests or existing data.

2. **Don't create resources**: Tests should not create organizations, projects, or other resources. Use the pre-configured project.

3. **Clean assertions**: Include context in assertion messages to aid debugging.

4. **Respect timeouts**: Use `config.event_timeout_seconds` for consistency.

## Alerting Integration

The `--results-output` flag generates a JSON file suitable for alerting systems:

```bash
pytest --results-output=results.json
```

### CI Integration

Example CI integration with JSON output:

```yaml
- name: Run acceptance tests
  run: pytest --results-output=results.json
  continue-on-error: true

- name: Check results and alert
  run: |
    if jq -e '.summary.success == false' results.json > /dev/null; then
      # Send alert (implement your alerting logic here)
      echo "Tests failed!"
      exit 1
    fi
```

## Troubleshooting

### "Missing required environment variables"

Ensure all required environment variables are set. Check with:

```bash
env | grep POSTHOG
```

### "Event not found within timeout"

- Increase `POSTHOG_EVENT_TIMEOUT_SECONDS`
- Check that the PostHog instance is processing events
- Verify the project API key matches the project ID

### "401 Unauthorized"

- Verify `POSTHOG_PERSONAL_API_KEY` is valid
- Check that the key has access to the specified project
