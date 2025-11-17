# LLMA Acceptance Test Implementation Plan

## Overview

Python-based acceptance tests for the LLM Analytics capture pipeline, testing against an existing PostHog instance.

## Test Execution

### Local Development

- User starts PostHog stack manually (using docker-compose or other method)
- Set POSTHOG_TEST_BASE_URL environment variable to PostHog instance URL
- Run acceptance tests: `python run_tests.py`

### GitHub Actions

- Triggered on PRs affecting rust/capture/ or plugin-server/
- Sets up PostHog stack in CI
- Runs acceptance tests against the stack
- Collects logs on failure

## Implementation Steps

### Commit 1: Basic acceptance test infrastructure ✓

1. Create common/ingestion/acceptance_tests/ directory structure
2. Add utils.py for service URL management
3. Add requirements.txt with test dependencies
4. Add run_tests.py test runner script

### Commit 2: PostHog API client for test setup

1. Add api_client.py with PostHogTestClient class
2. Implement organization creation via API
3. Implement project creation with API key retrieval
4. Add project deletion for cleanup
5. Add event querying through PostHog Query API
6. Implement polling mechanism for event arrival

### Commit 3: Basic event capture test

1. Add test_basic_capture.py
2. Test sending a regular PostHog event to /capture
3. Poll Query API until event appears
4. Verify event properties match what was sent
5. Confirm end-to-end pipeline works

### Commit 4: Test orchestration

1. Add conftest.py with pytest fixtures
2. Add per-test project isolation
3. Add environment variable handling
4. Handle cleanup of test data

### Commit 5: GitHub Actions workflow

1. Add .github/workflows/llma-acceptance-tests.yml
2. Configure triggers for relevant paths
3. Add PostHog stack startup steps
4. Add test execution with pytest
5. Implement log collection on failure
6. Add cleanup steps

### Commit 6: Documentation

1. Add README.md with setup instructions
2. Document local running procedures
3. Document environment variables
4. Add troubleshooting guide
5. Create .env.example file
6. Document how to extend the test suite

## Usage

```bash
# Start PostHog manually (e.g., with docker-compose)
docker-compose -f docker-compose.dev-full.yml up -d

# Set environment variable
export POSTHOG_TEST_BASE_URL=http://localhost:8010

# Run tests
cd common/ingestion/acceptance_tests
python run_tests.py
```
