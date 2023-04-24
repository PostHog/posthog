import pytest
from temporalio.testing import ActivityEnvironment


@pytest.fixture
def activity_environment():
    """Return a testing temporal ActivityEnvironment."""
    return ActivityEnvironment()
