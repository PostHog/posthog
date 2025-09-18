"""
Simple time freezing for Playwright tests.

When the START_PLAYWRIGHT environment variable is set (which is standard
for Playwright test runs), this freezes Django backend time to match
the frontend frozen time.
"""

import os
import datetime as dt
from typing import Optional

import freezegun

import structlog

logger = structlog.get_logger(__name__)

# Fixed frozen time for all Playwright tests: November 8, 2024 at 12:00:00 UTC
PLAYWRIGHT_FROZEN_TIME = "2024-11-08T12:00:00Z"


def is_playwright_test() -> bool:
    """Check if we're running in a Playwright test environment."""
    return bool(os.getenv("PLAYWRIGHT_FROZEN_TIME"))


def get_frozen_datetime() -> Optional[dt.datetime]:
    """Get the frozen datetime if in Playwright test mode."""
    frozen_time = os.getenv("PLAYWRIGHT_FROZEN_TIME")
    if frozen_time:
        return dt.datetime.fromisoformat(frozen_time.replace("Z", "+00:00"))
    return None


# Global freezer instance for Playwright tests
_global_freezer = None


def setup_playwright_time_freeze():
    """Setup global time freezing for Playwright tests if environment variable is set."""
    global _global_freezer

    frozen_time = os.getenv("PLAYWRIGHT_FROZEN_TIME")
    if frozen_time and _global_freezer is None:
        # Ignore pendulum and other libraries that have compatibility issues
        _global_freezer = freezegun.freeze_time(frozen_time, ignore=["pendulum", "dlt", "asyncio", "threading"])
        _global_freezer.start()
        logger.info("playwright_time_freeze_enabled", frozen_time=frozen_time)


def teardown_playwright_time_freeze():
    """Teardown global time freezing."""
    global _global_freezer

    if _global_freezer:
        _global_freezer.stop()
        _global_freezer = None
