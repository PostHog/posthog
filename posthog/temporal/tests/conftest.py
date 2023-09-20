import pytest
import pytest_asyncio
from asgiref.sync import sync_to_async
from django.conf import settings
from temporalio.testing import ActivityEnvironment

from posthog.api.test.test_organization import acreate_organization
from posthog.api.test.test_team import acreate_team
from posthog.models import Organization, Team
from posthog.temporal.client import connect


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


@pytest_asyncio.fixture
async def aorganization():
    """A test organization in an asynchronous fixture."""
    organization = await acreate_organization("test")
    yield organization
    await sync_to_async(organization.delete)()  # type: ignore


@pytest_asyncio.fixture
async def ateam(aorganization):
    """A test team in an asynchronous fixture."""
    team = await acreate_team(organization=aorganization)
    yield team
    await sync_to_async(team.delete)()  # type: ignore


@pytest_asyncio.fixture
async def temporal_client():
    """A Temporal client."""
    client = await connect(
        settings.TEMPORAL_HOST,
        settings.TEMPORAL_PORT,
        settings.TEMPORAL_NAMESPACE,
        settings.TEMPORAL_CLIENT_ROOT_CA,
        settings.TEMPORAL_CLIENT_CERT,
        settings.TEMPORAL_CLIENT_KEY,
    )
    return client


@pytest.fixture
def activity_environment():
    """Return a testing temporal ActivityEnvironment."""
    return ActivityEnvironment()
