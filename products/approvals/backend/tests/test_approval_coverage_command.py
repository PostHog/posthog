from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import call_command

from posthog.models import Team

from products.approvals.backend.models import ApprovalPolicy
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestApprovalCoverageCommand(BaseTest):
    def _policy(self, action_key: str, team: Team | None) -> ApprovalPolicy:
        return ApprovalPolicy.objects.create(
            organization=self.organization,
            team=team,
            action_key=action_key,
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

    def test_a_team_policy_counts_only_for_its_own_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization, project=self.team.project)
        self._policy("feature_flag.enable", team=None)
        self._policy("experiment.launch", team=self.team)
        flag = FeatureFlag.objects.create(team=other_team, key="other-team-experiment", created_by=self.user)
        Experiment.objects.create(team=other_team, name="Other team experiment", feature_flag=flag)

        out = StringIO()
        call_command("approval_coverage", "--organization", str(self.organization.id), stdout=out)

        assert "0 flags move family, 1 flags lose coverage" in out.getvalue()
