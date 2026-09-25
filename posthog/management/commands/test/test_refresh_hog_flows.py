from io import StringIO
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command

from parameterized import parameterized

from posthog.cdp.filters import RUNTIME_CONTRACT
from posthog.models import Team

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow


class TestRefreshHogFlows(BaseTest):
    def setUp(self):
        super().setUp()

        # Create additional teams for testing
        self.team2 = Team.objects.create(organization=self.organization, name="Test Team 2")

        # Create HogFlows for testing with proper trigger actions
        with patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers"):
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

    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_refresh_all_hog_flows(self, mock_reload):
        """Test refreshing all HogFlows across all teams."""

        out = StringIO()
        call_command("refresh_hog_flows", stdout=out)

        # Should have refreshed all 4 flows (including archived)
        assert mock_reload.call_count == 4

        output = out.getvalue()
        self.assertIn("Found 4 HogFlows to process", output)
        self.assertIn("Processed: 4", output)
        self.assertIn("Updated: 4", output)
        self.assertIn("Errors: 0", output)

    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_refresh_by_team_id(self, mock_reload):
        """Test refreshing HogFlows for a specific team."""

        out = StringIO()
        call_command("refresh_hog_flows", team_id=self.team.id, stdout=out)

        # Should have refreshed flows from team1 (hog_flow1, hog_flow2, archived_flow)
        assert mock_reload.call_count == 3

        output = out.getvalue()
        self.assertIn(f"Processing HogFlows for team: {self.team.id}", output)
        self.assertIn("Found 3 HogFlows to process", output)
        self.assertIn("Updated: 3", output)

    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_refresh_by_hog_flow_id(self, mock_reload):
        """Test refreshing a specific HogFlow by ID."""

        out = StringIO()
        call_command("refresh_hog_flows", hog_flow_id=str(self.hog_flow1.id), stdout=out)

        # Should have refreshed only the specific flow
        assert mock_reload.call_count == 1

        output = out.getvalue()
        self.assertIn(f"Processing single HogFlow: {self.hog_flow1.id}", output)
        self.assertIn("Found 1 HogFlows to process", output)
        self.assertIn("Updated: 1", output)

    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_nonexistent_team_id(self, mock_reload):
        """Test handling of nonexistent team ID."""

        out = StringIO()
        call_command("refresh_hog_flows", team_id=99999, stdout=out)

        assert mock_reload.call_count == 0

        output = out.getvalue()
        self.assertIn("Found 0 HogFlows to process", output)
        self.assertIn("No HogFlows found matching criteria", output)

    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_nonexistent_hog_flow_id(self, mock_reload):
        """Test handling of nonexistent HogFlow ID."""

        out = StringIO()
        # Use a valid UUID format that doesn't exist
        nonexistent_uuid = "00000000-0000-0000-0000-000000000000"
        call_command("refresh_hog_flows", hog_flow_id=nonexistent_uuid, stdout=out)

        assert mock_reload.call_count == 0

        output = out.getvalue()
        self.assertIn("Found 0 HogFlows to process", output)
        self.assertIn("No HogFlows found matching criteria", output)

    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_page_size_option(self, mock_reload):
        """Test that the page_size option works correctly."""

        out = StringIO()
        # Set page size to 2, should process all flows but in multiple pages
        call_command("refresh_hog_flows", page_size=2, stdout=out)

        # Should still refresh all 4 flows
        assert mock_reload.call_count == 4

        output = out.getvalue()
        # Should see multiple page processing messages
        self.assertIn("Processing page 1/2", output)
        self.assertIn("Processing page 2/2", output)
        self.assertIn("Processed: 4", output)
        self.assertIn("Updated: 4", output)

    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
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
            self.assertIn("Found 4 HogFlows to process", output)
            self.assertIn("Processed: 4", output)
            self.assertIn("Updated: 3", output)  # 3 successful
            self.assertIn("Errors: 1", output)  # 1 failure
            self.assertIn("Check logs for details on 1 errors encountered", output)

    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_keeps_an_edit_made_to_a_workflow_while_the_run_is_in_progress(self, mock_reload):
        first_saved: list[str] = []

        def turn_off_the_rest_once(team_id: int, hog_flow_ids: list[str]) -> None:
            if not first_saved:
                first_saved.extend(hog_flow_ids)
                HogFlow.objects.exclude(id__in=hog_flow_ids).update(status=HogFlow.State.DRAFT)

        mock_reload.side_effect = turn_off_the_rest_once
        call_command("refresh_hog_flows", stdout=StringIO())

        statuses = set(HogFlow.objects.exclude(id__in=first_saved).values_list("status", flat=True))
        assert statuses == {HogFlow.State.DRAFT}

    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_refuses_a_conditional_branch_carrying_event_filters(self, mock_reload):
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
        self.assertNotIn("bytecode", conditional_branch["config"]["conditions"][0]["filters"])

        out = StringIO()
        call_command("refresh_hog_flows", hog_flow_id=str(test_flow.id), stdout=out)

        # Refresh the flow from database
        test_flow.refresh_from_db()

        # The validator refuses event filters in a conditional, so the flow cannot be re-saved.
        branch = next(a for a in test_flow.actions if a["type"] == "conditional_branch")
        assert branch["config"]["conditions"][0]["filters"]["events"] == [
            {"id": "$pageview", "name": "$pageview", "type": "events"}
        ]

        output = out.getvalue()
        self.assertIn("Found 1 HogFlows to process", output)
        self.assertIn(f"workflow {test_flow.id}", output)
        self.assertIn("Updated: 0", output)
        self.assertIn("Errors: 1", output)

    def _unstamped(self, trigger_filters: dict[str, Any], conditions: list[dict[str, Any]] | None = None) -> HogFlow:
        trigger_config = {"type": "event", "filters": trigger_filters}
        actions: list[dict[str, Any]] = [
            {"id": "trigger_node", "name": "trigger", "type": "trigger", "config": trigger_config},
            {"id": "exit_node", "name": "exit", "type": "exit", "config": {}},
        ]
        if conditions is not None:
            actions.insert(
                1,
                {
                    "id": "branch",
                    "name": "branch",
                    "type": "conditional_branch",
                    "config": {"conditions": conditions},
                },
            )
        flow = HogFlow.objects.create(
            team=self.team,
            name="Saved before stamping",
            status="active",
            trigger=trigger_config,
            actions=actions,
            edges=[],
            exit_condition="exit_only_at_end",
        )
        return HogFlow.objects.get(pk=flow.pk)

    @parameterized.expand([("dry_run", True), ("real_run", False)])
    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_stamps_the_trigger_filters_of_a_workflow(self, _name, dry_run, mock_reload):
        flow = self._unstamped({"events": [{"id": "$pageview", "type": "events"}]})
        assert "bytecode_contract" not in (flow.trigger or {})["filters"]

        out = StringIO()
        call_command("refresh_hog_flows", hog_flow_id=str(flow.id), dry_run=dry_run, stdout=out)

        flow.refresh_from_db()
        stamped = (flow.trigger or {}).get("filters", {}).get("bytecode_contract")
        assert stamped == (None if dry_run else RUNTIME_CONTRACT)
        assert ("Dry run" in out.getvalue()) is dry_run
        assert ("Would update: 1" if dry_run else "Updated: 1") in out.getvalue()

    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_names_a_workflow_that_no_longer_validates(self, mock_reload):
        # A count alone cannot be acted on: the run has to say which workflow to look at.
        flow = self._unstamped({"properties": [{"type": "hogql", "key": "nosuch.thing"}]})

        out = StringIO()
        call_command("refresh_hog_flows", hog_flow_id=str(flow.id), stdout=out)

        flow.refresh_from_db()
        assert "bytecode_contract" not in (flow.trigger or {})["filters"]
        assert f"workflow {flow.id}" in out.getvalue()
        assert "Errors: 1" in out.getvalue()
