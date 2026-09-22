"""Gate tests for ``classify_slack_app_project_route_activity``.

The classifier's own prompt and parse behaviour is covered in
``test_classify_slack_app_project_route.py``, and which projects are eligible in
``products/slack_app/backend/tests/services/test_project_routing.py``. What matters here
is what the activity does with both.
"""

from contextlib import contextmanager

import pytest
from unittest.mock import patch

from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.ai.slack_app.activities.classifiers import classify_slack_app_project_route_activity
from posthog.temporal.ai.slack_app.types import SlackAppProjectRouteInput

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
        self.offered = [self.default, self.other]

    def _input(self, text: str = "how many signups on staging yesterday") -> SlackAppProjectRouteInput:
        return SlackAppProjectRouteInput(
            integration_id=self.default.id,
            slack_team_id=WORKSPACE,
            event_text=text,
            user_id=self.user.id,
            slack_user_id=SLACK_USER,
        )

    @contextmanager
    def _classifier(self, *, projects: list | None = None, **kwargs):
        """Run the activity with the LLM call stubbed, yielding the stub."""
        with (
            patch(f"{ACTIVITY_MODULE}.routable_projects", return_value=self.offered if projects is None else projects),
            patch(f"{ACTIVITY_MODULE}.classify_slack_app_project_route", **kwargs) as classify,
        ):
            yield classify

    @pytest.mark.parametrize(
        "reason",
        [
            # A follow-up that is only an attachment carries no sentence to read.
            "blank_text",
            "no_eligible_projects",
        ],
    )
    def test_gates_return_no_route_without_calling_the_llm(self, reason):
        text = "   " if reason == "blank_text" else "how many signups on staging yesterday"
        with self._classifier(projects=[] if reason == "no_eligible_projects" else None) as classify:
            assert classify_slack_app_project_route_activity(self._input(text)) is None
        classify.assert_not_called()

    def test_named_project_is_returned_as_its_integration(self):
        with self._classifier(return_value=self.other):
            result = classify_slack_app_project_route_activity(self._input())

        assert result is not None
        assert result.integration_id == self.other.id

    def test_a_gateway_failure_leaves_the_run_where_routing_put_it(self):
        with self._classifier(side_effect=RuntimeError("boom")):
            assert classify_slack_app_project_route_activity(self._input()) is None

    def test_naming_the_project_the_run_already_had_reports_no_route(self):
        # A returned route is what drives both the rebind and the notice posted in the
        # thread, so naming the default must not read as a move.
        with self._classifier(return_value=self.default):
            assert classify_slack_app_project_route_activity(self._input()) is None
