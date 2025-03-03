from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
import pytest_asyncio

from posthog.models import Action
from posthog.temporal.ai.sync_vectors import get_actions_qs


@pytest_asyncio.fixture
async def actions(ateam):
    actions = [
        Action(
            team=ateam,
            name="Completed onboarding",
            description="Filters users who successfully completed onboarding",
            steps_json=[{"event": "onboarding completed"}],
        ),
        Action(
            team=ateam,
            name="Requested a quote",
            description="Display users who wanted to purchase the product",
            steps_json=[{"href": "/subscribe", "href_matching": "exact", "event": "pressed button"}],
        ),
        Action(
            team=ateam,
            name="Interacted with the assistant",
            description="Cohort of events when users interacted with the AI assistant",
            steps_json=[{"event": "message sent"}, {"url": "/chat", "event": "$pageview"}],
        ),
    ]
    await Action.objects.abulk_create(actions)

    yield actions

    await Action.objects.filter(team=ateam).adelete()


@pytest.fixture
def mock_feature_flags(organization):
    with patch("posthog.temporal.ai.sync_vectors._get_orgs_from_the_feature_flag", return_value=[organization.id]):
        yield


@pytest.mark.django_db(transaction=True)
async def test_get_actions_qs(actions):
    qs = await get_actions_qs(datetime.now())
    assert qs.count() == 3
    qs = await get_actions_qs(datetime.now(), 0, 1)
    assert qs.count() == 1

    action = actions[0]
    action.updated_at = datetime.now() - timedelta(days=1)
    await action.asave()

    qs = await get_actions_qs(datetime.now())
    assert qs.count() == 2
