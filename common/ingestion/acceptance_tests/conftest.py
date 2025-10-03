"""Pytest fixtures for acceptance tests."""

import os
import logging

import pytest

from api_client import PostHogTestClient

logger = logging.getLogger(__name__)


@pytest.fixture(scope="function")
def test_client():
    """Create a PostHog test client instance for each test."""
    # Get configuration from environment
    base_url = os.environ.get("POSTHOG_TEST_BASE_URL", "http://localhost:8010")
    personal_api_key = os.environ.get("POSTHOG_PERSONAL_API_KEY")

    if not personal_api_key:
        pytest.skip("POSTHOG_PERSONAL_API_KEY not set - please set it to run acceptance tests")

    logger.info("Creating test client with base_url=%s", base_url)
    client = PostHogTestClient(base_url=base_url, personal_api_key=personal_api_key)

    yield client

    # Cleanup happens in individual tests
