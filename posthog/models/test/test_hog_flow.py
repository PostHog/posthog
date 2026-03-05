from unittest.mock import patch

from django.test import TestCase

from parameterized import parameterized

from posthog.models.action.action import Action
from posthog.models.hog_flow.hog_flow import HogFlow
from posthog.models.hog_function_template import HogFunctionTemplate
from posthog.models.user import User

TEMPLATE_WITH_SECRET_ID = "template-test-secret-dest"
TEMPLATE_NO_SECRET_ID = "template-test-no-secret-dest"


def _create_secret_template():
    return HogFunctionTemplate.objects.create(
        template_id=TEMPLATE_WITH_SECRET_ID,
        name="Test Secret Destination",
        type="destination",
        status="alpha",
        code="fetch(inputs.url, {headers: {'Authorization': inputs.api_key}})",
        code_language="hog",
        inputs_schema=[
            {"key": "url", "type": "string", "label": "URL", "secret": False, "required": True},
            {"key": "api_key", "type": "string", "label": "API Key", "secret": True, "required": True},
        ],
        category=["Custom"],
    )


def _create_no_secret_template():
    return HogFunctionTemplate.objects.create(
        template_id=TEMPLATE_NO_SECRET_ID,
        name="Test No Secret Destination",
        type="destination",
        status="alpha",
        code="fetch(inputs.url)",
        code_language="hog",
        inputs_schema=[
            {"key": "url", "type": "string", "label": "URL", "secret": False, "required": True},
        ],
        category=["Custom"],
    )


class TestHogFlow(TestCase):
    def setUp(self):
        super().setUp()
        org, team, user = User.objects.bootstrap("Test org", "ben@posthog.com", None)
        self.team = team
        self.user = user
        self.org = org

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

    @patch("posthog.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_move_secret_inputs_extracts_secrets_from_action_config(self, _mock_reload):
        _create_secret_template()
        flow = HogFlow(
            team=self.team,
            trigger={"type": "event"},
            actions=[
                {"id": "trigger_node", "type": "trigger", "config": {"type": "event"}},
                {
                    "id": "action_1",
                    "type": "function",
                    "config": {
                        "template_id": TEMPLATE_WITH_SECRET_ID,
                        "inputs": {
                            "url": {"value": "https://example.com"},
                            "api_key": {"value": "sk-12345"},
                        },
                    },
                },
            ],
        )

        flow.move_secret_inputs()

        assert flow.actions[1]["config"]["inputs"] == {"url": {"value": "https://example.com"}}
        assert flow.encrypted_inputs == {"action_1": {"api_key": {"value": "sk-12345"}}}

    @patch("posthog.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_move_secret_inputs_preserves_non_secret_inputs(self, _mock_reload):
        _create_no_secret_template()
        flow = HogFlow(
            team=self.team,
            trigger={"type": "event"},
            actions=[
                {"id": "trigger_node", "type": "trigger", "config": {"type": "event"}},
                {
                    "id": "action_1",
                    "type": "function",
                    "config": {
                        "template_id": TEMPLATE_NO_SECRET_ID,
                        "inputs": {"url": {"value": "https://example.com"}},
                    },
                },
            ],
        )

        flow.move_secret_inputs()

        assert flow.actions[1]["config"]["inputs"] == {"url": {"value": "https://example.com"}}
        assert flow.encrypted_inputs is None

    @patch("posthog.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_move_secret_inputs_secret_marker_preserves_existing_encrypted(self, _mock_reload):
        _create_secret_template()
        flow = HogFlow(
            team=self.team,
            trigger={"type": "event"},
            encrypted_inputs={"action_1": {"api_key": {"value": "sk-original"}}},
            actions=[
                {"id": "trigger_node", "type": "trigger", "config": {"type": "event"}},
                {
                    "id": "action_1",
                    "type": "function",
                    "config": {
                        "template_id": TEMPLATE_WITH_SECRET_ID,
                        "inputs": {
                            "url": {"value": "https://example.com"},
                            "api_key": {"secret": True},
                        },
                    },
                },
            ],
        )

        flow.move_secret_inputs()

        assert "api_key" not in flow.actions[1]["config"]["inputs"]
        assert flow.encrypted_inputs == {"action_1": {"api_key": {"value": "sk-original"}}}

    @parameterized.expand(
        [
            ("delay",),
            ("branch",),
            ("wait",),
        ]
    )
    @patch("posthog.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_move_secret_inputs_skips_non_function_actions(self, action_type, _mock_reload):
        _create_secret_template()
        flow = HogFlow(
            team=self.team,
            trigger={"type": "event"},
            actions=[
                {"id": "trigger_node", "type": "trigger", "config": {"type": "event"}},
                {
                    "id": "action_1",
                    "type": action_type,
                    "config": {
                        "template_id": TEMPLATE_WITH_SECRET_ID,
                        "inputs": {"api_key": {"value": "sk-12345"}},
                    },
                },
            ],
        )

        flow.move_secret_inputs()

        assert flow.actions[1]["config"]["inputs"] == {"api_key": {"value": "sk-12345"}}
        assert flow.encrypted_inputs is None

    @patch("posthog.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_move_secret_inputs_skips_actions_with_missing_template(self, _mock_reload):
        flow = HogFlow(
            team=self.team,
            trigger={"type": "event"},
            actions=[
                {"id": "trigger_node", "type": "trigger", "config": {"type": "event"}},
                {
                    "id": "action_1",
                    "type": "function",
                    "config": {
                        "template_id": "template-nonexistent",
                        "inputs": {"api_key": {"value": "sk-12345"}},
                    },
                },
            ],
        )

        flow.move_secret_inputs()

        assert flow.actions[1]["config"]["inputs"] == {"api_key": {"value": "sk-12345"}}
        assert flow.encrypted_inputs is None

    @patch("posthog.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_move_secret_inputs_skips_actions_without_template_id(self, _mock_reload):
        flow = HogFlow(
            team=self.team,
            trigger={"type": "event"},
            actions=[
                {"id": "trigger_node", "type": "trigger", "config": {"type": "event"}},
                {
                    "id": "action_1",
                    "type": "function",
                    "config": {
                        "inputs": {"api_key": {"value": "sk-12345"}},
                    },
                },
            ],
        )

        flow.move_secret_inputs()

        assert flow.actions[1]["config"]["inputs"] == {"api_key": {"value": "sk-12345"}}
        assert flow.encrypted_inputs is None

    @patch("posthog.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_move_secret_inputs_multiple_function_actions(self, _mock_reload):
        _create_secret_template()
        flow = HogFlow(
            team=self.team,
            trigger={"type": "event"},
            actions=[
                {"id": "trigger_node", "type": "trigger", "config": {"type": "event"}},
                {
                    "id": "action_1",
                    "type": "function",
                    "config": {
                        "template_id": TEMPLATE_WITH_SECRET_ID,
                        "inputs": {
                            "url": {"value": "https://first.com"},
                            "api_key": {"value": "sk-first"},
                        },
                    },
                },
                {
                    "id": "action_2",
                    "type": "function",
                    "config": {
                        "template_id": TEMPLATE_WITH_SECRET_ID,
                        "inputs": {
                            "url": {"value": "https://second.com"},
                            "api_key": {"value": "sk-second"},
                        },
                    },
                },
            ],
        )

        flow.move_secret_inputs()

        assert flow.actions[1]["config"]["inputs"] == {"url": {"value": "https://first.com"}}
        assert flow.actions[2]["config"]["inputs"] == {"url": {"value": "https://second.com"}}
        assert flow.encrypted_inputs == {
            "action_1": {"api_key": {"value": "sk-first"}},
            "action_2": {"api_key": {"value": "sk-second"}},
        }

    @parameterized.expand(
        [
            ("webhook",),
            ("manual",),
        ]
    )
    @patch("posthog.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_move_secret_inputs_function_trigger_extracts_secrets(self, trigger_type, _mock_reload):
        _create_secret_template()
        flow = HogFlow(
            team=self.team,
            trigger={"type": trigger_type},
            actions=[
                {
                    "id": "trigger_node",
                    "type": "trigger",
                    "config": {
                        "type": trigger_type,
                        "template_id": TEMPLATE_WITH_SECRET_ID,
                        "inputs": {
                            "url": {"value": "https://hook.example.com"},
                            "api_key": {"value": "sk-trigger-secret"},
                        },
                    },
                },
            ],
        )

        flow.move_secret_inputs()

        assert flow.actions[0]["config"]["inputs"] == {"url": {"value": "https://hook.example.com"}}
        assert flow.encrypted_inputs == {"trigger_node": {"api_key": {"value": "sk-trigger-secret"}}}

    @patch("posthog.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_move_secret_inputs_event_trigger_not_treated_as_function(self, _mock_reload):
        _create_secret_template()
        flow = HogFlow(
            team=self.team,
            trigger={"type": "event"},
            actions=[
                {
                    "id": "trigger_node",
                    "type": "trigger",
                    "config": {
                        "type": "event",
                        "template_id": TEMPLATE_WITH_SECRET_ID,
                        "inputs": {"api_key": {"value": "sk-should-stay"}},
                    },
                },
            ],
        )

        flow.move_secret_inputs()

        assert flow.actions[0]["config"]["inputs"] == {"api_key": {"value": "sk-should-stay"}}
        assert flow.encrypted_inputs is None

    @patch("posthog.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_move_secret_inputs_preserves_non_schema_inputs(self, _mock_reload):
        _create_secret_template()
        flow = HogFlow(
            team=self.team,
            trigger={"type": "event"},
            actions=[
                {"id": "trigger_node", "type": "trigger", "config": {"type": "event"}},
                {
                    "id": "action_1",
                    "type": "function",
                    "config": {
                        "template_id": TEMPLATE_WITH_SECRET_ID,
                        "inputs": {
                            "url": {"value": "https://example.com"},
                            "api_key": {"value": "sk-12345"},
                            "extra_field": {"value": "extra_value"},
                        },
                    },
                },
            ],
        )

        flow.move_secret_inputs()

        assert flow.actions[1]["config"]["inputs"] == {
            "url": {"value": "https://example.com"},
            "extra_field": {"value": "extra_value"},
        }
        assert flow.encrypted_inputs == {"action_1": {"api_key": {"value": "sk-12345"}}}
