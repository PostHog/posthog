from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command

from posthog.models.hog_flow.hog_flow import HogFlow
from posthog.models.hog_flow.hog_flow_revision import HogFlowRevision
from posthog.models.team.team import Team


class TestBackfillHogFlowRevisions(BaseTest):
    def setUp(self):
        super().setUp()
        self.team2 = Team.objects.create(organization=self.organization, name="Test Team 2")

    def _create_flow(self, team, name="Test Flow", status=HogFlow.State.ACTIVE, **kwargs):
        defaults = {
            "name": name,
            "status": status,
            "trigger": {"type": "event", "filters": {"events": [{"id": "$pageview"}]}},
            "edges": [{"from": "a", "to": "b"}],
            "actions": [{"id": "a", "type": "trigger"}],
        }
        defaults.update(kwargs)
        with patch("posthog.models.hog_flow.hog_flow.reload_hog_flows_on_workers"):
            return HogFlow.objects.create(team=team, **defaults)

    def test_backfill_creates_revisions(self):
        flow1 = self._create_flow(self.team, name="Flow 1")
        flow2 = self._create_flow(self.team, name="Flow 2")

        out = StringIO()
        call_command("backfill_hogflow_revisions", stdout=out)

        assert HogFlowRevision.objects.count() == 2

        flow1.refresh_from_db()
        flow2.refresh_from_db()
        assert flow1.active_revision is not None
        assert flow2.active_revision is not None

        rev1 = flow1.active_revision
        assert rev1.version == flow1.version
        assert rev1.status == HogFlowRevision.State.ACTIVE
        assert rev1.name == "Flow 1"
        assert rev1.trigger == flow1.trigger
        assert rev1.edges == flow1.edges
        assert rev1.actions == flow1.actions
        assert rev1.team_id == self.team.id

    def test_backfill_skips_already_backfilled(self):
        self._create_flow(self.team)

        out = StringIO()
        call_command("backfill_hogflow_revisions", stdout=out)
        assert HogFlowRevision.objects.count() == 1

        out = StringIO()
        call_command("backfill_hogflow_revisions", stdout=out)
        assert HogFlowRevision.objects.count() == 1
        assert "Nothing to backfill" in out.getvalue()

    def test_backfill_filters_by_team(self):
        self._create_flow(self.team, name="Team 1 Flow")
        self._create_flow(self.team2, name="Team 2 Flow")

        out = StringIO()
        call_command("backfill_hogflow_revisions", team_id=self.team.id, stdout=out)

        assert HogFlowRevision.objects.filter(team=self.team).count() == 1
        assert HogFlowRevision.objects.filter(team=self.team2).count() == 0

    def test_dry_run_does_not_create_revisions(self):
        self._create_flow(self.team)

        out = StringIO()
        call_command("backfill_hogflow_revisions", dry_run=True, stdout=out)

        assert HogFlowRevision.objects.count() == 0
        assert "DRY RUN" in out.getvalue()

    def test_backfill_copies_all_content_fields(self):
        flow = self._create_flow(
            self.team,
            name="Full Flow",
            description="A description",
            trigger_masking={"ttl": 3600},
            conversion={"goal": "purchase"},
            exit_condition="exit_on_trigger_not_matched",
            abort_action="abort_node",
            variables=[{"name": "x"}],
            billable_action_types=["function"],
        )

        call_command("backfill_hogflow_revisions", stdout=StringIO())

        flow.refresh_from_db()
        rev = flow.active_revision
        assert rev.name == "Full Flow"
        assert rev.description == "A description"
        assert rev.trigger_masking == {"ttl": 3600}
        assert rev.conversion == {"goal": "purchase"}
        assert rev.exit_condition == "exit_on_trigger_not_matched"
        assert rev.abort_action == "abort_node"
        assert rev.variables == [{"name": "x"}]
        assert rev.billable_action_types == ["function"]
