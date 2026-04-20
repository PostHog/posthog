"""pytest configuration for video segment clustering tests."""

# Import fixtures from temporal tests conftest
from posthog.temporal.tests.conftest import aorganization, ateam

__all__ = [
    "aorganization",
    "ateam",
]
