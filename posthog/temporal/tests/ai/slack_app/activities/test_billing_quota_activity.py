from unittest.mock import patch

from django.test import TestCase

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.ai.slack_app import (
    PostHogCodeSlackMentionWorkflowInputs,
    enforce_posthog_code_billing_quota_activity,
)


class TestEnforcePostHogCodeBillingQuotaActivity(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="TestOrg")
        self.team = Team.objects.create(organization=self.org, name="TestTeam")
        self.user = User.objects.create(email="alice@example.com")
        self.integration = Integration.objects.create(team=self.team, kind="slack", integration_id="T_SLACK", config={})

    def _call(self, *, untagged_followup: bool, confirmed: bool) -> bool:
        inputs = PostHogCodeSlackMentionWorkflowInputs(
            event={},
            integration_id=self.integration.id,
            slack_team_id="T_SLACK",
            user_id=self.user.id,
            untagged_followup=untagged_followup,
            untagged_followup_confirmed=confirmed,
        )
        return enforce_posthog_code_billing_quota_activity(inputs, "C001", "1000.0000", "U_BOB")

    @parameterized.expand(
        [
            # The gate runs before the classifier and before the prompt, so an untagged
            # reply has asked for nothing yet. A denial under it would land in the thread
            # for every reply people write, chitchat included.
            ("unconfirmed_reply", True, False, False),
            ("confirmed_reply", True, True, True),
            ("mention", False, False, True),
        ]
    )
    def test_denial_reaches_the_thread_only_for_a_turn_that_asked_for_work(
        self, _name, untagged_followup, confirmed, expect_denial
    ):
        with (
            patch("ee.billing.quota_limiting.is_team_limited", return_value=True),
            patch("products.slack_app.backend.api.post_quota_exhausted_denial") as mock_denial,
        ):
            blocked = self._call(untagged_followup=untagged_followup, confirmed=confirmed)

        assert blocked is True
        assert mock_denial.called is expect_denial

    def test_a_team_within_quota_is_not_blocked(self):
        with (
            patch("ee.billing.quota_limiting.is_team_limited", return_value=False),
            patch("products.slack_app.backend.api.post_quota_exhausted_denial") as mock_denial,
        ):
            assert self._call(untagged_followup=True, confirmed=False) is False
        mock_denial.assert_not_called()
