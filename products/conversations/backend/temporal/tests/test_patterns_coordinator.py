from __future__ import annotations

from datetime import UTC, datetime

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import Team

from products.conversations.backend.temporal.patterns.coordinator import _collect_eligible_teams

ELIGIBILITY_MODULE = "products.conversations.backend.temporal.patterns.eligibility"


class TestCollectEligibleTeams(BaseTest):
    @parameterized.expand(
        [
            ("all_gates_open", True, True, True, 1),
            ("flag_off", False, True, True, 0),
            ("setting_off", True, False, True, 0),
            ("conversations_off", True, True, False, 0),
        ]
    )
    def test_every_gate_must_pass(self, _name, flag_on, setting_on, conversations_on, expected):
        Team.objects.filter(id=self.team.id).update(
            conversations_enabled=conversations_on,
            conversations_settings={"pattern_detection_enabled": setting_on},
        )

        with patch(f"{ELIGIBILITY_MODULE}.posthoganalytics.feature_enabled", return_value=flag_on):
            eligible = _collect_eligible_teams(datetime(2026, 1, 1, 10, 7, tzinfo=UTC))

        assert len(eligible) == expected
        if expected:
            assert eligible[0].team_id == self.team.id
            assert eligible[0].tick == "2026-01-01T10:00:00+00:00"
