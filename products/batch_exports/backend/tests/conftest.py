import random
import asyncio

import pytest_asyncio
from asgiref.sync import sync_to_async

from posthog.models import Organization, Team
from posthog.models.team.util import delete_batch_exports


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
    try:
        await asyncio.wait_for(sync_to_async(delete_batch_exports)(team_ids=[team.pk]), timeout=10.0)
    except Exception:
        pass  # Best-effort cleanup; test DB is reset between runs anyway
    await sync_to_async(team.delete)()
