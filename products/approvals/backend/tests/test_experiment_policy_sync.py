from datetime import timedelta

from posthog.test.base import BaseTest

from django.db import connection

from parameterized import parameterized

from posthog.models import Team

from products.access_control.backend.models.role import Role
from products.approvals.backend.experiment_policy_sync import _SYNC_LOCK_KEY, sync_experiment_policies
from products.approvals.backend.models import ApprovalPolicy


class TestSyncExperimentPolicies(BaseTest):
    def _flag_policy(self, action_key: str, **overrides) -> ApprovalPolicy:
        fields = {
            "organization": self.organization,
            "team": self.team,
            "action_key": action_key,
            "approver_config": {"quorum": 1, "users": [self.user.id]},
            "created_by": self.user,
            **overrides,
        }
        return ApprovalPolicy.objects.create(**fields)

    def _mirror(self, action_key: str, team: Team | None) -> ApprovalPolicy:
        return ApprovalPolicy.objects.get(organization=self.organization, team=team, action_key=action_key)

    @parameterized.expand(
        [
            ("feature_flag.enable", "experiment.launch"),
            ("feature_flag.disable", "experiment.pause"),
            ("feature_flag.update", "experiment.update"),
        ]
    )
    def test_creates_mirror_with_mapped_action(self, source_action: str, mirror_action: str) -> None:
        role = Role.objects.create(organization=self.organization, name="Release managers")
        source = self._flag_policy(
            source_action,
            conditions={"rollout_percentage": {"gt": 50}},
            approver_config={"quorum": 2, "users": [self.user.id], "roles": [str(role.id)]},
            allow_self_approve=True,
            bypass_org_membership_levels=[15],
            expires_after=timedelta(days=3),
            enabled=False,
        )
        source.bypass_roles.set([role])

        sync_experiment_policies()

        mirror = self._mirror(mirror_action, self.team)
        assert mirror.conditions == source.conditions
        assert mirror.approver_config == source.approver_config
        assert mirror.allow_self_approve is True
        assert mirror.bypass_org_membership_levels == [15]
        assert mirror.expires_after == timedelta(days=3)
        assert mirror.enabled is False
        assert mirror.created_by_id == self.user.id
        assert list(mirror.bypass_roles.all()) == [role]

    def test_propagates_edits_without_duplicating(self) -> None:
        kept_role = Role.objects.create(organization=self.organization, name="Kept")
        dropped_role = Role.objects.create(organization=self.organization, name="Dropped")
        source = self._flag_policy("feature_flag.update")
        source.bypass_roles.set([dropped_role])
        sync_experiment_policies()

        source.bypass_roles.set([kept_role])
        before_roles_sync = self._mirror("experiment.update", self.team).updated_at
        sync_experiment_policies()
        assert self._mirror("experiment.update", self.team).updated_at > before_roles_sync

        source.approver_config = {"quorum": 3, "users": [self.user.id]}
        source.enabled = False
        source.save()
        sync_experiment_policies()
        sync_experiment_policies()

        assert ApprovalPolicy.objects.filter(action_key="experiment.update").count() == 1
        mirror = self._mirror("experiment.update", self.team)
        assert mirror.approver_config == {"quorum": 3, "users": [self.user.id]}
        assert mirror.enabled is False
        assert list(mirror.bypass_roles.all()) == [kept_role]

    def test_deletes_mirror_only_when_its_source_is_gone(self) -> None:
        deleted_source = self._flag_policy("feature_flag.enable")
        self._flag_policy("feature_flag.enable", team=None)
        unrelated = self._flag_policy("feature_flag.delete")
        sync_experiment_policies()

        deleted_source.delete()
        sync_experiment_policies()

        assert not ApprovalPolicy.objects.filter(team=self.team, action_key="experiment.launch").exists()
        assert self._mirror("experiment.launch", None)
        assert ApprovalPolicy.objects.filter(id=unrelated.id).exists()
        assert not ApprovalPolicy.objects.filter(action_key="experiment.delete").exists()

    def test_skips_while_another_run_holds_the_lock(self) -> None:
        self._flag_policy("feature_flag.enable", team=None)
        other_run = connection.copy()
        try:
            with other_run.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", [_SYNC_LOCK_KEY])
            sync_experiment_policies()
        finally:
            other_run.close()

        assert not ApprovalPolicy.objects.filter(action_key="experiment.launch").exists()
        sync_experiment_policies()
        assert self._mirror("experiment.launch", None)
