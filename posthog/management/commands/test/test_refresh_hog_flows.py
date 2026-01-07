from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command

from posthog.management.commands.refresh_hog_flows import remove_event_filters_from_conditionals
from posthog.models import Team
from posthog.models.hog_flow.hog_flow import HogFlow


class TestRefreshHogFlows(BaseTest):
    def setUp(self):
        super().setUp()

        # Create additional teams for testing
        self.team2 = Team.objects.create(organization=self.organization, name="Test Team 2")

        # Create HogFlows for testing with proper trigger actions
        with patch("posthog.models.hog_flow.hog_flow.reload_hog_flows_on_workers"):
            trigger_config_1 = {
                "type": "event",
                "filters": {
                    "events": [{"id": "test_event_1", "name": "test_event_1", "type": "events"}],
                    "source": "events",
                },
            }
            self.hog_flow1 = HogFlow.objects.create(
                team=self.team,
                name="Test Flow 1",
                status=HogFlow.State.ACTIVE,
                description="Test Description 1",
                trigger=trigger_config_1,
                edges=[],
                actions=[{"id": "trigger_node", "name": "Trigger", "type": "trigger", "config": trigger_config_1}],
                version=1,
            )

            trigger_config_2 = {
                "type": "event",
                "filters": {
                    "events": [{"id": "test_event_2", "name": "test_event_2", "type": "events"}],
                    "source": "events",
                },
            }
            self.hog_flow2 = HogFlow.objects.create(
                team=self.team,
                name="Test Flow 2",
                status=HogFlow.State.DRAFT,
                description="Test Description 2",
                trigger=trigger_config_2,
                edges=[],
                actions=[{"id": "trigger_node", "name": "Trigger", "type": "trigger", "config": trigger_config_2}],
                version=1,
            )

            trigger_config_3 = {
                "type": "event",
                "filters": {
                    "events": [{"id": "test_event_3", "name": "test_event_3", "type": "events"}],
                    "source": "events",
                },
            }
            self.hog_flow3 = HogFlow.objects.create(
                team=self.team2,
                name="Test Flow 3",
                status=HogFlow.State.ACTIVE,
                description="Test Description 3",
                trigger=trigger_config_3,
                edges=[],
                actions=[{"id": "trigger_node", "name": "Trigger", "type": "trigger", "config": trigger_config_3}],
                version=1,
            )

            # Create archived flow - should also be processed
            trigger_config_archived = {
                "type": "event",
                "filters": {
                    "events": [{"id": "archived_event", "name": "archived_event", "type": "events"}],
                    "source": "events",
                },
            }
            self.archived_flow = HogFlow.objects.create(
                team=self.team,
                name="Archived Flow",
                status=HogFlow.State.ARCHIVED,
                description="Archived Flow Description",
                trigger=trigger_config_archived,
                edges=[],
                actions=[
                    {"id": "trigger_node", "name": "Trigger", "type": "trigger", "config": trigger_config_archived}
                ],
                version=1,
            )

    @patch("posthog.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_refresh_all_hog_flows(self, mock_reload):
        """Test refreshing all HogFlows across all teams."""

        out = StringIO()
        call_command("refresh_hog_flows", stdout=out)

        # Should have refreshed all 4 flows (including archived)
        assert mock_reload.call_count == 4

        output = out.getvalue()
        assert "Found 4 HogFlows to process" in output
        assert "Processed: 4" in output
        assert "Updated: 4" in output
        assert "Errors: 0" in output

    @patch("posthog.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_refresh_by_team_id(self, mock_reload):
        """Test refreshing HogFlows for a specific team."""

        out = StringIO()
        call_command("refresh_hog_flows", team_id=self.team.id, stdout=out)

        # Should have refreshed flows from team1 (hog_flow1, hog_flow2, archived_flow)
        assert mock_reload.call_count == 3

        output = out.getvalue()
        assert f"Processing HogFlows for team: {self.team.id}" in output
        assert "Found 3 HogFlows to process" in output
        assert "Updated: 3" in output

    @patch("posthog.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_refresh_by_hog_flow_id(self, mock_reload):
        """Test refreshing a specific HogFlow by ID."""

        out = StringIO()
        call_command("refresh_hog_flows", hog_flow_id=str(self.hog_flow1.id), stdout=out)

        # Should have refreshed only the specific flow
        assert mock_reload.call_count == 1

        output = out.getvalue()
        assert f"Processing single HogFlow: {self.hog_flow1.id}" in output
        assert "Found 1 HogFlows to process" in output
        assert "Updated: 1" in output

    @patch("posthog.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_nonexistent_team_id(self, mock_reload):
        """Test handling of nonexistent team ID."""

        out = StringIO()
        call_command("refresh_hog_flows", team_id=99999, stdout=out)

        assert mock_reload.call_count == 0

        output = out.getvalue()
        assert "Found 0 HogFlows to process" in output
        assert "No HogFlows found matching criteria" in output

    @patch("posthog.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_nonexistent_hog_flow_id(self, mock_reload):
        """Test handling of nonexistent HogFlow ID."""

        out = StringIO()
        # Use a valid UUID format that doesn't exist
        nonexistent_uuid = "00000000-0000-0000-0000-000000000000"
        call_command("refresh_hog_flows", hog_flow_id=nonexistent_uuid, stdout=out)

        assert mock_reload.call_count == 0

        output = out.getvalue()
        assert "Found 0 HogFlows to process" in output
        assert "No HogFlows found matching criteria" in output

    @patch("posthog.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_page_size_option(self, mock_reload):
        """Test that the page_size option works correctly."""

        out = StringIO()
        # Set page size to 2, should process all flows but in multiple pages
        call_command("refresh_hog_flows", page_size=2, stdout=out)

        # Should still refresh all 4 flows
        assert mock_reload.call_count == 4

        output = out.getvalue()
        # Should see multiple page processing messages
        assert "Processing page 1/2" in output
        assert "Processing page 2/2" in output
        assert "Processed: 4" in output
        assert "Updated: 4" in output

    @patch("posthog.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_error_handling(self, mock_reload):
        """Test error handling when a flow fails to save."""

        # Track which save calls we've seen
        save_call_count = [0]
        original_save = HogFlow.save
        test_instance = self

        def mock_save_method(self):
            save_call_count[0] += 1
            # Raise exception only for the first flow
            if self.id == test_instance.hog_flow1.id:
                raise Exception("Test exception")
            # Call original save for other flows
            return original_save(self)

        # Patch the save method
        with patch.object(HogFlow, "save", mock_save_method):
            out = StringIO()
            call_command("refresh_hog_flows", stdout=out)

            # Should have attempted to process all 4 flows
            # But only 3 should succeed
            output = out.getvalue()
            assert "Found 4 HogFlows to process" in output
            assert "Processed: 4" in output
            assert "Updated: 3" in output  # 3 successful
            assert "Errors: 1" in output  # 1 failure
            assert "Check logs for details on 1 errors encountered" in output

    @patch("posthog.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_bytecode_regeneration_on_conditional_branch(self, mock_reload):
        """Test that bytecode is regenerated when a conditional branch action is missing bytecode."""

        # Create a HogFlow with conditional branch that has filters but no bytecode
        actions = [
            {
                "id": "trigger_node",
                "name": "Trigger",
                "type": "trigger",
                "config": {
                    "type": "event",
                    "filters": {
                        "events": [{"id": "$pageview", "name": "$pageview", "type": "events"}],
                        "source": "events",
                        "actions": [],
                        "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
                    },
                },
            },
            {
                "id": "action_conditional_branch_test",
                "name": "Conditional branch",
                "type": "conditional_branch",
                "config": {
                    "conditions": [
                        {
                            "filters": {
                                "events": [{"id": "$pageview", "name": "$pageview", "type": "events"}],
                                "source": "events",
                                # Intentionally missing bytecode - should be regenerated
                                "properties": [
                                    {"key": "$browser", "type": "event", "value": "is_set", "operator": "is_set"}
                                ],
                            }
                        }
                    ]
                },
            },
            {"id": "exit_node", "name": "Exit", "type": "exit", "config": {"reason": "Default exit"}},
        ]

        edges = [
            {"to": "action_conditional_branch_test", "from": "trigger_node", "type": "continue"},
            {"to": "exit_node", "from": "action_conditional_branch_test", "type": "continue"},
        ]

        trigger = {
            "type": "event",
            "filters": {
                "events": [{"id": "$pageview", "name": "$pageview", "type": "events"}],
                "source": "events",
                "actions": [],
                "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
            },
        }

        # Create the flow with missing bytecode in conditional branch
        test_flow = HogFlow.objects.create(
            team=self.team,
            name="Test Flow with Missing Bytecode",
            status=HogFlow.State.ACTIVE,
            trigger=trigger,
            edges=edges,
            actions=actions,
            version=1,
        )

        # Verify that the conditional branch initially has no bytecode
        initial_actions = test_flow.actions
        conditional_branch = next(a for a in initial_actions if a["type"] == "conditional_branch")
        assert "bytecode" not in conditional_branch["config"]["conditions"][0]["filters"]

        out = StringIO()
        call_command("refresh_hog_flows", hog_flow_id=str(test_flow.id), stdout=out)

        # Refresh the flow from database
        test_flow.refresh_from_db()

        # Check that bytecode was generated for the conditional branch
        updated_actions = test_flow.actions
        updated_conditional_branch = next(a for a in updated_actions if a["type"] == "conditional_branch")

        # After save, the bytecode should be generated
        assert "bytecode" in updated_conditional_branch["config"]["conditions"][0]["filters"]
        bytecode = updated_conditional_branch["config"]["conditions"][0]["filters"]["bytecode"]
        assert isinstance(bytecode, list)
        assert len(bytecode) > 0

        # Verify the command output
        output = out.getvalue()
        assert "Found 1 HogFlows to process" in output
        assert "Updated: 1" in output
        assert "Errors: 0" in output

    def test_remove_event_filters_from_single_condition(self):
        actions = [
            {
                "id": "action_conditional_branch_test",
                "name": "Conditional branch",
                "type": "conditional_branch",
                "config": {
                    "conditions": [
                        {
                            "filters": {
                                "events": [{"id": "$pageview", "name": "$pageview", "type": "events"}],
                                "source": "events",
                                "properties": [
                                    {"key": "$browser", "type": "event", "value": "is_set", "operator": "is_set"}
                                ],
                            }
                        }
                    ]
                },
            }
        ]
        updated = remove_event_filters_from_conditionals(actions)
        filters = updated[0]["config"]["conditions"][0]["filters"]
        assert "events" not in filters
        assert filters["source"] == "events"
        assert filters["properties"] == [{"key": "$browser", "type": "event", "value": "is_set", "operator": "is_set"}]

    def test_remove_event_filters_does_not_fail_if_no_events(self):
        actions = [
            {
                "id": "action_conditional_branch_test",
                "name": "Conditional branch",
                "type": "conditional_branch",
                "config": {
                    "conditions": [
                        {
                            "filters": {
                                "source": "events",
                                "properties": [
                                    {"key": "$browser", "type": "event", "value": "is_set", "operator": "is_set"}
                                ],
                            }
                        }
                    ]
                },
            }
        ]
        updated = remove_event_filters_from_conditionals(actions)
        filters = updated[0]["config"]["conditions"][0]["filters"]
        assert "events" not in filters
        assert filters["source"] == "events"
        assert filters["properties"] == [{"key": "$browser", "type": "event", "value": "is_set", "operator": "is_set"}]

    def test_remove_event_filters_multiple_conditions_and_actions(self):
        actions = [
            {
                "id": "action_conditional_branch_test",
                "name": "Conditional branch",
                "type": "conditional_branch",
                "config": {
                    "conditions": [
                        {"filters": {"events": [{"id": "a"}], "source": "events"}},
                        {"filters": {"source": "events"}},
                    ]
                },
            },
            {
                "id": "other_action",
                "name": "Other",
                "type": "exit",
                "config": {},
            },
        ]
        updated = remove_event_filters_from_conditionals(actions)
        cond1 = updated[0]["config"]["conditions"][0]["filters"]
        cond2 = updated[0]["config"]["conditions"][1]["filters"]
        assert "events" not in cond1
        assert "events" not in cond2
        assert cond1 == {"source": "events"}
        assert cond2 == {"source": "events"}
