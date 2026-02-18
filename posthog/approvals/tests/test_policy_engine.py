from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.approvals.models import ApprovalPolicy
from posthog.approvals.policies import PolicyEngine
from posthog.models.organization import OrganizationMembership


class TestPolicyEngineBypass(APIBaseTest):
    def _create_policy(
        self,
        bypass_org_membership_levels: list[str] | None = None,
        bypass_role_ids: list[str] | None = None,
    ) -> ApprovalPolicy:
        policy = ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.update",
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            bypass_org_membership_levels=bypass_org_membership_levels or [],
            created_by=self.user,
        )
        if bypass_role_ids:
            policy.set_bypass_roles(bypass_role_ids)
        return policy

    @parameterized.expand(
        [
            (OrganizationMembership.Level.ADMIN, ["8", "15"], True),
            (OrganizationMembership.Level.OWNER, ["8", "15"], True),
            (OrganizationMembership.Level.MEMBER, ["8", "15"], False),
            (OrganizationMembership.Level.ADMIN, ["15"], False),
            (OrganizationMembership.Level.OWNER, ["15"], True),
            (OrganizationMembership.Level.ADMIN, [], False),
        ]
    )
    def test_bypass_org_membership_levels(
        self,
        user_level: int,
        bypass_levels: list[str],
        expected_bypass: bool,
    ):
        self.organization_membership.level = user_level
        self.organization_membership.save()

        policy = self._create_policy(bypass_org_membership_levels=bypass_levels)
        engine = PolicyEngine()
        context = {"organization": self.organization}
        bypass_role_ids = [str(r.id) for r in policy.bypass_roles.all()]

        result = engine._has_bypass(self.user, policy, bypass_role_ids, context)

        assert result is expected_bypass

    def test_bypass_rbac_role(self):
        from ee.models.rbac.role import Role, RoleMembership

        role = Role.objects.create(
            organization=self.organization,
            name="Approver Role",
        )
        RoleMembership.objects.create(user=self.user, role=role)

        policy = self._create_policy(bypass_role_ids=[str(role.id)])
        engine = PolicyEngine()
        context = {"organization": self.organization}
        bypass_role_ids = [str(r.id) for r in policy.bypass_roles.all()]

        result = engine._has_bypass(self.user, policy, bypass_role_ids, context)

        assert result is True

    def test_bypass_rbac_role_user_not_in_role(self):
        from ee.models.rbac.role import Role

        role = Role.objects.create(
            organization=self.organization,
            name="Approver Role",
        )

        policy = self._create_policy(bypass_role_ids=[str(role.id)])
        engine = PolicyEngine()
        context = {"organization": self.organization}
        bypass_role_ids = [str(r.id) for r in policy.bypass_roles.all()]

        result = engine._has_bypass(self.user, policy, bypass_role_ids, context)

        assert result is False

    def test_bypass_rbac_role_user_has_other_org_role_but_not_bypass_role(self):
        from posthog.models.organization import Organization

        from ee.models.rbac.role import Role, RoleMembership

        other_org = Organization.objects.create(name="Other Org")
        other_role = Role.objects.create(
            organization=other_org,
            name="Other Org Role",
        )
        RoleMembership.objects.create(user=self.user, role=other_role)

        bypass_role = Role.objects.create(
            organization=self.organization,
            name="Bypass Role",
        )

        policy = self._create_policy(bypass_role_ids=[str(bypass_role.id)])
        engine = PolicyEngine()
        context = {"organization": self.organization}
        bypass_role_ids = [str(r.id) for r in policy.bypass_roles.all()]

        result = engine._has_bypass(self.user, policy, bypass_role_ids, context)

        assert result is False

    def test_no_bypass_when_both_empty(self):
        policy = self._create_policy(bypass_org_membership_levels=[], bypass_role_ids=[])
        engine = PolicyEngine()
        context = {"organization": self.organization}
        bypass_role_ids = [str(r.id) for r in policy.bypass_roles.all()]

        result = engine._has_bypass(self.user, policy, bypass_role_ids, context)

        assert result is False

    def test_no_bypass_without_organization_context(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        policy = self._create_policy(bypass_org_membership_levels=["8", "15"])
        engine = PolicyEngine()
        context: dict[str, object] = {}
        bypass_role_ids = [str(r.id) for r in policy.bypass_roles.all()]

        result = engine._has_bypass(self.user, policy, bypass_role_ids, context)

        assert result is False


class TestPolicyEngineEvaluateBypass(APIBaseTest):
    def _create_policy(
        self,
        bypass_org_membership_levels: list[str] | None = None,
        bypass_role_ids: list[str] | None = None,
    ) -> ApprovalPolicy:
        policy = ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.update",
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            bypass_org_membership_levels=bypass_org_membership_levels or [],
            created_by=self.user,
        )
        if bypass_role_ids:
            policy.set_bypass_roles(bypass_role_ids)
        return policy

    def test_evaluate_returns_allow_when_org_level_bypass(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        policy = self._create_policy(bypass_org_membership_levels=["8", "15"])
        engine = PolicyEngine()
        context = {"organization": self.organization}
        intent = {"gated_changes": {"rollout_percentage": [{"path": "groups[0]", "value": 80}]}}

        decision = engine.evaluate(policy, self.user, intent, context)

        assert decision.result == "ALLOW"
        assert "bypass" in decision.reason.lower()

    def test_evaluate_returns_allow_when_rbac_role_bypass(self):
        from ee.models.rbac.role import Role, RoleMembership

        role = Role.objects.create(
            organization=self.organization,
            name="Bypass Role",
        )
        RoleMembership.objects.create(user=self.user, role=role)

        policy = self._create_policy(bypass_role_ids=[str(role.id)])
        engine = PolicyEngine()
        context = {"organization": self.organization}
        intent = {"gated_changes": {"rollout_percentage": [{"path": "groups[0]", "value": 80}]}}

        decision = engine.evaluate(policy, self.user, intent, context)

        assert decision.result == "ALLOW"
        assert "bypass" in decision.reason.lower()

    def test_evaluate_returns_require_approval_when_no_bypass(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        policy = self._create_policy(bypass_org_membership_levels=["8", "15"])
        engine = PolicyEngine()
        context = {"organization": self.organization}
        intent = {"gated_changes": {"rollout_percentage": [{"path": "groups[0]", "value": 80}]}}

        decision = engine.evaluate(policy, self.user, intent, context)

        assert decision.result == "REQUIRE_APPROVAL"


class TestPolicySnapshotBypassFields(APIBaseTest):
    def _create_policy(
        self,
        bypass_org_membership_levels: list[str] | None = None,
        bypass_role_ids: list[str] | None = None,
    ) -> ApprovalPolicy:
        policy = ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.update",
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            bypass_org_membership_levels=bypass_org_membership_levels or [],
            created_by=self.user,
        )
        if bypass_role_ids:
            policy.set_bypass_roles(bypass_role_ids)
        return policy

    def test_policy_snapshot_includes_bypass_org_membership_levels(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        policy = self._create_policy(bypass_org_membership_levels=["8", "15"])
        engine = PolicyEngine()
        context = {"organization": self.organization}
        intent = {"gated_changes": {"rollout_percentage": [{"path": "groups[0]", "value": 80}]}}

        decision = engine.evaluate(policy, self.user, intent, context)

        assert "bypass_org_membership_levels" in decision.policy_snapshot
        assert decision.policy_snapshot["bypass_org_membership_levels"] == ["8", "15"]

    def test_policy_snapshot_includes_bypass_roles(self):
        from ee.models.rbac.role import Role

        role = Role.objects.create(
            organization=self.organization,
            name="Bypass Role",
        )

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        policy = self._create_policy(bypass_role_ids=[str(role.id)])
        engine = PolicyEngine()
        context = {"organization": self.organization}
        intent = {"gated_changes": {"rollout_percentage": [{"path": "groups[0]", "value": 80}]}}

        decision = engine.evaluate(policy, self.user, intent, context)

        assert "bypass_roles" in decision.policy_snapshot
        assert decision.policy_snapshot["bypass_roles"] == [str(role.id)]

    def test_policy_snapshot_includes_empty_bypass_fields(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        policy = self._create_policy()
        engine = PolicyEngine()
        context = {"organization": self.organization}
        intent = {"gated_changes": {"rollout_percentage": [{"path": "groups[0]", "value": 80}]}}

        decision = engine.evaluate(policy, self.user, intent, context)

        assert decision.policy_snapshot["bypass_org_membership_levels"] == []
        assert decision.policy_snapshot["bypass_roles"] == []


class TestBypassRolesValidation(APIBaseTest):
    def test_set_bypass_roles_validates_organization(self):
        from posthog.models.organization import Organization

        from ee.models.rbac.role import Role

        other_org = Organization.objects.create(name="Other Org")
        role = Role.objects.create(
            organization=other_org,
            name="Other Org Role",
        )

        policy = ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.update",
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

        with self.assertRaises(ValueError) as context:
            policy.set_bypass_roles([str(role.id)])

        assert "same organization" in str(context.exception)

    def test_set_bypass_roles_accepts_valid_roles(self):
        from ee.models.rbac.role import Role

        role = Role.objects.create(
            organization=self.organization,
            name="Valid Role",
        )

        policy = ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.update",
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

        policy.set_bypass_roles([str(role.id)])

        assert list(policy.bypass_roles.values_list("id", flat=True)) == [role.id]

    def test_set_bypass_roles_clears_when_empty(self):
        from ee.models.rbac.role import Role

        role = Role.objects.create(
            organization=self.organization,
            name="Valid Role",
        )

        policy = ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.update",
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )
        policy.bypass_roles.add(role)

        policy.set_bypass_roles([])

        assert policy.bypass_roles.count() == 0
