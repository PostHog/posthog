from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command

from posthog.management.commands import backfill_workflows_slack_integration as backfill
from posthog.management.commands.backfill_workflows_slack_integration import _rewrite_slack_workspace_in_actions
from posthog.models import Team

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow


def _slack_action(action_id: str, slack_workspace_value: int | None) -> dict:
    inputs: dict = {
        "channel": {"value": "C123"},
    }
    if slack_workspace_value is not None:
        inputs["slack_workspace"] = {"order": 0, "value": slack_workspace_value, "templating": "hog"}
    return {
        "id": action_id,
        "name": "Slack",
        "type": "function",
        "config": {
            "template_id": "template-slack",
            "inputs": inputs,
        },
    }


class TestRewriteSlackWorkspaceInActions(BaseTest):
    def test_rewrites_matching_value(self):
        actions = [_slack_action("a1", backfill.OLD_INTEGRATION_ID)]
        new_actions, changed = _rewrite_slack_workspace_in_actions(actions)
        assert changed == ["a1"]
        assert new_actions[0]["config"]["inputs"]["slack_workspace"]["value"] == backfill.NEW_INTEGRATION_ID

    def test_does_not_touch_non_matching_value(self):
        actions = [_slack_action("a1", 99999)]
        new_actions, changed = _rewrite_slack_workspace_in_actions(actions)
        assert changed == []
        assert new_actions[0]["config"]["inputs"]["slack_workspace"]["value"] == 99999

    def test_handles_missing_slack_workspace_input(self):
        actions = [_slack_action("a1", None)]
        new_actions, changed = _rewrite_slack_workspace_in_actions(actions)
        assert changed == []
        assert "slack_workspace" not in new_actions[0]["config"]["inputs"]

    def test_mixed_actions_only_changes_matches(self):
        actions = [
            _slack_action("match", backfill.OLD_INTEGRATION_ID),
            _slack_action("nope", 99999),
            {"id": "trigger", "type": "trigger", "config": {}},
            {"id": "exit", "type": "exit", "config": {"reason": "default"}},
        ]
        new_actions, changed = _rewrite_slack_workspace_in_actions(actions)
        assert changed == ["match"]
        assert new_actions[0]["config"]["inputs"]["slack_workspace"]["value"] == backfill.NEW_INTEGRATION_ID
        assert new_actions[1]["config"]["inputs"]["slack_workspace"]["value"] == 99999

    def test_idempotent_when_already_migrated(self):
        actions = [_slack_action("a1", backfill.NEW_INTEGRATION_ID)]
        _, changed = _rewrite_slack_workspace_in_actions(actions)
        assert changed == []

    def test_non_list_actions_returned_unchanged(self):
        new_actions, changed = _rewrite_slack_workspace_in_actions(None)
        assert new_actions is None
        assert changed == []

    def test_deepcopy_does_not_mutate_input(self):
        actions = [_slack_action("a1", backfill.OLD_INTEGRATION_ID)]
        _rewrite_slack_workspace_in_actions(actions)
        assert actions[0]["config"]["inputs"]["slack_workspace"]["value"] == backfill.OLD_INTEGRATION_ID


class TestBackfillWorkflowsSlackIntegrationCommand(BaseTest):
    """Tests patch the TEAM_ID constant to point at the test team so we don't need to
    construct a Team row with a specific primary key."""

    def setUp(self):
        super().setUp()
        self.other_team = Team.objects.create(organization=self.organization, name="Other team")

        with patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers"):
            self.target_flow = HogFlow.objects.create(
                team=self.team,
                name="Target flow",
                status=HogFlow.State.ACTIVE,
                actions=[
                    {"id": "trigger", "type": "trigger", "config": {}},
                    _slack_action("slack_step", backfill.OLD_INTEGRATION_ID),
                ],
                draft={
                    "actions": [
                        _slack_action("slack_step", backfill.OLD_INTEGRATION_ID),
                    ]
                },
                version=1,
            )
            self.untouched_flow = HogFlow.objects.create(
                team=self.team,
                name="Already migrated",
                status=HogFlow.State.ACTIVE,
                actions=[_slack_action("slack_step", backfill.NEW_INTEGRATION_ID)],
                version=1,
            )
            self.other_team_flow = HogFlow.objects.create(
                team=self.other_team,
                name="Other team flow",
                status=HogFlow.State.ACTIVE,
                actions=[_slack_action("slack_step", backfill.OLD_INTEGRATION_ID)],
                version=1,
            )

    def test_dry_run_does_not_modify_db(self):
        with patch.object(backfill, "TEAM_ID", self.team.id):
            call_command("backfill_workflows_slack_integration", "--dry-run")

        self.target_flow.refresh_from_db()
        assert self.target_flow.draft is not None
        assert (
            self.target_flow.actions[1]["config"]["inputs"]["slack_workspace"]["value"] == backfill.OLD_INTEGRATION_ID
        )
        assert (
            self.target_flow.draft["actions"][0]["config"]["inputs"]["slack_workspace"]["value"]
            == backfill.OLD_INTEGRATION_ID
        )

    def test_rewrites_only_target_team(self):
        with (
            patch.object(backfill, "TEAM_ID", self.team.id),
            patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers"),
        ):
            call_command("backfill_workflows_slack_integration")

        self.target_flow.refresh_from_db()
        self.untouched_flow.refresh_from_db()
        self.other_team_flow.refresh_from_db()

        assert self.target_flow.draft is not None
        assert (
            self.target_flow.actions[1]["config"]["inputs"]["slack_workspace"]["value"] == backfill.NEW_INTEGRATION_ID
        )
        assert (
            self.target_flow.draft["actions"][0]["config"]["inputs"]["slack_workspace"]["value"]
            == backfill.NEW_INTEGRATION_ID
        )
        assert (
            self.untouched_flow.actions[0]["config"]["inputs"]["slack_workspace"]["value"]
            == backfill.NEW_INTEGRATION_ID
        )
        # Other team must remain untouched even with the matching old id.
        assert (
            self.other_team_flow.actions[0]["config"]["inputs"]["slack_workspace"]["value"]
            == backfill.OLD_INTEGRATION_ID
        )
