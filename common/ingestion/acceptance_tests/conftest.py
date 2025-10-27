"""Pytest fixtures for acceptance tests."""

import os
import logging

import pytest

from .api_client import PostHogTestClient

logger = logging.getLogger(__name__)


@pytest.fixture(scope="class")
def test_client():
    """Create a PostHog test client instance for each test class."""
    # Get configuration from environment
    base_url = os.environ.get("POSTHOG_TEST_BASE_URL", "http://localhost:8010")
    personal_api_key = os.environ.get("POSTHOG_PERSONAL_API_KEY")

    if not personal_api_key:
        pytest.skip("POSTHOG_PERSONAL_API_KEY not set - please set it to run acceptance tests")

    logger.info("Creating test client with base_url=%s", base_url)
    client = PostHogTestClient(base_url=base_url, personal_api_key=personal_api_key)

    yield client

    # Cleanup happens in individual tests


@pytest.fixture(scope="function")
def function_test_client():
    """Create a PostHog test client instance for each individual test (for auth tests)."""
    # Get configuration from environment
    base_url = os.environ.get("POSTHOG_TEST_BASE_URL", "http://localhost:8010")
    personal_api_key = os.environ.get("POSTHOG_PERSONAL_API_KEY")

    if not personal_api_key:
        pytest.skip("POSTHOG_PERSONAL_API_KEY not set - please set it to run acceptance tests")

    logger.info("Creating function-scoped test client with base_url=%s", base_url)
    client = PostHogTestClient(base_url=base_url, personal_api_key=personal_api_key)

    yield client


@pytest.fixture(scope="class")
def shared_org_project(test_client):
    """Create a shared organization and project for an entire test class."""
    logger.info("Creating shared organization and project for test class")

    client = test_client
    org = client.create_organization()
    project = client.create_project(org["id"])

    # Project creation now waits for readiness internally

    yield {
        "org": org,
        "project": project,
        "client": client,
        "org_id": org["id"],
        "project_id": project["id"],
        "api_key": project["api_token"],
    }

    # Cleanup after all tests in class are done
    logger.info("Cleaning up shared organization and project")
    try:
        client.delete_project(project["id"])
        logger.info("Successfully deleted project: %s", project["id"])
    except Exception as e:
        logger.warning("Failed to delete project %s: %s", project["id"], e)

    try:
        client.delete_organization(org["id"])
        logger.info("Successfully deleted organization: %s", org["id"])
    except Exception as e:
        logger.warning("Failed to delete organization %s: %s", org["id"], e)
