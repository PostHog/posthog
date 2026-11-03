import pytest
from posthog.test.base import BaseTest

from django.db import connection
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import Organization, OrganizationMembership

from products.access_control.backend.facade import contracts
from products.access_control.backend.facade.api import (
    InvalidObjectAccessControlError,
    bulk_set_object_access_controls,
    every_member_has_resource_access,
    object_ids_restricted_from_any_member,
    role_belongs_to_organization,
    set_object_access_control,
    valid_role_member_user_ids,
)
from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.role import Role, RoleMembership
from products.dashboards.backend.models.dashboard import Dashboard


class TestSetObjectAccessControl(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        self.other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "testtest")
        self.other_membership = OrganizationMembership.objects.get(user=self.other_user, organization=self.organization)
        self.dashboard = Dashboard.objects.create(team=self.team, created_by=self.user)
        AccessControl.objects.create(team=self.team, resource="dashboard", resource_id=None, access_level="none")

    def _grant(
        self, access_level: str | None = "viewer", **overrides: object
    ) -> contracts.ObjectAccessControlRule | None:
        input_kwargs: dict = {
            "resource": "dashboard",
            "resource_id": str(self.dashboard.id),
            "access_level": access_level,
            "organization_member_id": self.other_membership.id,
        }
        input_kwargs.update(overrides)
        return set_object_access_control(
            team_id=self.team.id, input=contracts.SetObjectAccessControlInput(**input_kwargs)
        )

    def _other_user_level(self) -> str | None:
        return UserAccessControl(user=self.other_user, team=self.team).get_user_access_level(self.dashboard)

    def test_grant_update_and_revoke_are_visible_through_user_access_control(self) -> None:
        assert self._other_user_level() == "none"

        rule = self._grant("viewer")
        assert rule is not None and rule.access_level == "viewer"
        assert self._other_user_level() == "viewer"

        updated = self._grant("editor")
        assert updated is not None and updated.id == rule.id
        assert self._other_user_level() == "editor"

        assert self._grant(None) is None
        assert self._other_user_level() == "none"
        assert self._grant(None) is None

        logged = ActivityLog.objects.filter(scope="AccessControl", item_id=str(rule.id)).order_by("created_at")
        assert [log.activity for log in logged] == ["created", "updated", "deleted"]

    def test_role_rule_grants_role_members(self) -> None:
        role = Role.objects.create(name="Sales", organization=self.organization)
        RoleMembership.objects.create(user=self.other_user, role=role)

        self._grant("viewer", organization_member_id=None, role_id=role.id)

        assert self._other_user_level() == "viewer"

    @parameterized.expand(
        [
            ("unknown_resource", {"resource": "not_a_resource"}),
            ("internal_resource", {"resource": "INTERNAL"}),
            ("unknown_level", {"access_level": "owner"}),
            ("level_below_resource_minimum", {"resource": "action", "access_level": "none"}),
            ("level_above_resource_maximum", {"resource": "activity_log", "access_level": "editor"}),
        ]
    )
    def test_rejects_invalid_rules(self, _name: str, overrides: dict) -> None:
        with pytest.raises(InvalidObjectAccessControlError):
            self._grant(**overrides)
        assert not AccessControl.objects.filter(resource_id=str(self.dashboard.id)).exists()

    def test_rejects_subjects_from_another_organization(self) -> None:
        other_org = Organization.objects.create(name="Other")
        outsider = User.objects.create_and_join(other_org, "outsider@posthog.com", "testtest")
        outsider_membership = OrganizationMembership.objects.get(user=outsider, organization=other_org)
        other_org_role = Role.objects.create(name="Outside", organization=other_org)

        with pytest.raises(InvalidObjectAccessControlError):
            self._grant("viewer", organization_member_id=outsider_membership.id)
        with pytest.raises(InvalidObjectAccessControlError):
            self._grant("viewer", organization_member_id=None, role_id=other_org_role.id)

    def test_requires_exactly_one_subject(self) -> None:
        role = Role.objects.create(name="Sales", organization=self.organization)
        with pytest.raises(ValueError):
            self._grant("viewer", organization_member_id=None)
        with pytest.raises(ValueError):
            self._grant("viewer", role_id=role.id)

    @parameterized.expand([("member", False), ("role", False), ("member", True), ("role", True)])
    def test_bulk_rules_preserve_access_and_audit(self, subject: str, duplicates: bool) -> None:
        role = Role.objects.create(name="Support", organization=self.organization)
        RoleMembership.objects.create(user=self.other_user, role=role)
        if duplicates:
            AccessControl.objects.bulk_create(
                [
                    AccessControl(
                        team=self.team,
                        resource="dashboard",
                        resource_id=str(self.dashboard.id),
                        access_level="viewer",
                        organization_member_id=self.other_membership.id if subject == "member" else None,
                        role_id=role.id if subject == "role" else None,
                    )
                    for _ in range(2)
                ]
            )
        for level in ("viewer", "editor", "editor", None, None):
            bulk_set_object_access_controls(
                team_id=self.team.id,
                inputs=[
                    contracts.SetObjectAccessControlInput(
                        resource="dashboard",
                        resource_id=str(self.dashboard.id),
                        access_level=level,
                        created_by_id=self.user.id,
                        organization_member_id=self.other_membership.id if subject == "member" else None,
                        role_id=role.id if subject == "role" else None,
                    )
                ],
            )
            assert self._other_user_level() == (level or "none")
        logs = list(
            ActivityLog.objects.filter(
                team_id=self.team.id, scope="AccessControl", detail__name=f"dashboard {self.dashboard.id}"
            ).order_by("created_at")
        )
        assert [log.activity for log in logs] == (
            ["updated", "updated", "deleted", "deleted"] if duplicates else ["created", "updated", "deleted"]
        )
        assert len({log.item_id for log in logs}) == (2 if duplicates else 1)
        detail = logs[0 if duplicates else 1].detail
        assert detail is not None
        assert detail["changes"] == [
            {
                "type": "AccessControl",
                "field": "access_level",
                "action": "changed",
                "before": "viewer",
                "after": "editor",
            }
        ]

    @parameterized.expand([("member",), ("role",)])
    def test_bulk_rules_lock_only_requested_object_subject_pairs(self, subject: str) -> None:
        other_dashboard = Dashboard.objects.create(team=self.team, created_by=self.user)
        roles = Role.objects.bulk_create([Role(name=f"Role {i}", organization=self.organization) for i in range(2)])
        subjects = (
            [(self.other_membership.id, None), (self.organization_membership.id, None)]
            if subject == "member"
            else [(None, role.id) for role in roles]
        )
        rules = AccessControl.objects.bulk_create(
            [
                AccessControl(
                    team=self.team,
                    resource="dashboard",
                    resource_id=str(dashboard.id),
                    organization_member_id=member_id,
                    role_id=role_id,
                    access_level="viewer",
                )
                for dashboard in (self.dashboard, other_dashboard)
                for member_id, role_id in subjects
            ]
        )
        selected = [rules[0], rules[3]]
        with CaptureQueriesContext(connection) as queries:
            bulk_set_object_access_controls(
                team_id=self.team.id,
                inputs=[
                    contracts.SetObjectAccessControlInput(
                        resource=rule.resource,
                        resource_id=str(rule.resource_id),
                        organization_member_id=rule.organization_member_id,
                        role_id=rule.role_id,
                        access_level="editor",
                    )
                    for rule in selected
                ],
            )
        locking_queries = [
            query["sql"]
            for query in queries.captured_queries
            if "FOR UPDATE" in query["sql"] and AccessControl._meta.db_table in query["sql"]
        ]
        assert len(locking_queries) == 1
        assert {rule.id for rule in AccessControl.objects.raw(locking_queries[0])} == {rule.id for rule in selected}
        assert set(
            AccessControl.objects.filter(id__in=[rules[1].id, rules[2].id]).values_list("access_level", flat=True)
        ) == {"viewer"}

    @parameterized.expand([("member",), ("role",)])
    def test_bulk_rules_reject_foreign_subject_before_writing(self, subject: str) -> None:
        other_org = Organization.objects.create(name="Other organization")
        outsider = User.objects.create_and_join(other_org, "outside@example.com", "testtest")
        member = OrganizationMembership.objects.get(user=outsider, organization=other_org)
        role = Role.objects.create(name="Other role", organization=other_org)
        with pytest.raises(InvalidObjectAccessControlError):
            bulk_set_object_access_controls(
                team_id=self.team.id,
                inputs=[
                    contracts.SetObjectAccessControlInput(
                        resource="dashboard",
                        resource_id=str(self.dashboard.id),
                        access_level="editor",
                        organization_member_id=self.other_membership.id,
                    ),
                    contracts.SetObjectAccessControlInput(
                        resource="dashboard",
                        resource_id=str(self.dashboard.id),
                        access_level="editor",
                        organization_member_id=member.id if subject == "member" else None,
                        role_id=role.id if subject == "role" else None,
                    ),
                ],
            )
        assert not AccessControl.objects.filter(team=self.team, resource_id=str(self.dashboard.id)).exists()


class TestEveryMemberHasResourceAccess(BaseTest):
    """`account` inherits from `customer_analytics`, so every rule here is written on the parent,
    which is where resolution reads them from."""

    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        self.agent = User.objects.create_and_join(self.organization, "agent@example.com", "testtest")
        self.agent_membership = OrganizationMembership.objects.get(user=self.agent, organization=self.organization)

    def _everyone_has_access(self) -> bool:
        return every_member_has_resource_access(team_id=self.team.id, resource="account", required_level="viewer")

    def _rule(self, access_level: str, subject: str | None) -> None:
        rule: dict = {
            "team": self.team,
            "resource": "customer_analytics",
            "resource_id": None,
            "access_level": access_level,
        }
        if subject == "member":
            rule["organization_member"] = self.agent_membership
        elif subject == "role":
            rule["role"] = Role.objects.create(organization=self.organization, name="Support")
        AccessControl.objects.create(**rule)

    @parameterized.expand(
        [
            ("no rules", None, None, True),
            ("everyone denied", "none", None, False),
            ("one member denied", "none", "member", False),
            ("one role denied", "none", "role", False),
            ("everyone granted viewer", "viewer", None, True),
            ("one member granted editor", "editor", "member", True),
        ]
    )
    def test_one_restricting_rule_is_enough_to_answer_no(
        self, _name: str, access_level: str | None, subject: str | None, expected: bool
    ) -> None:
        if access_level is not None:
            self._rule(access_level, subject)
        assert self._everyone_has_access() is expected

    def test_rules_are_inert_without_the_entitlement(self) -> None:
        # Resolution hands everyone the built-in default when the organization can't use access
        # control, so a leftover rule must not withhold data from a team that isn't restricted.
        self._rule("none", None)
        self.organization.available_product_features = []
        self.organization.save()
        assert self._everyone_has_access() is True


class TestObjectIdsRestrictedFromAnyMember(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        self.agent = User.objects.create_and_join(self.organization, "agent@example.com", "testtest")
        self.agent_membership = OrganizationMembership.objects.get(user=self.agent, organization=self.organization)
        self.dashboard = Dashboard.objects.create(team=self.team, created_by=self.user)

    def _restricted(self) -> set[str]:
        return object_ids_restricted_from_any_member(
            team_id=self.team.id, resource="dashboard", required_level="viewer"
        )

    def _rule(self, access_level: str, subject: str | None) -> None:
        rule: dict = {
            "team": self.team,
            "resource": "dashboard",
            "resource_id": str(self.dashboard.id),
            "access_level": access_level,
        }
        if subject == "member":
            rule["organization_member"] = self.agent_membership
        elif subject == "role":
            rule["role"] = Role.objects.create(organization=self.organization, name="Support")
        AccessControl.objects.create(**rule)

    @parameterized.expand(
        [
            ("no rules", None, None, False),
            ("everyone denied", "none", None, True),
            ("one member denied", "none", "member", True),
            ("one role denied", "none", "role", True),
            ("everyone granted viewer", "viewer", None, False),
            ("one member granted editor", "editor", "member", False),
        ]
    )
    def test_one_restricting_rule_is_enough_to_name_the_object(
        self, _name: str, access_level: str | None, subject: str | None, expected: bool
    ) -> None:
        if access_level is not None:
            self._rule(access_level, subject)
        assert (str(self.dashboard.id) in self._restricted()) is expected

    def test_names_only_the_restricted_object(self) -> None:
        # A rule on one object must not withhold its neighbours.
        reachable = Dashboard.objects.create(team=self.team, created_by=self.user)
        self._rule("none", None)
        assert self._restricted() == {str(self.dashboard.id)}
        assert str(reachable.id) not in self._restricted()

    def test_resource_scope_rules_are_not_object_rules(self) -> None:
        # A resource-wide rule has no resource_id, so it names no object here.
        AccessControl.objects.create(team=self.team, resource="dashboard", resource_id=None, access_level="none")
        assert self._restricted() == set()

    def test_rules_are_inert_without_the_entitlement(self) -> None:
        self._rule("none", None)
        self.organization.available_product_features = []
        self.organization.save()
        assert self._restricted() == set()


class TestRoleReads(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.role = Role.objects.create(name="Support", organization=self.organization)
        self.other_organization = Organization.objects.create(name="Other")

    def test_role_belongs_only_to_its_own_organization(self) -> None:
        assert role_belongs_to_organization(role_id=self.role.id, organization_id=self.organization.id)
        assert not role_belongs_to_organization(role_id=self.role.id, organization_id=self.other_organization.id)

    def test_member_ids_leave_out_a_membership_from_another_organization(self) -> None:
        self.role.members.add(self.user)
        assert valid_role_member_user_ids(role_id=self.role.id) == [self.user.id]

        outsider = User.objects.create_and_join(self.other_organization, "outsider@posthog.com", "testtest")
        outside_membership = OrganizationMembership.objects.get(user=outsider, organization=self.other_organization)
        RoleMembership.objects.create(role=self.role, user=outsider, organization_member=outside_membership)

        assert valid_role_member_user_ids(role_id=self.role.id) == [self.user.id]
