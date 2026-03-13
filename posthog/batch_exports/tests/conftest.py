import random

import pytest

from asgiref.sync import sync_to_async

from posthog.models import Organization, Team


@pytest.fixture
def organization():
    """A test organization."""
    name = f"BatchExportsTestOrg-{random.randint(1, 99999)}"
    org = Organization.objects.create(name=name, is_ai_data_processing_approved=True)
    org.save()

    yield org

    org.delete()


@pytest.fixture
def team(organization):
    """A test team."""
    name = f"BatchExportsTestTeam-{random.randint(1, 99999)}"
    team = Team.objects.create(organization=organization, name=name)
    team.save()

    yield team

    team.delete()


@pytest.fixture
async def aorganization(db):
    """A test organization."""
    name = f"BatchExportsTestOrg-{random.randint(1, 99999)}"
    org = await Organization.objects.acreate(name=name, is_ai_data_processing_approved=True)

    yield org

    await org.adelete()


@pytest.fixture
async def ateam(aorganization):
    name = f"BatchExportsTestTeam-{random.randint(1, 99999)}"
    # need to use create here rather than acreate because TeamManager.create() has some custom logic
    team = await sync_to_async(Team.objects.create)(organization=aorganization, name=name)

    yield team

    await sync_to_async(team.delete)()
