import asyncio
import logging
import random

import pytest_asyncio
from asgiref.sync import sync_to_async

from posthog.models import Organization, Team
from posthog.models.team.util import delete_batch_exports

logger = logging.getLogger(__name__)


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
        await asyncio.wait_for(
            sync_to_async(delete_batch_exports)(team_ids=[team.pk]),
            timeout=10.0,
        )
    except asyncio.TimeoutError:
        logger.warning("Timed out deleting batch exports for team %s during teardown", team.pk)
    except Exception:
        logger.warning("Failed to delete batch exports for team %s during teardown", team.pk, exc_info=True)
    await sync_to_async(team.delete)()
