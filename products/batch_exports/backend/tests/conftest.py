import random

import pytest_asyncio
from asgiref.sync import sync_to_async

from posthog.models import Organization, Team

from products.batch_exports.backend.tests.teardown import arun_best_effort


@pytest_asyncio.fixture
async def aorganization(db):
    name = f"BatchExportsTestOrg-{random.randint(1, 99999)}"
    org = await sync_to_async(Organization.objects.create)(name=name, is_ai_data_processing_approved=True)

    yield org

    await arun_best_effort(org.delete, label="organization")


@pytest_asyncio.fixture
async def ateam(aorganization):
    name = f"BatchExportsTestTeam-{random.randint(1, 99999)}"
    # need to use create here rather than acreate because TeamManager.create() has some custom logic
    team = await sync_to_async(Team.objects.create)(organization=aorganization, name=name)

    yield team
    # team.delete() CASCADE-deletes BatchExport rows; Temporal schedules in CI don't
    # need explicit removal. The cascade can block indefinitely on an uncancellable
    # backend call, so it's run time-bounded — see arun_best_effort.
    await arun_best_effort(team.delete, label="team")
