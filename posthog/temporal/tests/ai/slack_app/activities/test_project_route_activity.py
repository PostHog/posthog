"""Gate tests for ``classify_slack_app_project_route_activity``.

The classifier's own prompt and parse behaviour is covered in
``test_classify_slack_app_project_route.py``, and which projects are eligible in
``products/slack_app/backend/tests/services/test_project_routing.py``. What matters here
is what the activity does with both.
"""

import pytest
from unittest.mock import patch

from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.ai.slack_app.activities.classifiers import classify_slack_app_project_route_activity
from posthog.temporal.ai.slack_app.types import SlackAppProjectRouteInput

from products.slack_app.backend.services.project_routing import ProjectChoice

ACTIVITY_MODULE = "posthog.temporal.ai.slack_app.activities.classifiers"
WORKSPACE = "T_WS"
SLACK_USER = "U001"


class TestClassifySlackAppProjectRouteActivity:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        organization = Organization.objects.create(name="Org")
        self.default_team = Team.objects.create(organization=organization, name="Production")
        self.other_team = Team.objects.create(organization=organization, name="Staging")
        self.user = User.objects.create(email="dev@example.com", distinct_id="u-1")
        OrganizationMembership.objects.create(user=self.user, organization=organization)

        self.default = Integration.objects.create(
            team=self.default_team,
            kind="slack",
            integration_id=WORKSPACE,
            sensitive_config={"access_token": "xoxb"},
        )
        self.other = Integration.objects.create(
            team=self.other_team,
            kind="slack",
            integration_id=WORKSPACE,
            sensitive_config={"access_token": "xoxb"},
        )
        self.offered = (
            ProjectChoice(team_id=self.default_team.id, integration_id=self.default.id, label="Org · Production"),
            ProjectChoice(team_id=self.other_team.id, integration_id=self.other.id, label="Org · Staging"),
        )

    def _input(self, text: str = "how many signups on staging yesterday") -> SlackAppProjectRouteInput:
        return SlackAppProjectRouteInput(
            integration_id=self.default.id,
            slack_team_id=WORKSPACE,
            event_text=text,
            user_id=self.user.id,
            slack_user_id=SLACK_USER,
        )

    def test_blank_text_never_reaches_the_llm(self):
        with patch(f"{ACTIVITY_MODULE}.classify_slack_app_project_route") as classify:
            assert classify_slack_app_project_route_activity(self._input("   ")) is None
        classify.assert_not_called()

    def test_no_eligible_projects_never_reaches_the_llm(self):
        with (
            patch(f"{ACTIVITY_MODULE}.routable_projects", return_value=()),
            patch(f"{ACTIVITY_MODULE}.classify_slack_app_project_route") as classify,
        ):
            assert classify_slack_app_project_route_activity(self._input()) is None
        classify.assert_not_called()

    def test_named_project_is_returned_as_its_integration(self):
        with (
            patch(f"{ACTIVITY_MODULE}.routable_projects", return_value=self.offered),
            patch(f"{ACTIVITY_MODULE}.classify_slack_app_project_route", return_value=self.offered[1]),
        ):
            result = classify_slack_app_project_route_activity(self._input())

        assert result is not None
        assert result.integration_id == self.other.id

    def test_naming_the_project_the_run_already_had_reports_no_route(self):
        # A returned route is what drives both the rebind and the notice posted in the
        # thread, so naming the default must not read as a move.
        with (
            patch(f"{ACTIVITY_MODULE}.routable_projects", return_value=self.offered),
            patch(f"{ACTIVITY_MODULE}.classify_slack_app_project_route", return_value=self.offered[0]),
        ):
            assert classify_slack_app_project_route_activity(self._input()) is None
