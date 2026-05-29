from unittest.mock import patch

from django.test import TestCase

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.temporal.ai.posthog_code_slack_mention import classify_posthog_code_task_needs_repo_activity


class TestClassifyPostHogCodeTaskNeedsRepoActivity(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="TestOrg")
        self.team = Team.objects.create(organization=self.org, name="TestTeam")
        self.integration = Integration.objects.create(
            team=self.team, kind="slack-posthog-code", integration_id="T_SLACK", config={}
        )

    @patch("products.slack_app.backend.api.classify_task_needs_repo")
    def test_resolves_team_id_from_integration(self, mock_classify):
        mock_classify.return_value = False

        result = classify_posthog_code_task_needs_repo_activity("fix the checkout test", [], self.integration.id)

        assert result is False
        mock_classify.assert_called_once_with("fix the checkout test", [], team_id=self.team.id)

    @patch("products.slack_app.backend.api.classify_task_needs_repo")
    def test_defaults_to_picker_when_integration_missing(self, mock_classify):
        result = classify_posthog_code_task_needs_repo_activity("fix the checkout test", [], 999999)

        assert result is True
        mock_classify.assert_not_called()
