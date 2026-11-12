from typing import Any

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.alerts.backend.llm_detector_limits import (
    DEFAULT_MAX_LLM_ALERTS_PER_TEAM,
    LLM_DETECTOR_FLAG,
    max_llm_alerts_per_team,
)

TEAM_ID = 2
ORGANIZATION_ID = "0188430e-316e-0000-51a6-fd646548690e"


class TestMaxLLMAlertsPerTeam(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_payload", None, DEFAULT_MAX_LLM_ALERTS_PER_TEAM),
            ("top_level_only", {"max_llm_alerts_per_team": 20}, 20),
            ("json_string_payload", '{"max_llm_alerts_per_team": 20}', 20),
            (
                "team_override_wins",
                {
                    "max_llm_alerts_per_team": 20,
                    "team_configs": {str(TEAM_ID): {"max_llm_alerts_per_team": 60}},
                    "organization_configs": {ORGANIZATION_ID: {"max_llm_alerts_per_team": 30}},
                },
                60,
            ),
            (
                "organization_override_when_team_not_listed",
                {
                    "max_llm_alerts_per_team": 20,
                    "team_configs": {"999": {"max_llm_alerts_per_team": 60}},
                    "organization_configs": {ORGANIZATION_ID: {"max_llm_alerts_per_team": 30}},
                },
                30,
            ),
            (
                "zero_team_override_is_honored",
                {"max_llm_alerts_per_team": 20, "team_configs": {str(TEAM_ID): {"max_llm_alerts_per_team": 0}}},
                0,
            ),
            (
                "malformed_team_override_falls_through_to_organization",
                {
                    "max_llm_alerts_per_team": 20,
                    "team_configs": {str(TEAM_ID): {"max_llm_alerts_per_team": "60"}},
                    "organization_configs": {ORGANIZATION_ID: {"max_llm_alerts_per_team": 30}},
                },
                30,
            ),
            (
                "malformed_organization_override_falls_through_to_top_level",
                {
                    "max_llm_alerts_per_team": 20,
                    "organization_configs": {ORGANIZATION_ID: {"max_llm_alerts_per_team": True}},
                },
                20,
            ),
            (
                "non_object_entries_and_maps_are_ignored",
                {
                    "max_llm_alerts_per_team": 20,
                    "team_configs": {str(TEAM_ID): 60},
                    "organization_configs": [ORGANIZATION_ID],
                },
                20,
            ),
            (
                "malformed_everywhere_falls_back_to_default",
                {"max_llm_alerts_per_team": -1, "team_configs": {str(TEAM_ID): {"max_llm_alerts_per_team": 1.5}}},
                DEFAULT_MAX_LLM_ALERTS_PER_TEAM,
            ),
        ]
    )
    def test_resolves_the_most_specific_valid_cap(self, _name: str, payload: Any, expected: int) -> None:
        with patch("posthoganalytics.get_feature_flag_payload", return_value=payload) as read:
            assert max_llm_alerts_per_team(team_id=TEAM_ID, organization_id=ORGANIZATION_ID) == expected

        read.assert_called_once()
        assert read.call_args.args[0] == LLM_DETECTOR_FLAG
        assert read.call_args.kwargs == {"match_value": True}

    def test_read_error_falls_back_to_default(self) -> None:
        with (
            patch("posthoganalytics.get_feature_flag_payload", side_effect=RuntimeError("flag service down")),
            patch("products.alerts.backend.llm_detector_limits.capture_exception"),
        ):
            assert (
                max_llm_alerts_per_team(team_id=TEAM_ID, organization_id=ORGANIZATION_ID)
                == DEFAULT_MAX_LLM_ALERTS_PER_TEAM
            )
