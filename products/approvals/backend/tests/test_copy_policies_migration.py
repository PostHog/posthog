import importlib
from datetime import timedelta

from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.models import Team

from products.approvals.backend.models import ApprovalPolicy

# Delete this once the migration has run everywhere and the rollback window has closed.
MIGRATION = importlib.import_module(
    "products.approvals.backend.migrations.0003_copy_feature_flag_policies_to_experiments"
)


class FakeApps:
    def get_model(self, app_label: str, model_name: str) -> type[ApprovalPolicy]:
        return ApprovalPolicy


def run_migration() -> None:
    MIGRATION.copy_policies(FakeApps(), None)


class TestCopyFeatureFlagPoliciesToExperiments(APIBaseTest):
    def _policy(self, action_key: str, *, team: Team | None = None, **overrides) -> ApprovalPolicy:
        return ApprovalPolicy.objects.create(
            organization=self.organization,
            team=team if team is not None else self.team,
            action_key=action_key,
            conditions=overrides.pop("conditions", {}),
            approver_config=overrides.pop("approver_config", {"quorum": 1, "users": [self.user.id]}),
            created_by=self.user,
            **overrides,
        )

    @parameterized.expand(
        [
            ("feature_flag.enable", "experiment.launch"),
            ("feature_flag.disable", "experiment.pause"),
            ("feature_flag.update", "experiment.update"),
        ]
    )
    def test_each_flag_action_gets_its_experiment_action(self, source: str, target: str) -> None:
        self._policy(source)

        run_migration()

        assert ApprovalPolicy.objects.filter(action_key=target, team=self.team).count() == 1

    def test_copies_per_team_not_per_organization(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        self._policy("feature_flag.enable")
        self._policy("feature_flag.enable", team=other_team)

        run_migration()

        copied_teams = set(
            ApprovalPolicy.objects.filter(action_key="experiment.launch").values_list("team_id", flat=True)
        )
        assert copied_teams == {self.team.id, other_team.id}

    def test_carries_the_whole_policy_across(self) -> None:
        source = self._policy(
            "feature_flag.update",
            conditions={"type": "before_after", "field": "rollout_percentage", "operator": ">", "value": 0},
            approver_config={"quorum": 2, "users": [self.user.id]},
            allow_self_approve=True,
            bypass_org_membership_levels=[15],
            expires_after=timedelta(days=3),
            enabled=False,
        )

        run_migration()

        copy = ApprovalPolicy.objects.get(action_key="experiment.update", team=self.team)
        for field in MIGRATION.COPIED_FIELDS:
            assert getattr(copy, field) == getattr(source, field), field

    def test_running_twice_creates_nothing_new(self) -> None:
        self._policy("feature_flag.enable")

        run_migration()
        run_migration()

        assert ApprovalPolicy.objects.filter(action_key="experiment.launch").count() == 1

    def test_leaves_an_organization_without_policies_alone(self) -> None:
        run_migration()

        assert not ApprovalPolicy.objects.filter(action_key__startswith="experiment.").exists()
