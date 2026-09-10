import pytest
from posthog.test.base import BaseTest

from django.core.exceptions import ValidationError

from posthog.schema import NodeKind


class TestConversionGoalsValidation(BaseTest):
    def _goal(self, conversion_goal_name: str) -> dict:
        return {
            "kind": NodeKind.EVENTS_NODE,
            "id": "purchase",
            "name": "purchase",
            "conversion_goal_name": conversion_goal_name,
            "schema_map": {"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        }

    def test_unique_names_accepted(self):
        goals = [self._goal("Signups"), self._goal("Purchases")]

        self.team.marketing_analytics_config.conversion_goals = goals
        self.team.marketing_analytics_config.save()
        self.team.marketing_analytics_config.refresh_from_db()

        assert len(self.team.marketing_analytics_config.conversion_goals) == 2

    def test_duplicate_names_rejected(self):
        goals = [self._goal("Signups"), self._goal("Signups")]

        with pytest.raises(ValidationError) as exc_info:
            self.team.marketing_analytics_config.conversion_goals = goals

        assert "must be unique" in str(exc_info.value)
        assert "Signups" in str(exc_info.value)
