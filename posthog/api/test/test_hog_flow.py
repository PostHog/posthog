from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES
from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.cdp.templates.slack.template_slack import template as template_slack
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

    def test_hog_flow_function_validation(self):
        hog_flow, action = self._create_hog_flow_with_action(
            {
                "template_id": "missing",
                "inputs": {},
            }
        )

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
            mock_get_user_blast_radius.return_value = (4, 10)

            response = self.client.post(
                f"/api/projects/{self.team.id}/hog_flows/user_blast_radius",
                {"filters": {"properties": []}},
            )

        assert response.status_code == 200, response.json()
        assert response.json() == {"users_affected": 4, "total_users": 10}

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
    def test_hog_flow_batch_jobs_endpoint_creates_job(self, mock_create_invocation):
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

    def test_hog_flow_batch_jobs_endpoint_nonexistent_flow(self):
        batch_job_data = {"variables": [{"key": "first_name", "value": "Test"}]}

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows/99999/batch_jobs", batch_job_data)

        assert response.status_code == 404, response.json()

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
