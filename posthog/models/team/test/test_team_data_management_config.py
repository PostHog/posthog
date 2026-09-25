import pytest
from posthog.test.base import BaseTest

from django.db import IntegrityError, transaction

from parameterized import parameterized

from posthog.models.team.team_data_management_config import TeamDataManagementConfig


class TestTeamDataManagementConfig(BaseTest):
    # The field validators only run through a serializer or full_clean(), so without the database
    # constraint a queryset update could store a threshold the UI and the API both refuse.
    @parameterized.expand([("below_minimum", 0), ("above_maximum", 366)])
    def test_database_rejects_a_stale_event_days_outside_the_supported_range(
        self, _name: str, stale_event_days: int
    ) -> None:
        config = TeamDataManagementConfig.objects.get(team=self.team)

        with pytest.raises(IntegrityError), transaction.atomic():
            TeamDataManagementConfig.objects.filter(pk=config.pk).update(stale_event_days=stale_event_days)
