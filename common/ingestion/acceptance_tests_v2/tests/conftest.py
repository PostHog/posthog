"""Shared fixtures for all acceptance tests."""

from collections.abc import Generator

import pytest

from ..client import PostHogClient
from ..config import Config


@pytest.fixture(scope="session")
def config() -> Config:
    """Load configuration from environment variables.

    This fixture is session-scoped, so configuration is loaded once
    and shared across all tests.
    """
    return Config()


@pytest.fixture(scope="session")
def client(config: Config) -> Generator[PostHogClient, None, None]:
    """Create a PostHog client for the test session.

    This fixture is session-scoped, so a single client instance is
    shared across all tests. Each test should use unique identifiers
    to avoid interference.
    """
    client = PostHogClient(config)
    yield client
    client.shutdown()
