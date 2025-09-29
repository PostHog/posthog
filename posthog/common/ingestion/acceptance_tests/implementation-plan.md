# LLMA Acceptance Test Implementation Plan

## Overview

Python-based acceptance tests for the LLM Analytics capture pipeline, testing the full PostHog stack end-to-end.

## Test Execution

### Local Development
- Run from repository root
- Start PostHog stack using docker-compose.dev-full.yml
- Execute pytest from llma_acceptance_tests directory
- Tests automatically detect running services

### GitHub Actions
- Triggered on PRs affecting rust/capture/ or plugin-server/
- Starts fresh PostHog stack
- Runs all acceptance tests
- Collects logs on failure
- Cleans up resources

## Implementation Steps

### Commit 1: Basic acceptance test infrastructure
1. Create posthog/llma_acceptance_tests/ directory structure
2. Add docker_utils.py for Docker Compose management
3. Add requirements.txt with test dependencies
4. Implement service health checking logic
5. Add utilities for starting/stopping PostHog stack

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

### Commit 4: Test orchestration and CI integration
1. Add conftest.py with pytest fixtures
2. Implement session-scoped PostHog stack management
3. Add per-test project isolation
4. Add environment detection for local vs CI
5. Handle cleanup based on environment

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