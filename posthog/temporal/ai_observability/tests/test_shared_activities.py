import pytest

from parameterized import parameterized

from posthog.sync import database_sync_to_async
from posthog.temporal.ai_observability.shared_activities import (
    TeamAIConsentInput,
    check_ai_data_processing_consent_activity,
)


def _create_team(approved: bool | None) -> int:
    from posthog.models.organization import Organization
    from posthog.models.team import Team

    organization = Organization.objects.create(name="Org", is_ai_data_processing_approved=approved)
    return Team.objects.create(organization=organization, name="Team").id


@pytest.mark.django_db(transaction=True)
class TestCheckAIDataProcessingConsentActivity:
    @parameterized.expand(
        [
            ("approved", True, True),
            ("null_counts_as_approved", None, True),
            ("not_approved", False, False),
        ]
    )
    @pytest.mark.asyncio
    async def test_consent_flag_decides(self, _name, approved, expected):
        team_id = await database_sync_to_async(_create_team)(approved)

        assert await check_ai_data_processing_consent_activity(TeamAIConsentInput(team_id=team_id)) is expected

    @pytest.mark.asyncio
    async def test_missing_team_is_not_approved(self):
        assert await check_ai_data_processing_consent_activity(TeamAIConsentInput(team_id=-1)) is False
