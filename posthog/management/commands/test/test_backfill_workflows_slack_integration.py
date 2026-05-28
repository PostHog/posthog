from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command

from posthog.management.commands.backfill_workflows_slack_integration import _rewrite_slack_workspace_in_actions
from posthog.models import Team
from posthog.models.hog_flow.hog_flow import HogFlow


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
        actions = [_slack_action("a1", 54567)]
        new_actions, changed = _rewrite_slack_workspace_in_actions(actions, 54567, 173069)
        assert changed == ["a1"]
        assert new_actions[0]["config"]["inputs"]["slack_workspace"]["value"] == 173069

    def test_does_not_touch_non_matching_value(self):
        actions = [_slack_action("a1", 99999)]
        new_actions, changed = _rewrite_slack_workspace_in_actions(actions, 54567, 173069)
        assert changed == []
        assert new_actions[0]["config"]["inputs"]["slack_workspace"]["value"] == 99999

    def test_handles_missing_slack_workspace_input(self):
        actions = [_slack_action("a1", None)]
        new_actions, changed = _rewrite_slack_workspace_in_actions(actions, 54567, 173069)
        assert changed == []
        assert "slack_workspace" not in new_actions[0]["config"]["inputs"]

    def test_mixed_actions_only_changes_matches(self):
        actions = [
            _slack_action("match", 54567),
            _slack_action("nope", 99999),
            {"id": "trigger", "type": "trigger", "config": {}},
            {"id": "exit", "type": "exit", "config": {"reason": "default"}},
        ]
        new_actions, changed = _rewrite_slack_workspace_in_actions(actions, 54567, 173069)
        assert changed == ["match"]
        assert new_actions[0]["config"]["inputs"]["slack_workspace"]["value"] == 173069
        assert new_actions[1]["config"]["inputs"]["slack_workspace"]["value"] == 99999

    def test_idempotent_when_already_migrated(self):
        actions = [_slack_action("a1", 173069)]
        _, changed = _rewrite_slack_workspace_in_actions(actions, 54567, 173069)
        assert changed == []

    def test_non_list_actions_returned_unchanged(self):
        new_actions, changed = _rewrite_slack_workspace_in_actions(None, 54567, 173069)
        assert new_actions is None
        assert changed == []

    def test_deepcopy_does_not_mutate_input(self):
        actions = [_slack_action("a1", 54567)]
        _rewrite_slack_workspace_in_actions(actions, 54567, 173069)
        assert actions[0]["config"]["inputs"]["slack_workspace"]["value"] == 54567


class TestBackfillWorkflowsSlackIntegrationCommand(BaseTest):
    def setUp(self):
        super().setUp()
        self.other_team = Team.objects.create(organization=self.organization, name="Other team")

        with patch("posthog.models.hog_flow.hog_flow.reload_hog_flows_on_workers"):
            self.target_flow = HogFlow.objects.create(
                team=self.team,
                name="Target flow",
                status=HogFlow.State.ACTIVE,
                actions=[
                    {"id": "trigger", "type": "trigger", "config": {}},
                    _slack_action("slack_step", 54567),
                ],
                draft={
                    "actions": [
                        _slack_action("slack_step", 54567),
                    ]
                },
                version=1,
            )
            self.untouched_flow = HogFlow.objects.create(
                team=self.team,
                name="Already migrated",
                status=HogFlow.State.ACTIVE,
                actions=[_slack_action("slack_step", 173069)],
                version=1,
            )
            self.other_team_flow = HogFlow.objects.create(
                team=self.other_team,
                name="Other team flow",
                status=HogFlow.State.ACTIVE,
                actions=[_slack_action("slack_step", 54567)],
                version=1,
            )

    def test_dry_run_does_not_modify_db(self):
        call_command(
            "backfill_workflows_slack_integration",
            f"--team-id={self.team.id}",
            "--old-integration-id=54567",
            "--new-integration-id=173069",
            "--dry-run",
        )

        self.target_flow.refresh_from_db()
        assert self.target_flow.actions[1]["config"]["inputs"]["slack_workspace"]["value"] == 54567
        assert self.target_flow.draft["actions"][0]["config"]["inputs"]["slack_workspace"]["value"] == 54567

    def test_rewrites_only_target_team(self):
        with patch("posthog.models.hog_flow.hog_flow.reload_hog_flows_on_workers"):
            call_command(
                "backfill_workflows_slack_integration",
                f"--team-id={self.team.id}",
                "--old-integration-id=54567",
                "--new-integration-id=173069",
            )

        self.target_flow.refresh_from_db()
        self.untouched_flow.refresh_from_db()
        self.other_team_flow.refresh_from_db()

        assert self.target_flow.actions[1]["config"]["inputs"]["slack_workspace"]["value"] == 173069
        assert self.target_flow.draft["actions"][0]["config"]["inputs"]["slack_workspace"]["value"] == 173069
        assert self.untouched_flow.actions[0]["config"]["inputs"]["slack_workspace"]["value"] == 173069
        # Other team must remain untouched even with the matching old id.
        assert self.other_team_flow.actions[0]["config"]["inputs"]["slack_workspace"]["value"] == 54567

    def test_aborts_when_old_and_new_are_equal(self):
        # Running with old == new should refuse rather than no-op silently.
        call_command(
            "backfill_workflows_slack_integration",
            f"--team-id={self.team.id}",
            "--old-integration-id=54567",
            "--new-integration-id=54567",
        )
        self.target_flow.refresh_from_db()
        assert self.target_flow.actions[1]["config"]["inputs"]["slack_workspace"]["value"] == 54567
