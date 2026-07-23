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

    def test_goal_without_optional_name_accepted(self):
        # `name` is optional on ConversionGoalFilter; a schema-valid goal that omits it must not be rejected.
        goal = self._goal("Signups")
        del goal["name"]

        self.team.marketing_analytics_config.conversion_goals = [goal]
        self.team.marketing_analytics_config.save()
        self.team.marketing_analytics_config.refresh_from_db()

        assert len(self.team.marketing_analytics_config.conversion_goals) == 1

    def test_missing_conversion_goal_name_rejected(self):
        goal = self._goal("Signups")
        del goal["conversion_goal_name"]

        with pytest.raises(ValidationError) as exc_info:
            self.team.marketing_analytics_config.conversion_goals = [goal]

        assert "conversion_goal_name" in str(exc_info.value)

    def test_actions_node_missing_id_raises_validation_error(self):
        # int(None) used to escape as an uncaught TypeError (→ HTTP 500); it must surface as a ValidationError.
        goal = {
            "kind": NodeKind.ACTIONS_NODE,
            "conversion_goal_name": "Signups",
            "schema_map": {"utm_campaign_name": "utm_campaign"},
        }

        with pytest.raises(ValidationError) as exc_info:
            self.team.marketing_analytics_config.conversion_goals = [goal]

        assert "integer" in str(exc_info.value)

    def test_actions_node_integer_id_accepted(self):
        goal = {
            "kind": NodeKind.ACTIONS_NODE,
            "id": "42",
            "conversion_goal_name": "Signups",
            "schema_map": {"utm_campaign_name": "utm_campaign"},
        }

        self.team.marketing_analytics_config.conversion_goals = [goal]
        self.team.marketing_analytics_config.save()
        self.team.marketing_analytics_config.refresh_from_db()

        assert self.team.marketing_analytics_config.conversion_goals[0]["id"] == 42
