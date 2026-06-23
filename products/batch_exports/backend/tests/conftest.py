import random

import pytest_asyncio
from asgiref.sync import sync_to_async

from posthog.models import Organization, Team


@pytest_asyncio.fixture
async def aorganization(db):
    name = f"BatchExportsTestOrg-{random.randint(1, 99999)}"
    org = await sync_to_async(Organization.objects.create)(name=name, is_ai_data_processing_approved=True)

    yield org

    await sync_to_async(org.delete)()


@pytest_asyncio.fixture
async def ateam(aorganization):
    name = f"BatchExportsTestTeam-{random.randint(1, 99999)}"
    # need to use create here rather than acreate because TeamManager.create() has some custom logic
    team = await sync_to_async(Team.objects.create)(organization=aorganization, name=name)

    yield team
    # Skip Temporal schedule cleanup — team.delete() CASCADE-deletes BatchExport
    # rows from the DB, and Temporal schedules in CI don't need explicit removal.
    # Calling delete_batch_exports() here can hang indefinitely because
    # sync_to_async threads blocked on gRPC cannot be cancelled by asyncio.
    await sync_to_async(team.delete)()
