import uuid as uuid_mod
from datetime import UTC, datetime, timedelta
from typing import Optional

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import Mock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES
from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.cdp.templates.slack.template_slack import template as template_slack
from posthog.models import Organization, Team, User
from posthog.models.hog_flow.hog_flow import HogFlow

webhook_template = MOCK_NODE_TEMPLATES[0]


class TestHogFlowAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        # Create slack template in DB
        sync_template_to_db(template_slack)
        sync_template_to_db(webhook_template)

    def _create_hog_flow_with_action(self, action_config: dict):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }
        action = {
            "id": "action_1",
            "name": "action_1",
            "type": "function",
            "config": action_config,
        }

        hog_flow = {
            "name": "Test Flow",
            "actions": [trigger_action, action],
        }

        return hog_flow, action

    def test_hog_flow_function_trigger_check(self):
        hog_flow = {
            "name": "Test Flow",
            "actions": [],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 400, response.json()
        assert response.json() == {
            "attr": "actions",
            "code": "invalid_input",
            "detail": "Exactly one trigger action is required",
            "type": "validation_error",
        }

    def test_hog_flow_function_trigger_copied_from_action(self):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "webhook",
                "template_id": "template-webhook",
                "inputs": {
                    "url": {"value": "https://example.com"},
                },
            },
        }

        hog_flow = {
            "name": "Test Flow",
            "status": "active",
            "actions": [trigger_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)

        trigger_action_expectation = {
            "id": "trigger_node",
            "name": "trigger_1",
            "description": "",
            "on_error": None,
            "filters": None,
            "type": "trigger",
            "config": {
                "type": "webhook",
                "template_id": "template-webhook",
                "inputs": {
                    "url": {
                        "value": "https://example.com",
                        "bytecode": ["_H", 1, 32, "https://example.com"],
                        "order": 0,
                    }
                },
            },
            "output_variable": None,
        }

        assert response.status_code == 201, response.json()
        assert response.json()["actions"] == [trigger_action_expectation]
        assert response.json()["trigger"] == trigger_action_expectation["config"]

    def _make_delay_flow(self, delay_config: dict, status: Optional[str] = "active") -> dict:
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }
        delay_action = {"id": "d1", "name": "d1", "type": "delay", "config": delay_config}
        flow: dict = {"name": "Test Flow", "actions": [trigger_action, delay_action]}
        if status is not None:
            flow["status"] = status
        return flow

    @parameterized.expand(
        [
            ("missing_delay_duration", {}),
            ("null_delay_duration", {"delay_duration": None}),
            ("numeric_delay_duration", {"delay_duration": 1800}),
            ("seconds_as_input_shape", {"inputs": {"duration": {"value": 1800}}}),
            ("iso_8601_duration", {"delay_duration": "P30D"}),
            ("unit_and_duration_shape", {"unit": "days", "duration": 3}),
            ("unsupported_unit", {"delay_duration": "30s"}),
            ("empty_string", {"delay_duration": ""}),
        ]
    )
    def test_hog_flow_delay_validation_rejects_malformed_config(self, _name, bad_config):
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", self._make_delay_flow(bad_config))
        assert response.status_code == 400, response.json()
        assert response.json() == {
            "attr": "actions__1__config",
            "code": "invalid_input",
            "detail": (
                "delay_duration must be a string matching ^\\d*\\.?\\d+[dhm]$ "
                "(e.g. '30m', '2h', '1d'). Seconds and ISO-8601 formats are not supported."
            ),
            "type": "validation_error",
        }

    @parameterized.expand(
        [
            ("minutes", "30m"),
            ("hours", "2h"),
            ("days", "1d"),
            ("fractional", "1.5h"),
        ]
    )
    def test_hog_flow_delay_validation_accepts_canonical_config(self, _name, delay_duration):
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows",
            self._make_delay_flow({"delay_duration": delay_duration}),
        )
        assert response.status_code == 201, response.json()

    def test_hog_flow_delay_validation_lenient_for_drafts(self):
        # status omitted defaults to draft; draft mode lets users save WIP with invalid configs
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows",
            self._make_delay_flow({"inputs": {"duration": {"value": 1800}}}, status=None),
        )
        assert response.status_code == 201, response.json()

    def test_hog_flow_function_validation(self):
        hog_flow, action = self._create_hog_flow_with_action(
            {
                "template_id": "missing",
                "inputs": {},
            }
        )
        hog_flow["status"] = "active"

        # Check that the template is found but missing required inputs
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 400, response.json()
        assert response.json() == {
            "attr": "actions__1__template_id",
            "code": "invalid_input",
            "detail": "Template not found",
            "type": "validation_error",
        }

        # Check that the template is found but missing required inputs
        hog_flow, action = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {},
            }
        )
        hog_flow["status"] = "active"
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 400, response.json()
        assert response.json() == {
            "attr": "actions__1__inputs__url",
            "code": "invalid_input",
            "detail": "This field is required.",
            "type": "validation_error",
        }

    def test_hog_flow_bytecode_compilation(self):
        hog_flow, action = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
            }
        )
        hog_flow["status"] = "active"

        action["filters"] = {
            "properties": [{"key": "event", "type": "event_metadata", "value": ["custom_event"], "operator": "exact"}]
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)

        assert response.status_code == 201, response.json()
        hog_flow = HogFlow.objects.get(pk=response.json()["id"])

        assert hog_flow.trigger["filters"].get("bytecode") == ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11]

        assert hog_flow.actions[1]["filters"].get("bytecode") == ["_H", 1, 32, "custom_event", 32, "event", 1, 1, 11]

        assert hog_flow.actions[1]["config"]["inputs"] == {
            "url": {"order": 0, "value": "https://example.com", "bytecode": ["_H", 1, 32, "https://example.com"]}
        }

    def test_hog_flow_conversion_filters_compiles_bytecode_on_create(self):
        expected_conversion_bytecode = [
            "_H",
            1,
            32,
            "Chrome",
            32,
            "$browser",
            32,
            "properties",
            32,
            "person",
            1,
            3,
            11,
        ]

        hog_flow, _ = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
            }
        )
        hog_flow["status"] = "active"
        hog_flow["conversion"] = {
            "filters": [
                {
                    "key": "$browser",
                    "type": "person",
                    "value": ["Chrome"],
                    "operator": "exact",
                }
            ],
            "window_minutes": None,
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)

        assert response.status_code == 201, response.json()
        conversion = response.json()["conversion"]
        assert conversion["filters"][0] == {
            "key": "$browser",
            "type": "person",
            "value": ["Chrome"],
            "operator": "exact",
        }
        assert conversion["bytecode"] == expected_conversion_bytecode

        flow = HogFlow.objects.get(pk=response.json()["id"])
        flow_conversion = flow.conversion
        assert flow_conversion is not None
        assert flow_conversion["window_minutes"] is None
        assert flow_conversion["filters"][0] == {
            "key": "$browser",
            "type": "person",
            "value": ["Chrome"],
            "operator": "exact",
        }
        assert flow_conversion["bytecode"] == expected_conversion_bytecode

    def test_hog_flow_conversion_filters_compiles_bytecode_on_update(self):
        expected_conversion_bytecode = [
            "_H",
            1,
            32,
            "Chrome",
            32,
            "$browser",
            32,
            "properties",
            32,
            "person",
            1,
            3,
            11,
        ]

        hog_flow, _ = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
            }
        )
        hog_flow["status"] = "active"

        create_response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert create_response.status_code == 201, create_response.json()
        flow_id = create_response.json()["id"]

        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {
                "conversion": {
                    "filters": [
                        {
                            "key": "$browser",
                            "type": "person",
                            "value": ["Chrome"],
                            "operator": "exact",
                        }
                    ],
                    "window_minutes": None,
                }
            },
        )

        assert update_response.status_code == 200, update_response.json()
        conversion = update_response.json()["conversion"]
        assert conversion["filters"][0] == {
            "key": "$browser",
            "type": "person",
            "value": ["Chrome"],
            "operator": "exact",
        }
        assert conversion["bytecode"] == expected_conversion_bytecode

        flow = HogFlow.objects.get(pk=flow_id)
        flow_conversion = flow.conversion
        assert flow_conversion is not None
        assert flow_conversion["window_minutes"] is None
        assert flow_conversion["filters"][0] == {
            "key": "$browser",
            "type": "person",
            "value": ["Chrome"],
            "operator": "exact",
        }
        assert flow_conversion["bytecode"] == expected_conversion_bytecode

    def test_hog_flow_conditional_branch_filters_bytecode(self):
        conditional_action = {
            "id": "cond_1",
            "name": "cond_1",
            "type": "function",
            "config": {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
                "conditions": [
                    {
                        "filters": {
                            "properties": [
                                {
                                    "key": "event",
                                    "type": "event_metadata",
                                    "value": ["custom_event"],
                                    "operator": "exact",
                                }
                            ]
                        }
                    }
                ],
            },
        }

        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }

        hog_flow = {
            "name": "Test Flow",
            "status": "active",
            "actions": [trigger_action, conditional_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()

        conditions = response.json()["actions"][1]["config"]["conditions"]
        assert "filters" in conditions[0]
        assert "bytecode" in conditions[0]["filters"], conditions[0]["filters"]
        assert conditions[0]["filters"]["bytecode"] == ["_H", 1, 32, "custom_event", 32, "event", 1, 1, 11]

    def test_hog_flow_single_condition_field(self):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }

        wait_action = {
            "id": "wait_1",
            "name": "wait_1",
            "type": "wait_until_condition",
            "config": {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
                "condition": {
                    "filters": {
                        "properties": [
                            {
                                "key": "event",
                                "type": "event_metadata",
                                "value": ["custom_event"],
                                "operator": "exact",
                            }
                        ]
                    }
                },
            },
        }

        hog_flow = {
            "name": "Test Flow Single Condition",
            "status": "active",
            "actions": [trigger_action, wait_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()

        condition = response.json()["actions"][1]["config"]["condition"]
        assert "filters" in condition
        assert "bytecode" in condition["filters"], condition["filters"]
        assert condition["filters"]["bytecode"] == ["_H", 1, 32, "custom_event", 32, "event", 1, 1, 11]

    def test_hog_flow_condition_and_conditions_mutually_exclusive(self):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }

        wait_action = {
            "id": "wait_1",
            "name": "wait_1",
            "type": "wait_until_condition",
            "config": {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
                "condition": {
                    "filters": {
                        "properties": [
                            {
                                "key": "event",
                                "type": "event_metadata",
                                "value": ["custom_event"],
                                "operator": "exact",
                            }
                        ]
                    }
                },
                "conditions": [
                    {
                        "filters": {
                            "properties": [
                                {
                                    "key": "event",
                                    "type": "event_metadata",
                                    "value": ["another_event"],
                                    "operator": "exact",
                                }
                            ]
                        }
                    }
                ],
            },
        }

        hog_flow = {
            "name": "Test Flow Mutually Exclusive",
            "status": "active",
            "actions": [trigger_action, wait_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 400, response.json()

        data = response.json()
        assert data["attr"] == "actions__1__config"
        assert data["code"] == "invalid_input"
        assert data["type"] == "validation_error"

    def test_hog_flow_enable_disable(self):
        hog_flow, _ = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
            }
        )
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()

        assert response.json()["status"] == "draft"
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{response.json()['id']}", {"status": "active"}
        )
        assert response.status_code == 200, response.json()
        assert response.json()["status"] == "active"
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{response.json()['id']}", {"status": "draft"}
        )
        assert response.status_code == 200, response.json()
        assert response.json()["status"] == "draft"

    def test_hog_flow_conditional_event_filter_rejected(self):
        conditional_action = {
            "id": "cond_1",
            "name": "cond_1",
            "type": "function",
            "config": {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
                "conditions": [
                    {
                        "filters": {
                            "events": [{"id": "custom_event", "name": "custom_event", "type": "events", "order": 0}]
                        }
                    }
                ],
            },
        }

        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }

        hog_flow = {
            "name": "Test Flow",
            "status": "active",
            "actions": [trigger_action, conditional_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 400, response.json()
        assert response.json() == {
            "attr": "actions__1__non_field_errors",
            "code": "invalid_input",
            "detail": "Event filters are not allowed in conditionals",
            "type": "validation_error",
        }

    def test_hog_flow_batch_trigger_valid_filters(self):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "batch",
                "filters": {
                    "properties": [{"key": "email", "type": "person", "value": "test@example.com", "operator": "exact"}]
                },
            },
        }

        hog_flow = {
            "name": "Test Batch Flow",
            "actions": [trigger_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()
        assert response.json()["trigger"]["type"] == "batch"
        assert response.json()["trigger"]["filters"]["properties"][0]["key"] == "email"

    def test_hog_flow_batch_trigger_without_filters(self):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "batch",
            },
        }

        hog_flow = {
            "name": "Test Batch Flow",
            "status": "active",
            "actions": [trigger_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 400, response.json()

    def test_hog_flow_batch_trigger_filters_not_dict(self):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "batch",
                "filters": "not a dict",
            },
        }

        hog_flow = {
            "name": "Test Batch Flow",
            "status": "active",
            "actions": [trigger_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 400, response.json()
        assert response.json() == {
            "attr": "actions__0__filters",
            "code": "invalid_input",
            "detail": "Filters must be a dictionary.",
            "type": "validation_error",
        }

    def test_hog_flow_batch_trigger_properties_not_array(self):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "batch",
                "filters": {
                    "properties": "not an array",
                },
            },
        }

        hog_flow = {
            "name": "Test Batch Flow",
            "status": "active",
            "actions": [trigger_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 400, response.json()
        assert response.json() == {
            "attr": "actions__0__filters__properties",
            "code": "invalid_input",
            "detail": "Properties must be an array.",
            "type": "validation_error",
        }

    def test_hog_flow_user_blast_radius_requires_filters(self):
        with patch("posthog.api.hog_flow.get_user_blast_radius") as mock_get_user_blast_radius:
            response = self.client.post(f"/api/projects/{self.team.id}/hog_flows/user_blast_radius", {})

        assert response.status_code == 400, response.json()
        assert "Missing filters" in response.json().get("detail", "")
        mock_get_user_blast_radius.assert_not_called()

    def test_hog_flow_user_blast_radius_returns_counts(self):
        with patch("posthog.api.hog_flow.get_user_blast_radius") as mock_get_user_blast_radius:
            from posthog.models.feature_flag.user_blast_radius import BlastRadiusResult

            mock_get_user_blast_radius.return_value = BlastRadiusResult(affected=4, total=10)

            response = self.client.post(
                f"/api/projects/{self.team.id}/hog_flows/user_blast_radius",
                {"filters": {"properties": []}},
            )

        assert response.status_code == 200, response.json()
        assert response.json() == {"affected": 4, "total": 10}

    def test_billable_action_types_computed_correctly(self):
        """Test that billable_action_types is computed correctly and cannot be overridden by clients"""
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }

        actions = [
            trigger_action,
            {
                "id": "a1",
                "name": "webhook1",
                "type": "function",
                "config": {"template_id": "template-webhook", "inputs": {"url": {"value": "https://example.com"}}},
            },
            {
                "id": "delay1",
                "name": "delay_action",
                "type": "delay",
                "config": {"duration": 60},
            },  # Non-billable action type
            {
                "id": "a2",
                "name": "webhook2",
                "type": "function",
                "config": {"template_id": "template-webhook", "inputs": {"url": {"value": "https://example2.com"}}},
            },  # Duplicate function type
        ]

        # Try to set billable_action_types manually (should be ignored)
        hog_flow = {
            "name": "Test Billable Types",
            "actions": actions,
            "billable_action_types": ["fake_type", "another_fake"],  # Client tries to override
        }
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)

        assert response.status_code == 201, response.json()
        # Should have only unique billable types (deduped), client override ignored
        # The delay action should NOT be included in billable_action_types
        assert response.json()["billable_action_types"] == ["function"]

        # Verify it's stored correctly in database
        flow = HogFlow.objects.get(pk=response.json()["id"])
        assert flow.billable_action_types == ["function"]

        # Verify that we have both function actions and the delay action in the flow
        assert len(flow.actions) == 4  # trigger + 2 functions + 1 delay
        action_types = [action["type"] for action in flow.actions]
        assert "delay" in action_types  # Delay is present
        assert action_types.count("function") == 2  # Two function actions

    def test_billable_action_types_recomputed_on_update(self):
        """Test that billable_action_types is recomputed when HogFlow is updated"""
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }

        # Create flow with just one function action
        initial_actions = [
            trigger_action,
            {
                "id": "a1",
                "name": "webhook",
                "type": "function",
                "config": {"template_id": "template-webhook", "inputs": {"url": {"value": "https://example.com"}}},
            },
        ]

        hog_flow = {"name": "Test Update Billable Types", "actions": initial_actions}
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()
        flow_id = response.json()["id"]
        assert response.json()["billable_action_types"] == ["function"]

        # Update to remove function action (no billable actions left)
        updated_actions = [trigger_action]
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}", {"actions": updated_actions}
        )
        assert update_response.status_code == 200, update_response.json()
        assert update_response.json()["billable_action_types"] == []

        # Update again to add multiple webhook actions (same billable type) and a delay (non-billable)
        complex_actions = [
            trigger_action,
            {
                "id": "a1",
                "name": "webhook",
                "type": "function",
                "config": {"template_id": "template-webhook", "inputs": {"url": {"value": "https://example.com"}}},
            },
            {
                "id": "delay1",
                "name": "delay_action",
                "type": "delay",
                "config": {"duration": 30},
            },  # Non-billable action
            {
                "id": "a2",
                "name": "webhook2",
                "type": "function",
                "config": {"template_id": "template-webhook", "inputs": {"url": {"value": "https://example2.com"}}},
            },
        ]

        # Try to override billable_action_types in update - should be ignored and recomputed
        override_response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {
                "actions": complex_actions,
                "billable_action_types": ["fake_type"],  # Try to override
            },
        )
        assert override_response.status_code == 200, override_response.json()
        # Should be recomputed based on actual actions, not the override attempt
        # Delay action should NOT be in billable_action_types
        assert override_response.json()["billable_action_types"] == ["function"]

        # Verify database is consistent
        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.billable_action_types == ["function"]

        # Verify that the delay action is present but not counted as billable
        assert len(flow.actions) == 4  # trigger + 2 functions + 1 delay
        action_types = [action["type"] for action in flow.actions]
        assert "delay" in action_types  # Delay is present
        assert action_types.count("function") == 2  # Two function actions

    @patch(
        "products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation"
    )
    def test_post_hog_flow_batch_jobs_endpoint_creates_job(self, mock_create_invocation):
        hog_flow, _ = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
            }
        )
        create_response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert create_response.status_code == 201, create_response.json()
        flow_id = create_response.json()["id"]

        batch_job_data = {
            "variables": [{"key": "first_name", "value": "Test"}],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/batch_jobs", batch_job_data)

        assert response.status_code == 200, response.json()
        assert response.json()["hog_flow"] == flow_id
        assert response.json()["variables"] == batch_job_data["variables"]
        assert response.json()["status"] == "queued"
        mock_create_invocation.assert_called_once()

    def test_post_hog_flow_batch_jobs_endpoint_nonexistent_flow(self):
        batch_job_data = {"variables": [{"key": "first_name", "value": "Test"}]}

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows/99999/batch_jobs", batch_job_data)

        assert response.status_code == 404, response.json()

    @patch(
        "products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation"
    )
    def test_get_hog_flow_batch_jobs_only_returns_jobs_for_flow(self, mock_create_invocation):
        hog_flow, _ = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
            }
        )
        create_response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert create_response.status_code == 201, create_response.json()
        flow_id = create_response.json()["id"]

        # Create another flow
        hog_flow_2, _ = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example2.com"}},
            }
        )
        create_response_2 = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow_2)
        assert create_response_2.status_code == 201, create_response_2.json()
        flow_id_2 = create_response_2.json()["id"]

        # Create batch jobs for both flows
        batch_job_data_1 = {"variables": [{"key": "first_name", "value": "Test1"}]}
        batch_job_data_2 = {"variables": [{"key": "first_name", "value": "Test2"}]}

        job_response_1 = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/batch_jobs", batch_job_data_1
        )
        assert job_response_1.status_code == 200, job_response_1.json()

        job_response_2 = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id_2}/batch_jobs", batch_job_data_2
        )
        assert job_response_2.status_code == 200, job_response_2.json()

        # Fetch jobs for the first flow
        get_response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/batch_jobs")
        assert get_response.status_code == 200, get_response.json()
        jobs = get_response.json()
        assert len(jobs) == 1
        assert jobs[0]["id"] == job_response_1.json()["id"]

    def test_hog_flow_filter_test_accounts_compiles_bytecode(self):
        """Test that filter_test_accounts includes team's test account filters in bytecode"""
        # Set up test account filters on the team
        self.team.test_account_filters = [
            {
                "key": "email",
                "value": "@posthog.com",
                "operator": "not_icontains",
                "type": "person",
            }
        ]
        self.team.save()

        # Create a workflow WITHOUT filter_test_accounts
        trigger_action_without_filter = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }

        hog_flow_without = {
            "name": "Test Flow Without Filter",
            "status": "active",
            "actions": [trigger_action_without_filter],
        }

        response_without = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow_without)
        assert response_without.status_code == 201, response_without.json()

        # Bytecode should just check for $pageview event
        bytecode_without = response_without.json()["trigger"]["filters"]["bytecode"]
        assert bytecode_without == ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11]

        # Create a workflow WITH filter_test_accounts: true
        trigger_action_with_filter = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
                "filter_test_accounts": True,
            },
        }

        hog_flow_with = {
            "name": "Test Flow With Filter",
            "status": "active",
            "actions": [trigger_action_with_filter],
        }

        response_with = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow_with)
        assert response_with.status_code == 201, response_with.json()

        # Bytecode should be in trigger.filters.bytecode
        trigger_filters = response_with.json()["trigger"]["filters"]
        bytecode_with = trigger_filters["bytecode"]

        # The bytecode should be longer and include the test account filter check
        assert len(bytecode_with) > len(bytecode_without), "Bytecode with filter_test_accounts should be longer"

        # Verify the bytecode includes the test account filter pattern
        # The pattern "%@posthog.com%" indicates the not_icontains check
        assert "%@posthog.com%" in bytecode_with, "Bytecode should include test account filter value"
        assert "email" in bytecode_with, "Bytecode should include email property check"
        assert "person" in bytecode_with, "Bytecode should include person property type"

    def test_hog_flow_draft_compiles_bytecode_for_complete_actions(self):
        hog_flow, action = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
            }
        )
        hog_flow["status"] = "draft"

        action["filters"] = {
            "properties": [{"key": "event", "type": "event_metadata", "value": ["custom_event"], "operator": "exact"}]
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)

        assert response.status_code == 201, response.json()
        flow = HogFlow.objects.get(pk=response.json()["id"])

        assert flow.trigger["filters"].get("bytecode") == ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11]

        assert flow.actions[1]["filters"].get("bytecode") == ["_H", 1, 32, "custom_event", 32, "event", 1, 1, 11]

        assert flow.actions[1]["config"]["inputs"] == {
            "url": {"order": 0, "value": "https://example.com", "bytecode": ["_H", 1, 32, "https://example.com"]}
        }

    def test_hog_flow_draft_to_active_compiles_bytecode(self):
        hog_flow, _ = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
            }
        )
        hog_flow["status"] = "draft"

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()
        flow_id = response.json()["id"]

        # Activate the draft — re-validation should compile bytecodes
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {"status": "active"},
        )
        assert response.status_code == 200, response.json()

        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.trigger["filters"].get("bytecode") == ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11]
        assert flow.actions[1]["config"]["inputs"] == {
            "url": {"order": 0, "value": "https://example.com", "bytecode": ["_H", 1, 32, "https://example.com"]}
        }

    def test_hog_flow_draft_partial_inputs_skips_input_bytecode(self):
        hog_flow, _ = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {},
            }
        )
        hog_flow["status"] = "draft"

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()

        flow = HogFlow.objects.get(pk=response.json()["id"])

        # Trigger filter bytecode should still compile even though action inputs are incomplete
        assert flow.trigger["filters"].get("bytecode") == ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11]

        # Action inputs should NOT have bytecode since required 'url' is missing
        # (is_valid() fails on the whole inputs serializer)
        assert flow.actions[1]["config"]["inputs"] == {}

    def _get_hog_flow_activity(self, flow_id: Optional[str] = None) -> list:
        params: dict = {"scope": "HogFlow", "page": 1, "limit": 20}
        if flow_id:
            params["item_id"] = flow_id
        activity = self.client.get(f"/api/projects/{self.team.pk}/activity_log", data=params)
        assert activity.status_code == status.HTTP_200_OK
        return activity.json().get("results")

    def test_create_hog_flow_logs_activity(self):
        hog_flow, _ = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
            }
        )
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        flow_id = response.json()["id"]
        flow_name = response.json()["name"]

        activity = self._get_hog_flow_activity(flow_id)
        assert len(activity) >= 1

        latest = activity[0]
        assert latest["activity"] == "created"
        assert latest["scope"] == "HogFlow"
        assert latest["item_id"] == flow_id
        assert latest["detail"]["name"] == flow_name
        assert latest["detail"]["type"] == "standard"

    def test_update_hog_flow_logs_activity(self):
        hog_flow, _ = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
            }
        )
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        flow_id = response.json()["id"]
        original_name = response.json()["name"]

        new_name = "Updated Flow Name"
        update_response = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{flow_id}", {"name": new_name})
        assert update_response.status_code == status.HTTP_200_OK, update_response.json()

        activity = self._get_hog_flow_activity(flow_id)
        assert len(activity) >= 2

        latest = activity[0]
        assert latest["activity"] == "updated"
        assert latest["scope"] == "HogFlow"
        assert latest["item_id"] == flow_id
        assert latest["detail"]["name"] == new_name
        changes = latest["detail"]["changes"]
        name_change = next((c for c in changes if c["field"] == "name"), None)
        assert name_change is not None
        assert name_change["before"] == original_name
        assert name_change["after"] == new_name

    def test_hog_flow_draft_allows_incomplete_actions(self):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }
        incomplete_action = {
            "id": "action_1",
            "name": "action_1",
            "type": "function",
            "config": {},
        }

        hog_flow = {
            "name": "Draft Flow",
            "status": "draft",
            "actions": [trigger_action, incomplete_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()
        assert response.json()["status"] == "draft"

    def test_hog_flow_active_rejects_incomplete_actions(self):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }
        incomplete_action = {
            "id": "action_1",
            "name": "action_1",
            "type": "function",
            "config": {},
        }

        hog_flow = {
            "name": "Active Flow",
            "status": "active",
            "actions": [trigger_action, incomplete_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 400, response.json()

    def test_hog_flow_retrieve_does_not_leak_between_teams(self):
        another_org = Organization.objects.create(name="other org")
        another_team = Team.objects.create(organization=another_org)
        another_user = User.objects.create_and_join(another_org, "other-hog-flow@example.com", password="")

        hog_flow, _ = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
            }
        )

        self.client.force_login(another_user)
        create_response = self.client.post(f"/api/projects/{another_team.id}/hog_flows", hog_flow)
        assert create_response.status_code == 201, create_response.json()
        flow_id = create_response.json()["id"]

        self.client.force_login(self.user)
        response = self.client.get(f"/api/projects/{another_team.id}/hog_flows/{flow_id}")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_hog_flow_create_does_not_leak_between_teams(self):
        another_org = Organization.objects.create(name="other org")
        another_team = Team.objects.create(organization=another_org)

        hog_flow, _ = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
            }
        )

        self.client.force_login(self.user)
        response = self.client.post(f"/api/projects/{another_team.id}/hog_flows", hog_flow)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_hog_flow_update_does_not_leak_between_teams(self):
        another_org = Organization.objects.create(name="other org")
        another_team = Team.objects.create(organization=another_org)
        another_user = User.objects.create_and_join(another_org, "other-hog-flow-update@example.com", password="")

        hog_flow, _ = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
            }
        )

        self.client.force_login(another_user)
        create_response = self.client.post(f"/api/projects/{another_team.id}/hog_flows", hog_flow)
        assert create_response.status_code == 201, create_response.json()
        flow_id = create_response.json()["id"]

        self.client.force_login(self.user)
        response = self.client.patch(
            f"/api/projects/{another_team.id}/hog_flows/{flow_id}",
            {"name": "updated by unauthorized user"},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_hog_flow_delete_does_not_leak_between_teams(self):
        another_org = Organization.objects.create(name="other org")
        another_team = Team.objects.create(organization=another_org)
        another_user = User.objects.create_and_join(another_org, "other-hog-flow-delete@example.com", password="")

        hog_flow, _ = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
            }
        )

        self.client.force_login(another_user)
        create_response = self.client.post(f"/api/projects/{another_team.id}/hog_flows", hog_flow)
        assert create_response.status_code == 201, create_response.json()
        flow_id = create_response.json()["id"]

        self.client.force_login(self.user)
        response = self.client.delete(f"/api/projects/{another_team.id}/hog_flows/{flow_id}")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_hog_flow_draft_invalid_can_be_archived(self):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }
        incomplete_action = {
            "id": "action_1",
            "name": "action_1",
            "type": "function",
            "config": {},
        }

        hog_flow = {
            "name": "Draft to Archive Flow",
            "status": "draft",
            "actions": [trigger_action, incomplete_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()
        flow_id = response.json()["id"]
        assert response.json()["status"] == "draft"

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {"status": "archived"},
        )
        assert response.status_code == 200, response.json()
        assert response.json()["status"] == "archived"

    def test_hog_flow_draft_to_active_rejects_incomplete(self):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }
        incomplete_action = {
            "id": "action_1",
            "name": "action_1",
            "type": "function",
            "config": {},
        }

        hog_flow = {
            "name": "Draft to Active Flow",
            "status": "draft",
            "actions": [trigger_action, incomplete_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()
        flow_id = response.json()["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {"status": "active"},
        )
        assert response.status_code == 400, response.json()

    def _create_flow(self, name: str = "Test Flow", flow_status: str = "draft") -> str:
        hog_flow, _ = self._create_hog_flow_with_action(
            {"template_id": "template-webhook", "inputs": {"url": {"value": "https://example.com"}}},
        )
        hog_flow["name"] = name
        hog_flow["status"] = flow_status
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()
        return response.json()["id"]

    def _archive_flow(self, flow_id: str) -> None:
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {"status": "archived"},
        )
        assert response.status_code == 200, response.json()

    def test_bulk_delete_archived_workflows(self):
        ids = [self._create_flow(name=f"Flow {i}") for i in range(3)]
        for fid in ids:
            self._archive_flow(fid)

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/bulk_delete",
            {"ids": ids},
        )
        assert response.status_code == 200, response.json()
        assert response.json()["deleted"] == 3
        assert HogFlow.objects.filter(id__in=ids).count() == 0

    @parameterized.expand(
        [
            ("draft",),
            ("active",),
        ]
    )
    def test_bulk_delete_skips_non_archived_workflows(self, flow_status):
        flow_id = self._create_flow(flow_status=flow_status)

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/bulk_delete",
            {"ids": [flow_id]},
        )
        assert response.status_code == 200, response.json()
        assert response.json()["deleted"] == 0
        assert HogFlow.objects.filter(id=flow_id).exists()

    def test_bulk_delete_mixed_statuses_only_deletes_archived(self):
        draft_id = self._create_flow(name="Draft", flow_status="draft")
        archived_id = self._create_flow(name="Archived", flow_status="draft")
        self._archive_flow(archived_id)

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/bulk_delete",
            {"ids": [draft_id, archived_id]},
        )
        assert response.status_code == 200, response.json()
        assert response.json()["deleted"] == 1
        assert HogFlow.objects.filter(id=draft_id).exists()
        assert not HogFlow.objects.filter(id=archived_id).exists()

    def test_bulk_delete_rejects_empty_ids(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/bulk_delete",
            {"ids": []},
        )
        assert response.status_code == 400

    def test_bulk_delete_rejects_missing_ids(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/bulk_delete",
            {},
        )
        assert response.status_code == 400

    def test_bulk_delete_rejects_invalid_uuids(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/bulk_delete",
            {"ids": ["not-a-uuid", "also-bad"]},
        )
        assert response.status_code == 400

    def test_bulk_delete_does_not_leak_between_teams(self):
        another_org = Organization.objects.create(name="other org")
        another_team = Team.objects.create(organization=another_org)
        another_user = User.objects.create_and_join(another_org, "other-bulk-delete@example.com", password="")

        self.client.force_login(another_user)
        hog_flow, _ = self._create_hog_flow_with_action(
            {"template_id": "template-webhook", "inputs": {"url": {"value": "https://example.com"}}},
        )
        create_response = self.client.post(f"/api/projects/{another_team.id}/hog_flows", hog_flow)
        assert create_response.status_code == 201
        flow_id = create_response.json()["id"]
        self.client.patch(f"/api/projects/{another_team.id}/hog_flows/{flow_id}", {"status": "archived"})

        self.client.force_login(self.user)
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/bulk_delete",
            {"ids": [flow_id]},
        )
        assert response.status_code == 200, response.json()
        assert response.json()["deleted"] == 0
        assert HogFlow.objects.filter(id=flow_id).exists()

    def _base_hog_flow_with_variables(self, variables):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }
        return {
            "name": "Test Flow",
            "actions": [trigger_action],
            "variables": variables,
        }

    @parameterized.expand(
        [
            (
                "unique_keys_accepted",
                [{"key": "name", "value": ""}, {"key": "email", "value": ""}],
                201,
                None,
            ),
            (
                "duplicate_keys_rejected",
                [{"key": "name", "value": ""}, {"key": "name", "value": "other"}],
                400,
                "Variable keys must be unique",
            ),
            (
                "exceeding_5kb_rejected",
                [{"key": f"var_{i}", "value": "x" * 1000} for i in range(6)],
                400,
                "Total size of variables definition must be less than 5KB",
            ),
            (
                "just_under_5kb_accepted",
                [{"key": f"v_{i:02d}", "value": "x" * 1200} for i in range(4)],
                201,
                None,
            ),
        ]
    )
    def test_variables_validation(self, _name, variables, expected_status, expected_error):
        hog_flow = self._base_hog_flow_with_variables(variables)
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == expected_status, response.json()
        if expected_error:
            assert response.json()["detail"] == expected_error


class TestHogFlowBlockedRuns(ClickhouseTestMixin, APIBaseTest):
    INCIDENT_WINDOW_TIMESTAMP = "2026-04-15 12:00:00.000000"

    def setUp(self):
        super().setUp()
        sync_template_to_db(webhook_template)
        from posthog.models.feature_flag import FeatureFlag

        FeatureFlag.objects.create(
            team=self.team,
            key="workflows-replay-blocked-runs",
            active=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
            created_by=self.user,
        )

    def _create_flow(self) -> str:
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }
        action = {
            "id": "action_1",
            "name": "action_1",
            "type": "function",
            "config": {"template_id": "template-webhook", "inputs": {"url": {"value": "https://example.com"}}},
        }
        hog_flow = {"name": "Test Flow", "actions": [trigger_action, action]}
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()["id"]

    def _uuidv7_like(self, embedded_at: Optional[datetime] = None) -> str:
        # Version '7' at position 15, RFC-4122 variant at position 20 (1-indexed,
        # matching ClickHouse substring offsets used by BLOCKED_RUNS_SQL). Default
        # embedded timestamp is 5 minutes before the block so generated rows pass
        # the SQL's proximity check.
        if embedded_at is None:
            embedded_at = self._incident_window_dt() - timedelta(minutes=5)
        ms = int(embedded_at.timestamp() * 1000)
        ts_hex = f"{ms:012x}"
        rand_hex = uuid_mod.uuid4().hex
        s = ts_hex + "7" + rand_hex[13:16] + "8" + rand_hex[17:32]
        return f"{s[:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:]}"

    def _uuidt_like(self) -> str:
        # Version nibble '0' at position 15 mimics PostHog's UUIDT, not strict uuidv7.
        u = list(str(uuid_mod.uuid4()))
        u[14] = "0"
        return "".join(u)

    def _wait_until_action_id(self) -> str:
        return f"action_wait_until_condition_{uuid_mod.uuid4().hex[:8]}"

    def _incident_window_dt(self) -> datetime:
        return datetime(2026, 4, 15, 12, 0, 0, tzinfo=UTC)

    def _parse_block_ts(self, ts_str: str) -> datetime:
        return datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=UTC)

    def _insert_blocked_log(
        self,
        flow_id: str,
        *,
        instance_id: Optional[str] = None,
        action_id: Optional[str] = None,
        event_uuid: Optional[str] = None,
        other_inv_id: Optional[str] = None,
        include_other_clause: bool = True,
        timestamp: Optional[str] = None,
    ) -> dict:
        # Defaults produce a row that matches the 2026-04 dedup incident bug fingerprint:
        # wait_until_condition action, blocked id is uuidv7, message cites a UUIDT "other".
        from posthog.clickhouse.client.execute import sync_execute
        from posthog.clickhouse.log_entries import INSERT_LOG_ENTRY_SQL

        resolved_action_id = action_id if action_id is not None else self._wait_until_action_id()
        resolved_event_uuid = event_uuid if event_uuid is not None else str(uuid_mod.uuid4())
        resolved_timestamp = timestamp if timestamp is not None else self.INCIDENT_WINDOW_TIMESTAMP
        if instance_id is not None:
            resolved_instance_id = instance_id
        else:
            block_dt = self._parse_block_ts(resolved_timestamp)
            resolved_instance_id = self._uuidv7_like(embedded_at=block_dt - timedelta(minutes=5))

        resolved_other_inv_id: Optional[str]
        if include_other_clause:
            resolved_other_inv_id = other_inv_id if other_inv_id is not None else self._uuidt_like()
            message = (
                f"[Action:{resolved_action_id}] Skipped: duplicate execution detected "
                f"for event {resolved_event_uuid}. "
                f"Another invocation ({resolved_other_inv_id}) already executed this action."
            )
        else:
            # Pre-2026-04-21 log format had no "Another invocation (<uuid>)" clause.
            resolved_other_inv_id = None
            message = (
                f"[Action:{resolved_action_id}] Skipped: duplicate execution detected for event {resolved_event_uuid}."
            )

        sync_execute(
            INSERT_LOG_ENTRY_SQL,
            {
                "team_id": self.team.pk,
                "log_source": "hog_flow",
                "log_source_id": flow_id,
                "instance_id": resolved_instance_id,
                "timestamp": resolved_timestamp,
                "level": "warn",
                "message": message,
            },
        )
        return {
            "instance_id": resolved_instance_id,
            "action_id": resolved_action_id,
            "event_uuid": resolved_event_uuid,
            "other_inv_id": resolved_other_inv_id,
            "timestamp": resolved_timestamp,
        }

    def test_blocked_runs_returns_parsed_results(self):
        flow_id = self._create_flow()
        action_id = self._wait_until_action_id()

        log_a = self._insert_blocked_log(flow_id, action_id=action_id)
        log_b = self._insert_blocked_log(flow_id, action_id=action_id)

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/blocked_runs")
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 2

        returned_instance_ids = {r["instance_id"] for r in results}
        assert returned_instance_ids == {log_a["instance_id"], log_b["instance_id"]}
        for result in results:
            assert result["action_id"] == action_id
            assert result["event_uuid"] is not None

    def test_blocked_runs_invalid_limit(self):
        flow_id = self._create_flow()

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/blocked_runs?limit=abc")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "limit must be an integer"

    def test_blocked_runs_empty_when_no_blocked_logs(self):
        flow_id = self._create_flow()

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/blocked_runs")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == []

    def test_blocked_runs_scoped_to_workflow(self):
        flow_a = self._create_flow()
        flow_b = self._create_flow()

        log_a = self._insert_blocked_log(flow_a)
        self._insert_blocked_log(flow_b)

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_a}/blocked_runs")
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["instance_id"] == log_a["instance_id"]

    @patch("posthog.api.hog_flow.bulk_replay_hog_flow_invocations")
    def test_replay_blocked_run_success(self, mock_bulk_replay):
        from posthog.models.event.util import create_event

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"succeeded": 1, "failed": 0}
        mock_bulk_replay.return_value = mock_response

        flow_id = self._create_flow()
        event_uuid = uuid_mod.uuid4()
        person_id = uuid_mod.uuid4()
        create_event(
            event_uuid=event_uuid,
            event="$pageview",
            team=self.team,
            distinct_id="user-1",
            properties={"url": "https://example.com"},
            person_id=person_id,
            person_properties={"email": "test@example.com"},
        )
        log = self._insert_blocked_log(flow_id, event_uuid=str(event_uuid))

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/replay_blocked_run",
            {"event_uuid": str(event_uuid), "action_id": log["action_id"], "instance_id": log["instance_id"]},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == "queued"

        mock_bulk_replay.assert_called_once()
        call_kwargs = mock_bulk_replay.call_args[1]
        items = call_kwargs["items"]
        assert len(items) == 1
        assert items[0]["action_id"] == log["action_id"]
        assert items[0]["instance_id"] == log["instance_id"]
        assert items[0]["clickhouse_event"]["uuid"] == str(event_uuid)
        assert items[0]["clickhouse_event"]["person_id"] == str(person_id)
        assert "person_properties" in items[0]["clickhouse_event"]

    def test_replay_blocked_run_invalid_instance_id(self):
        flow_id = self._create_flow()
        log = self._insert_blocked_log(flow_id)

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/replay_blocked_run",
            {"event_uuid": log["event_uuid"], "action_id": log["action_id"], "instance_id": "bogus-id"},
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "not found" in response.json()["error"]

    def test_replay_blocked_run_mismatched_event_uuid(self):
        flow_id = self._create_flow()
        log = self._insert_blocked_log(flow_id)

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/replay_blocked_run",
            {
                "event_uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "action_id": log["action_id"],
                "instance_id": log["instance_id"],
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "does not match" in response.json()["error"]

    def test_replay_blocked_run_missing_params(self):
        flow_id = self._create_flow()

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/replay_blocked_run",
            {"event_uuid": "550e8400-e29b-41d4-a716-446655440000"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/replay_blocked_run",
            {"action_id": "action_1"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_replay_blocked_run_event_not_found(self):
        flow_id = self._create_flow()
        log = self._insert_blocked_log(flow_id)

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/replay_blocked_run",
            {
                "event_uuid": log["event_uuid"],
                "action_id": log["action_id"],
                "instance_id": log["instance_id"],
            },
        )
        # event was never inserted into ClickHouse, so lookup returns None
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @patch("posthog.api.hog_flow.bulk_replay_hog_flow_invocations")
    def test_replay_all_blocked_runs_sends_bulk_request(self, mock_bulk_replay):
        from posthog.models.event.util import create_event

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"succeeded": 2, "failed": 0}
        mock_bulk_replay.return_value = mock_response

        flow_id = self._create_flow()
        action_id = self._wait_until_action_id()
        event_uuid_1 = uuid_mod.uuid4()
        event_uuid_2 = uuid_mod.uuid4()
        for eu in [event_uuid_1, event_uuid_2]:
            create_event(
                event_uuid=eu,
                event="$pageview",
                team=self.team,
                distinct_id="user-1",
                properties={},
                person_id=uuid_mod.uuid4(),
            )

        self._insert_blocked_log(flow_id, action_id=action_id, event_uuid=str(event_uuid_1))
        self._insert_blocked_log(flow_id, action_id=action_id, event_uuid=str(event_uuid_2))

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/replay_all_blocked_runs",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["succeeded"] == 2
        assert response.json()["failed"] == 0

        mock_bulk_replay.assert_called_once()
        call_kwargs = mock_bulk_replay.call_args[1]
        items = call_kwargs["items"]
        assert len(items) == 2
        assert all(item["clickhouse_event"]["uuid"] in [str(event_uuid_1), str(event_uuid_2)] for item in items)
        assert all(item["action_id"] == action_id for item in items)

    @patch("posthog.api.hog_flow.bulk_replay_hog_flow_invocations")
    def test_replay_all_skips_runs_with_missing_events(self, mock_bulk_replay):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"succeeded": 0, "failed": 0}
        mock_bulk_replay.return_value = mock_response

        flow_id = self._create_flow()
        # Logs without backing ClickHouse events: replay must skip these so we don't
        # send invocations the executor would 404 on.
        self._insert_blocked_log(flow_id)
        self._insert_blocked_log(flow_id)

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/replay_all_blocked_runs",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["skipped"] == 2

        mock_bulk_replay.assert_not_called()

    def test_replay_all_empty_when_no_blocked_runs(self):
        flow_id = self._create_flow()

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/replay_all_blocked_runs",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"succeeded": 0, "failed": 0, "skipped": 0}

    def test_blocked_runs_returns_empty_when_feature_flag_disabled(self):
        from posthog.models.feature_flag import FeatureFlag

        FeatureFlag.objects.filter(team=self.team, key="workflows-replay-blocked-runs").update(active=False)

        flow_id = self._create_flow()
        self._insert_blocked_log(flow_id)

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/blocked_runs")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == []

    def test_replay_blocked_run_returns_403_when_feature_flag_disabled(self):
        from posthog.models.feature_flag import FeatureFlag

        FeatureFlag.objects.filter(team=self.team, key="workflows-replay-blocked-runs").update(active=False)

        flow_id = self._create_flow()
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/replay_blocked_run",
            {"event_uuid": "550e8400-e29b-41d4-a716-446655440000", "action_id": "action_1", "instance_id": "inv-001"},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_blocked_runs_pagination(self):
        flow_id = self._create_flow()
        for _ in range(3):
            self._insert_blocked_log(flow_id)

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/blocked_runs?limit=2&offset=0")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["results"]) == 2
        assert data["has_next"] is True

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/blocked_runs?limit=2&offset=2")
        data = response.json()
        assert len(data["results"]) == 1
        assert data["has_next"] is False

    # bug-fingerprint filter: reject legitimate dedupes so they are not replayed

    def test_blocked_runs_excludes_uuidt_blocked_instance_id(self):
        # Both invocations in UUIDT format = classifier's "two distinct UUIDT" verdict,
        # a genuine dedup catch. Must NOT be replayed.
        flow_id = self._create_flow()

        self._insert_blocked_log(flow_id, instance_id=self._uuidt_like())
        valid = self._insert_blocked_log(flow_id)

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/blocked_runs")
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["instance_id"] == valid["instance_id"]

    def test_blocked_runs_excludes_uuidv7_in_another_invocation_clause(self):
        # Both ids in uuidv7 = wait-through ghost (id rewritten on both sides). Too
        # ambiguous to safely replay.
        flow_id = self._create_flow()

        self._insert_blocked_log(flow_id, other_inv_id=self._uuidv7_like())
        valid = self._insert_blocked_log(flow_id)

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/blocked_runs")
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["instance_id"] == valid["instance_id"]

    def test_blocked_runs_includes_pre_4_21_format_without_another_invocation(self):
        # Pre-2026-04-21 messages omitted "Another invocation (<uuid>)". These rows
        # must still be included when the blocked id is uuidv7.
        flow_id = self._create_flow()

        pre = self._insert_blocked_log(flow_id, include_other_clause=False)
        uuidt_pre = self._insert_blocked_log(flow_id, instance_id=self._uuidt_like(), include_other_clause=False)

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/blocked_runs")
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["instance_id"] == pre["instance_id"]
        assert uuidt_pre["instance_id"] not in {r["instance_id"] for r in results}

    def test_blocked_runs_excludes_timestamps_outside_incident_window(self):
        # Dedup only existed between 2026-03-30 and 2026-04-22.
        flow_id = self._create_flow()

        self._insert_blocked_log(flow_id, timestamp="2026-03-29 23:59:59.000000")
        self._insert_blocked_log(flow_id, timestamp="2026-04-23 00:00:01.000000")
        valid = self._insert_blocked_log(flow_id, timestamp="2026-04-10 12:00:00.000000")

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/blocked_runs")
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["instance_id"] == valid["instance_id"]

    def test_blocked_runs_full_fingerprint_discrimination(self):
        flow_id = self._create_flow()

        bug_rows = [
            self._insert_blocked_log(flow_id),
            self._insert_blocked_log(flow_id, include_other_clause=False),
        ]

        legit_rows = [
            self._insert_blocked_log(flow_id, instance_id=self._uuidt_like()),
            self._insert_blocked_log(flow_id, other_inv_id=self._uuidv7_like()),
            self._insert_blocked_log(flow_id, action_id=f"action_function_email_{uuid_mod.uuid4().hex[:8]}"),
            self._insert_blocked_log(flow_id, timestamp="2026-03-29 12:00:00.000000"),
        ]

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/blocked_runs")
        returned = {r["instance_id"] for r in response.json()["results"]}

        assert returned == {row["instance_id"] for row in bug_rows}
        for legit in legit_rows:
            assert legit["instance_id"] not in returned, (
                f"Legit dedupe {legit['instance_id']} should not be returned for replay"
            )

    # uuidv7 embedded-timestamp proximity: bounded by the wait_until_condition re-check interval

    def test_blocked_runs_excludes_when_uuidv7_timestamp_too_old(self):
        # The wait_until_condition re-check interval is 10 min, so a real bug rewrite
        # cannot have an embedded timestamp more than 15 min before the block.
        flow_id = self._create_flow()
        block_dt = self._parse_block_ts(self.INCIDENT_WINDOW_TIMESTAMP)
        old_uuidv7 = self._uuidv7_like(embedded_at=block_dt - timedelta(hours=1))

        self._insert_blocked_log(flow_id, instance_id=old_uuidv7)

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/blocked_runs")
        assert response.json()["results"] == []

    def test_blocked_runs_excludes_when_uuidv7_timestamp_in_the_future(self):
        # A uuidv7 cannot have been minted after the block that referenced it.
        flow_id = self._create_flow()
        block_dt = self._parse_block_ts(self.INCIDENT_WINDOW_TIMESTAMP)
        future_uuidv7 = self._uuidv7_like(embedded_at=block_dt + timedelta(minutes=10))

        self._insert_blocked_log(flow_id, instance_id=future_uuidv7)

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/blocked_runs")
        assert response.json()["results"] == []

    def test_blocked_runs_includes_uuidv7_timestamp_at_window_boundary(self):
        flow_id = self._create_flow()
        block_dt = self._parse_block_ts(self.INCIDENT_WINDOW_TIMESTAMP)
        included = self._uuidv7_like(embedded_at=block_dt - timedelta(minutes=14, seconds=30))
        excluded = self._uuidv7_like(embedded_at=block_dt - timedelta(minutes=16))

        self._insert_blocked_log(flow_id, instance_id=included)
        self._insert_blocked_log(flow_id, instance_id=excluded)

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/blocked_runs")
        returned = {r["instance_id"] for r in response.json()["results"]}
        assert included in returned
        assert excluded not in returned

    # end-to-end shapes observed during the 2026-04 dedup incident

    def test_e2e_burst_of_bug_blocks_simultaneous_pause_resume(self):
        # Batch trigger fans out: all invocations pause, all re-queues rewrite ids
        # together, all re-checks hit dedup at the same minute. Verifies the SQL
        # handles a tight burst (identical timestamp on many rows).
        flow_id = self._create_flow()
        action_id = self._wait_until_action_id()
        burst_block_ts = "2026-04-15 09:56:00.000000"
        burst_dt = self._parse_block_ts(burst_block_ts)
        re_queue_dt = burst_dt - timedelta(minutes=10)

        burst_size = 30
        inserted_ids = []
        for _ in range(burst_size):
            log = self._insert_blocked_log(
                flow_id,
                action_id=action_id,
                timestamp=burst_block_ts,
                instance_id=self._uuidv7_like(embedded_at=re_queue_dt),
                include_other_clause=False,  # pre-2026-04-21 message format
            )
            inserted_ids.append(log["instance_id"])

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/blocked_runs?limit=1000")
        returned = {r["instance_id"] for r in response.json()["results"]}
        assert returned == set(inserted_ids)
        assert len(returned) == burst_size

    def test_e2e_high_volume_bug_workflow_with_minor_ghost_noise(self):
        flow_id = self._create_flow()
        action_id = self._wait_until_action_id()

        bug_rows = [
            self._insert_blocked_log(flow_id, action_id=action_id, include_other_clause=False) for _ in range(50)
        ]

        legit_ghost_rows = [
            self._insert_blocked_log(flow_id, action_id=action_id, instance_id=self._uuidt_like()),
            self._insert_blocked_log(flow_id, action_id=action_id, instance_id=self._uuidt_like()),
        ]

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/blocked_runs?limit=1000")
        returned = {r["instance_id"] for r in response.json()["results"]}

        for row in bug_rows:
            assert row["instance_id"] in returned
        for row in legit_ghost_rows:
            assert row["instance_id"] not in returned

    def test_e2e_mixed_pre_and_post_4_21_message_formats(self):
        # The bug spanned a logging refactor: early blocks have generic messages,
        # later blocks include "Another invocation (<uuid>)". Both shapes must match.
        flow_id = self._create_flow()
        action_id = self._wait_until_action_id()

        pre_4_21_rows = [
            self._insert_blocked_log(
                flow_id,
                action_id=action_id,
                include_other_clause=False,
                timestamp="2026-04-05 10:00:00.000000",
            )
            for _ in range(10)
        ]
        post_4_21_rows = [
            self._insert_blocked_log(
                flow_id,
                action_id=action_id,
                include_other_clause=True,
                timestamp="2026-04-21 10:00:00.000000",
            )
            for _ in range(10)
        ]

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/blocked_runs?limit=100")
        returned = {r["instance_id"] for r in response.json()["results"]}
        assert returned == {row["instance_id"] for row in pre_4_21_rows + post_4_21_rows}

    def test_e2e_workflow_with_mixed_action_types_keeps_only_wait_until(self):
        # Workflows hit dedup on multiple action types; only wait_until_condition rows
        # are bug-affected, the replay tool must filter the rest out.
        flow_id = self._create_flow()
        wait_action_id = self._wait_until_action_id()

        bug_rows = [self._insert_blocked_log(flow_id, action_id=wait_action_id) for _ in range(2)]

        for prefix in ("action_delay_", "action_function_", "action_function_email_", "action_conditional_branch_"):
            for _ in range(30):
                self._insert_blocked_log(flow_id, action_id=f"{prefix}{uuid_mod.uuid4().hex[:8]}")

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/blocked_runs?limit=200")
        returned = {r["instance_id"] for r in response.json()["results"]}
        assert returned == {row["instance_id"] for row in bug_rows}

    def test_e2e_replayed_runs_drop_off_the_list(self):
        # The replay handler writes a "[Replay] Queued" log marker per instance_id.
        # Subsequent list calls must exclude already-replayed runs.
        from posthog.clickhouse.client.execute import sync_execute
        from posthog.clickhouse.log_entries import INSERT_LOG_ENTRY_SQL

        flow_id = self._create_flow()
        already_replayed = self._insert_blocked_log(flow_id)
        still_pending = self._insert_blocked_log(flow_id)

        sync_execute(
            INSERT_LOG_ENTRY_SQL,
            {
                "team_id": self.team.pk,
                "log_source": "hog_flow",
                "log_source_id": flow_id,
                "instance_id": already_replayed["instance_id"],
                "timestamp": self.INCIDENT_WINDOW_TIMESTAMP,
                "level": "info",
                "message": (
                    f"[Replay] Queued replay for event {already_replayed['event_uuid']} "
                    f"from action {already_replayed['action_id']}."
                ),
            },
        )

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/blocked_runs")
        returned = {r["instance_id"] for r in response.json()["results"]}
        assert returned == {still_pending["instance_id"]}

    def test_e2e_pagination_returns_stable_results_across_pages(self):
        # Distinct timestamps per row so ORDER BY timestamp DESC is deterministic
        # and pages don't overlap.
        flow_id = self._create_flow()
        action_id = self._wait_until_action_id()
        base_dt = self._parse_block_ts(self.INCIDENT_WINDOW_TIMESTAMP)
        total_rows = 25

        inserted_ids = set()
        for i in range(total_rows):
            row_dt = base_dt - timedelta(seconds=i)
            log = self._insert_blocked_log(
                flow_id,
                action_id=action_id,
                timestamp=row_dt.strftime("%Y-%m-%d %H:%M:%S.%f"),
            )
            inserted_ids.add(log["instance_id"])

        page_size = 10
        seen: set[str] = set()
        offset = 0
        while True:
            response = self.client.get(
                f"/api/projects/{self.team.id}/hog_flows/{flow_id}/blocked_runs?limit={page_size}&offset={offset}"
            )
            data = response.json()
            page_ids = {r["instance_id"] for r in data["results"]}
            assert page_ids.isdisjoint(seen), "page contains an instance_id already seen on a prior page"
            seen.update(page_ids)
            if not data["has_next"]:
                break
            offset += page_size

        assert seen == inserted_ids
