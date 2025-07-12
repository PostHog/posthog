from django.test import TestCase
from unittest.mock import patch

from posthog.models.action.action import Action
from posthog.models.hog_flow.hog_flow import HogFlow
from posthog.models.user import User


class TestHogFlow(TestCase):
    def setUp(self):
        super().setUp()
        org, team, user = User.objects.bootstrap("Test org", "ben@posthog.com", None)
        self.team = team
        self.user = user
        self.org = org

    def test_hog_flow_save_method(self):
        hog_flow = HogFlow.objects.create(
            name="Test Flow",
            team=self.team,
            actions={
                "action_1": {
                    "type": "function",
                    "config": {"inputs": {"key": "value"}},
                }
            },
        )
        self.assertIn("bytecode", hog_flow.actions["action_1"]["config"]["inputs"])

        # Test that the bytecode is generated correctly
        self.assertListEqual(
            hog_flow.actions["action_1"]["config"]["inputs"]["bytecode"]["key"],
            ["_H", 1, 32, "value"],
        )

    @patch("posthog.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_hog_flow_saved_receiver(self, mock_reload):
        hog_flow = HogFlow.objects.create(name="Test Flow", team=self.team)
        mock_reload.assert_called_once_with(team_id=self.team.id, hog_flow_ids=[str(hog_flow.id)])

    @patch("posthog.tasks.hog_flows.refresh_affected_hog_flows.delay")
    def test_action_saved_receiver(self, mock_refresh):
        action = Action.objects.create(team=self.team, name="Test Action")
        mock_refresh.assert_called_once_with(action_id=action.id)

    @patch("posthog.tasks.hog_flows.refresh_affected_hog_flows.delay")
    def test_team_saved_receiver(self, mock_refresh):
        self.team.save()
        mock_refresh.assert_called_once_with(team_id=self.team.id)
