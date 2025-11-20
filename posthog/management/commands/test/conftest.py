import time
import logging

import pytest

from temporalio.client import Client as TemporalClient
from temporalio.service import RPCError

from posthog.temporal.common.client import sync_connect

logger = logging.getLogger(__name__)


def sync_connect_with_retry(max_retries: int = 5, initial_delay: float = 0.5) -> TemporalClient:
    """Connect to Temporal with exponential backoff retry logic.

    This helps handle transient connection issues where Temporal might not be ready
    when tests start, preventing flaky "Not enough hosts to serve the request" errors.

    Args:
        max_retries: Maximum number of connection attempts
        initial_delay: Initial delay in seconds between retries (doubles each retry)

    Returns:
        Connected Temporal client

    Raises:
        RPCError: If connection fails after all retries
    """
    delay = initial_delay
    last_error: RPCError | None = None

    for attempt in range(max_retries):
        try:
            logger.info(f"Attempting to connect to Temporal (attempt {attempt + 1}/{max_retries})")
            client = sync_connect()
            logger.info("Successfully connected to Temporal")
            return client
        except RPCError as e:
            last_error = e
            if "Not enough hosts to serve the request" in str(e):
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Temporal connection failed (attempt {attempt + 1}/{max_retries}): {e}. "
                        f"Retrying in {delay}s..."
                    )
                    time.sleep(delay)
                    delay *= 2  # Exponential backoff
                else:
                    logger.exception(f"Failed to connect to Temporal after {max_retries} attempts")
            else:
                # If it's a different error, don't retry
                raise

    # If we get here, all retries failed and last_error must be set
    assert last_error is not None
    raise last_error


@pytest.fixture(scope="module")
def temporal():
    """Return a TemporalClient instance with retry logic.

    This fixture is module-scoped to reuse the same connection across all tests
    in a module, which is both faster and more reliable than creating a new
    connection for each test.
    """
    client = sync_connect_with_retry()
    yield client
