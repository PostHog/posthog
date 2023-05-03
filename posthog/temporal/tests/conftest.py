import pytest
from temporalio.testing import ActivityEnvironment

from posthog.models import Organization, Team


@pytest.fixture
def organization():
    """A test organization."""
    org = Organization.objects.create(name="TempHog")
    org.save()

    yield org

    org.delete()


@pytest.fixture
def team(organization):
    """A test team."""
    team = Team.objects.create(organization=organization, name="TempHog-1")
    team.save()

    yield team

    team.delete()


@pytest.fixture
def activity_environment():
    """Return a testing temporal ActivityEnvironment."""
    return ActivityEnvironment()
