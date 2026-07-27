import random

import pytest

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
