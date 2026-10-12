import os
from typing import Literal
from uuid import UUID

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import transaction
from django.test import override_settings

from openfga_sdk import CreateStoreRequest
from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.dataclasses import frozen
from posthog.models import Organization, OrganizationMembership, Team, User

from products.access_control.backend.facade import testing as access_control_testing
from products.access_control.backend.facade.api import set_object_access_control
from products.access_control.backend.facade.contracts import SetObjectAccessControlInput
from products.authz.backend.bootstrap import bootstrap_openfga
from products.authz.backend.client import get_openfga_client
from products.authz.backend.facade import api
from products.authz.backend.facade.contracts import CheckRequest, Resource, Subject
from products.authz.backend.facade.enums import Action, ResourceType
from products.dashboards.backend.facade import testing as dashboard_testing
from products.dashboards.backend.facade.enums import PrivilegeLevel, RestrictionLevel

DASHBOARD_PERMISSIONS = {
    "none": frozenset(),
    "viewer": frozenset({Action.VIEW}),
    "editor": frozenset({Action.VIEW, Action.EDIT, Action.DELETE, Action.SHARE}),
    "manager": frozenset({Action.VIEW, Action.EDIT, Action.DELETE, Action.SHARE, Action.MANAGE_ACCESS}),
}


@frozen
class Rule:
    scope: Literal["object", "category", "project"]
    subject: Literal["member", "role", "default"]
    level: str


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class TestOpenFgaDashboardMirror(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        client = get_openfga_client()
        try:
            store = client.create_store(CreateStoreRequest(name="dashboard-mirror-e2e"))
        finally:
            client.close()
        self.environment = patch.dict(
            os.environ,
            {"OPENFGA_STORE_ID": store.id, "OPENFGA_AUTHORIZATION_MODEL_ID": "", "OPENFGA_SYNC_ENABLED": "1"},
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.addCleanup(self._delete_store)
        bootstrap_openfga()
        with self.captureOnCommitCallbacks(execute=True):
            self.organization.available_product_features = [
                {"key": feature, "name": feature}
                for feature in [AvailableFeature.ACCESS_CONTROL, AvailableFeature.ROLE_BASED_ACCESS]
            ]
            self.organization.save()
            self.other_user = User.objects.create_and_join(self.organization, "reader@example.com", "test-password")
            self.membership = OrganizationMembership.objects.get(organization=self.organization, user=self.other_user)
            self.dashboard_id = dashboard_testing.create_dashboard(team_id=self.team.id, created_by_id=self.user.id)
            self.second_dashboard_id = dashboard_testing.create_dashboard(
                team_id=self.team.id, created_by_id=self.user.id
            )
            self.category_rule_id = access_control_testing.create_access_control(
                team_id=self.team.id, resource="dashboard", access_level="none"
            )
        self.subject = Subject(user_id=self.other_user.id)
        self.role_index = 0

    def _delete_store(self) -> None:
        client = get_openfga_client()
        try:
            client.delete_store()
        finally:
            client.close()

    def _resource(self, dashboard_id: int | None = None, team_id: int | None = None) -> Resource:
        return Resource(
            type=ResourceType.DASHBOARD,
            id=str(dashboard_id) if dashboard_id is not None else None,
            project_id=team_id or self.team.id,
        )

    def _grant(self, level: str | None, dashboard_id: int | None = None, role_id: UUID | None = None) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            set_object_access_control(
                team_id=self.team.id,
                input=SetObjectAccessControlInput(
                    resource="dashboard",
                    resource_id=str(dashboard_id or self.dashboard_id),
                    access_level=level,
                    organization_member_id=self.membership.id if role_id is None else None,
                    role_id=role_id,
                ),
            )

    def _check(self, action: Action, dashboard_id: int | None = None) -> bool:
        return api.check(
            resource=self._resource(dashboard_id or self.dashboard_id), action=action, subject=self.subject
        )

    def _add_rule(self, rule: Rule, *, dashboard_id: int | None = None) -> UUID:
        role_id = None
        if rule.subject == "role":
            self.role_index += 1
            role_id = access_control_testing.create_role(
                organization_id=self.organization.id, name=f"Test role {self.role_index}"
            )
            access_control_testing.add_role_member(role_id=role_id, user_id=self.other_user.id)
        resource = "project" if rule.scope == "project" else "dashboard"
        resource_id = (
            str(self.team.id)
            if rule.scope == "project"
            else str(dashboard_id or self.dashboard_id)
            if rule.scope == "object"
            else None
        )
        return access_control_testing.create_access_control(
            team_id=self.team.id,
            resource=resource,
            resource_id=resource_id,
            access_level=rule.level,
            organization_member_id=self.membership.id if rule.subject == "member" else None,
            role_id=role_id,
        )

    def _assert_dashboard_permissions(
        self, expected: frozenset[Action], *, dashboard_id: int | None = None, subject: Subject | None = None
    ) -> None:
        id = dashboard_id or self.dashboard_id
        actor = subject or self.subject
        resource = self._resource(id)
        assert api.check(resource=resource, action=Action.VIEW, subject=actor) == (Action.VIEW in expected)
        actions = [Action.VIEW, Action.EDIT, Action.DELETE, Action.SHARE, Action.MANAGE_ACCESS]
        assert api.check([CheckRequest(resource=resource, action=action, subject=actor) for action in actions]) == [
            action in expected for action in actions
        ]
        assert api.permissions(resource=resource, subject=actor) == expected
        listed = api.list_resources(resource=self._resource(), action=Action.VIEW, subject=actor)
        assert listed.complete
        assert (str(id) in listed.ids) == (Action.VIEW in expected)

    def test_viewer_default_with_member_editor_grant_on_only_one_dashboard(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            access_control_testing.set_access_control_level(
                team_id=self.team.id, rule_id=self.category_rule_id, access_level="viewer"
            )
            third_dashboard_id = dashboard_testing.create_dashboard(team_id=self.team.id, created_by_id=self.user.id)
            another_reader = User.objects.create_and_join(
                self.organization, "another-reader@example.com", "test-password"
            )
        self._grant("editor")

        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS["editor"])
        for dashboard_id in (self.second_dashboard_id, third_dashboard_id):
            self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS["viewer"], dashboard_id=dashboard_id)
        viewable = api.list_resources(resource=self._resource(), action=Action.VIEW, subject=self.subject)
        assert viewable.complete and viewable.ids == frozenset(
            str(id) for id in (self.dashboard_id, self.second_dashboard_id, third_dashboard_id)
        )
        editable = api.list_resources(resource=self._resource(), action=Action.EDIT, subject=self.subject)
        assert editable.complete and editable.ids == frozenset({str(self.dashboard_id)})
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS["viewer"], subject=Subject(user_id=another_reader.id))

        self._grant(None)
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS["viewer"])
        editable = api.list_resources(resource=self._resource(), action=Action.EDIT, subject=self.subject)
        assert editable.complete and not editable.ids

    def test_rule_crud_dashboard_lifecycle_and_scoped_listing(self) -> None:
        assert not self._check(Action.VIEW)
        self._grant("viewer")
        assert self._check(Action.VIEW)
        assert not self._check(Action.EDIT)
        assert api.check(
            [
                CheckRequest(resource=self._resource(self.dashboard_id), action=Action.VIEW, subject=self.subject),
                CheckRequest(
                    resource=self._resource(self.second_dashboard_id), action=Action.VIEW, subject=self.subject
                ),
            ]
        ) == [True, False]
        assert api.permissions(resource=self._resource(self.dashboard_id), subject=self.subject) == frozenset(
            {Action.VIEW}
        )
        listed = api.list_resources(resource=self._resource(), action=Action.VIEW, subject=self.subject)
        assert listed.complete and listed.ids == frozenset({str(self.dashboard_id)})
        assert not api.check(resource=self._resource(), action=Action.CREATE, subject=self.subject)

        self._grant("editor")
        assert self._check(Action.EDIT)
        self._grant("manager")
        assert self._check(Action.MANAGE_ACCESS)
        self._grant(None)
        assert not self._check(Action.VIEW)

        with self.captureOnCommitCallbacks(execute=True):
            access_control_testing.set_access_control_level(
                team_id=self.team.id, rule_id=self.category_rule_id, access_level="viewer"
            )
        assert self._check(Action.VIEW) and not self._check(Action.EDIT)
        with self.captureOnCommitCallbacks(execute=True):
            access_control_testing.set_access_control_level(
                team_id=self.team.id, rule_id=self.category_rule_id, access_level=None
            )
        assert self._check(Action.EDIT)
        self._grant("none")
        assert not self._check(Action.VIEW)
        assert api.check(
            resource=self._resource(self.dashboard_id), action=Action.EDIT, subject=Subject(user_id=self.user.id)
        )
        self._grant(None)

        with self.captureOnCommitCallbacks(execute=True):
            other_team = Team.objects.create(organization=self.organization, name="Other project")
            dashboard_testing.create_dashboard(team_id=other_team.id, created_by_id=self.user.id)
        listed = api.list_resources(resource=self._resource(), action=Action.VIEW, subject=self.subject)
        assert listed.complete and listed.ids == frozenset({str(self.dashboard_id), str(self.second_dashboard_id)})
        capped = api.list_resources(resource=self._resource(), action=Action.VIEW, subject=self.subject, limit=1)
        assert not capped.complete and not capped.ids
        assert not api.check(
            resource=self._resource(self.dashboard_id, other_team.id), action=Action.VIEW, subject=self.subject
        )

        with self.captureOnCommitCallbacks(execute=True):
            dashboard_testing.set_dashboard_deleted(team_id=self.team.id, dashboard_id=self.dashboard_id, deleted=True)
        assert not self._check(Action.VIEW)
        with self.captureOnCommitCallbacks(execute=True):
            dashboard_testing.set_dashboard_deleted(team_id=self.team.id, dashboard_id=self.dashboard_id, deleted=False)
        assert self._check(Action.EDIT)
        with self.captureOnCommitCallbacks(execute=True):
            dashboard_testing.delete_dashboard(team_id=self.team.id, dashboard_id=self.dashboard_id)
        assert not self._check(Action.VIEW)

    def test_role_changes_member_override_and_rollback(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            role_id = access_control_testing.create_role(organization_id=self.organization.id, name="Reviewers")
            access_control_testing.add_role_member(role_id=role_id, user_id=self.other_user.id)
        self._grant("editor", role_id=role_id)
        assert self._check(Action.EDIT)
        self._grant("viewer")
        assert self._check(Action.VIEW) and not self._check(Action.EDIT)
        self._grant(None)
        assert self._check(Action.EDIT)
        with self.captureOnCommitCallbacks(execute=True):
            access_control_testing.remove_role_member(role_id=role_id, user_id=self.other_user.id)
        assert not self._check(Action.VIEW)
        self._grant("viewer")
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    set_object_access_control(
                        team_id=self.team.id,
                        input=SetObjectAccessControlInput(
                            resource="dashboard",
                            resource_id=str(self.dashboard_id),
                            access_level="none",
                            organization_member_id=self.membership.id,
                        ),
                    )
                    raise ValueError("Rollback")
            except ValueError:
                pass
        assert self._check(Action.VIEW)
        assert not self._check(Action.EDIT)

    @parameterized.expand(
        [
            (f"{rule.scope}_{rule.subject}_{rule.level}", rule)
            for level in ("none", "viewer", "editor", "manager")
            for rule in (
                Rule(scope="object", subject="member", level=level),
                Rule(scope="object", subject="role", level=level),
                Rule(scope="object", subject="default", level=level),
                Rule(scope="category", subject="member", level=level),
                Rule(scope="category", subject="role", level=level),
                Rule(scope="category", subject="default", level=level),
            )
        ]
    )
    def test_user_has_the_dashboard_permissions_their_rule_grants(self, _name: str, rule: Rule) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            if rule.scope == "category" and rule.subject == "default":
                access_control_testing.set_access_control_level(
                    team_id=self.team.id, rule_id=self.category_rule_id, access_level=rule.level
                )
            else:
                self._add_rule(rule)
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS[rule.level])
        expected_second = (
            DASHBOARD_PERMISSIONS[rule.level] if rule.scope == "category" else DASHBOARD_PERMISSIONS["none"]
        )
        self._assert_dashboard_permissions(expected_second, dashboard_id=self.second_dashboard_id)

    @parameterized.expand(
        [
            (
                "member_viewer_beats_role_manager",
                (
                    Rule(scope="object", subject="member", level="viewer"),
                    Rule(scope="object", subject="role", level="manager"),
                ),
                "viewer",
            ),
            (
                "member_none_beats_role_manager",
                (
                    Rule(scope="object", subject="member", level="none"),
                    Rule(scope="object", subject="role", level="manager"),
                ),
                "none",
            ),
            (
                "member_editor_beats_role_none",
                (
                    Rule(scope="object", subject="member", level="editor"),
                    Rule(scope="object", subject="role", level="none"),
                ),
                "editor",
            ),
            (
                "role_viewer_beats_object_default_manager",
                (
                    Rule(scope="object", subject="role", level="viewer"),
                    Rule(scope="object", subject="default", level="manager"),
                ),
                "viewer",
            ),
            (
                "role_none_beats_object_default_manager",
                (
                    Rule(scope="object", subject="role", level="none"),
                    Rule(scope="object", subject="default", level="manager"),
                ),
                "none",
            ),
            (
                "highest_role_manager_beats_none",
                (
                    Rule(scope="object", subject="role", level="none"),
                    Rule(scope="object", subject="role", level="manager"),
                ),
                "manager",
            ),
            (
                "highest_role_editor_beats_viewer",
                (
                    Rule(scope="object", subject="role", level="viewer"),
                    Rule(scope="object", subject="role", level="editor"),
                ),
                "editor",
            ),
            (
                "highest_role_viewer_beats_none",
                (
                    Rule(scope="object", subject="role", level="none"),
                    Rule(scope="object", subject="role", level="viewer"),
                ),
                "viewer",
            ),
            (
                "object_default_viewer_beats_category_member_manager",
                (
                    Rule(scope="object", subject="default", level="viewer"),
                    Rule(scope="category", subject="member", level="manager"),
                ),
                "viewer",
            ),
            (
                "object_default_none_beats_category_member_manager",
                (
                    Rule(scope="object", subject="default", level="none"),
                    Rule(scope="category", subject="member", level="manager"),
                ),
                "none",
            ),
            (
                "object_default_editor_beats_category_member_none",
                (
                    Rule(scope="object", subject="default", level="editor"),
                    Rule(scope="category", subject="member", level="none"),
                ),
                "editor",
            ),
            (
                "object_role_editor_beats_category_member_none",
                (
                    Rule(scope="object", subject="role", level="editor"),
                    Rule(scope="category", subject="member", level="none"),
                ),
                "editor",
            ),
            (
                "object_role_viewer_beats_category_role_manager",
                (
                    Rule(scope="object", subject="role", level="viewer"),
                    Rule(scope="category", subject="role", level="manager"),
                ),
                "viewer",
            ),
            (
                "object_member_viewer_beats_category_member_manager",
                (
                    Rule(scope="object", subject="member", level="viewer"),
                    Rule(scope="category", subject="member", level="manager"),
                ),
                "viewer",
            ),
            (
                "category_member_viewer_beats_role_manager",
                (
                    Rule(scope="category", subject="member", level="viewer"),
                    Rule(scope="category", subject="role", level="manager"),
                ),
                "viewer",
            ),
            (
                "category_member_none_beats_role_editor",
                (
                    Rule(scope="category", subject="member", level="none"),
                    Rule(scope="category", subject="role", level="editor"),
                ),
                "none",
            ),
            (
                "category_member_editor_beats_role_none",
                (
                    Rule(scope="category", subject="member", level="editor"),
                    Rule(scope="category", subject="role", level="none"),
                ),
                "editor",
            ),
            (
                "category_highest_role_manager_beats_none",
                (
                    Rule(scope="category", subject="role", level="none"),
                    Rule(scope="category", subject="role", level="manager"),
                ),
                "manager",
            ),
        ]
    )
    def test_dashboard_access_uses_the_most_specific_rule(
        self, _name: str, rules: tuple[Rule, ...], level: str
    ) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            for rule in rules:
                self._add_rule(rule)
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS[level])

    @parameterized.expand(
        [("admin", OrganizationMembership.Level.ADMIN), ("owner", OrganizationMembership.Level.OWNER)]
    )
    def test_organization_admin_and_owner_can_access_private_dashboards(
        self, _name: str, level: OrganizationMembership.Level
    ) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            self.membership.level = level
            self.membership.save(update_fields=["level"])
            self._add_rule(Rule(scope="project", subject="default", level="none"))
            self._add_rule(Rule(scope="project", subject="member", level="none"))
            self._add_rule(Rule(scope="category", subject="member", level="none"))
            self._add_rule(Rule(scope="object", subject="member", level="none"))
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS["manager"])
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS["manager"], dashboard_id=self.second_dashboard_id)

    @parameterized.expand(
        [("admin", OrganizationMembership.Level.ADMIN), ("owner", OrganizationMembership.Level.OWNER)]
    )
    def test_organization_demotion_restores_the_members_actual_dashboard_grant(
        self, _name: str, level: OrganizationMembership.Level
    ) -> None:
        self._grant("viewer")
        with self.captureOnCommitCallbacks(execute=True):
            self.membership.level = level
            self.membership.save(update_fields=["level"])
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS["manager"])
        with self.captureOnCommitCallbacks(execute=True):
            self.membership.level = OrganizationMembership.Level.MEMBER
            self.membership.save(update_fields=["level"])
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS["viewer"])
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS["none"], dashboard_id=self.second_dashboard_id)

    def test_non_admin_creator_can_access_their_private_dashboard(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            id = dashboard_testing.create_dashboard(team_id=self.team.id, created_by_id=self.other_user.id)
            self._add_rule(Rule(scope="project", subject="default", level="none"))
            self._add_rule(Rule(scope="project", subject="member", level="member"))
            self._add_rule(Rule(scope="object", subject="member", level="none"), dashboard_id=id)
            dashboard_testing.set_dashboard_restriction(
                team_id=self.team.id, dashboard_id=id, level=RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
            )
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS["manager"], dashboard_id=id)
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS["none"], dashboard_id=self.dashboard_id)

    def test_changing_creator_adds_and_removes_the_non_admins_inherent_access(self) -> None:
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS["none"])
        with self.captureOnCommitCallbacks(execute=True):
            dashboard_testing.set_dashboard_creator(
                team_id=self.team.id, dashboard_id=self.dashboard_id, user_id=self.other_user.id
            )
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS["manager"])
        with self.captureOnCommitCallbacks(execute=True):
            dashboard_testing.set_dashboard_creator(team_id=self.team.id, dashboard_id=self.dashboard_id, user_id=None)
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS["none"])

    @parameterized.expand([("member", "member"), ("role", "role"), ("default", "default")])
    def test_project_admin_can_manage_access_without_bypassing_dashboard_denials(
        self, _name: str, subject: Literal["member", "role", "default"]
    ) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            self._add_rule(Rule(scope="project", subject=subject, level="admin"))
            self._add_rule(Rule(scope="object", subject="member", level="none"))
        self._assert_dashboard_permissions(frozenset({Action.MANAGE_ACCESS}))
        assert api.check(
            resource=Resource(type=ResourceType.PROJECT, id=str(self.team.id)), action=Action.EDIT, subject=self.subject
        )

    @parameterized.expand([("member", "member"), ("role", "role"), ("default", "default")])
    def test_project_denial_blocks_an_object_grant(
        self, _name: str, subject: Literal["member", "role", "default"]
    ) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            self._add_rule(Rule(scope="project", subject=subject, level="none"))
            self._add_rule(Rule(scope="object", subject="member", level="manager"))
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS["none"])

    @parameterized.expand([("member", "member"), ("role", "role")])
    def test_explicit_project_members_can_access_their_granted_dashboard_in_a_private_project(
        self, _name: str, subject: Literal["member", "role"]
    ) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            self._add_rule(Rule(scope="project", subject="default", level="none"))
            self._add_rule(Rule(scope="project", subject=subject, level="member"))
            self._add_rule(Rule(scope="object", subject="member", level="editor"))
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS["editor"])
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS["none"], dashboard_id=self.second_dashboard_id)

    def test_project_member_denial_beats_a_role_admin_grant(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            self._add_rule(Rule(scope="project", subject="role", level="admin"))
            self._add_rule(Rule(scope="project", subject="member", level="none"))
            self._add_rule(Rule(scope="object", subject="member", level="manager"))
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS["none"])

    def test_creator_still_needs_project_access(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            dashboard_testing.set_dashboard_creator(
                team_id=self.team.id, dashboard_id=self.dashboard_id, user_id=self.other_user.id
            )
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS["manager"])
        with self.captureOnCommitCallbacks(execute=True):
            self._add_rule(Rule(scope="project", subject="member", level="none"))
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS["none"])

    def test_removed_members_cannot_access_but_rejoining_restores_their_role_grant(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            self._add_rule(Rule(scope="object", subject="role", level="editor"))
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS["editor"])
        with self.captureOnCommitCallbacks(execute=True):
            self.membership.delete()
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS["none"])
        with self.captureOnCommitCallbacks(execute=True):
            self.membership = OrganizationMembership.objects.create(
                organization=self.organization, user=self.other_user, level=OrganizationMembership.Level.MEMBER
            )
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS["editor"])

    def test_legacy_collaborator_grants_update_and_revoke_without_losing_view_access(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            self._add_rule(Rule(scope="project", subject="member", level="member"))
            self._add_rule(Rule(scope="object", subject="member", level="editor"))
            dashboard_testing.set_dashboard_restriction(
                team_id=self.team.id, dashboard_id=self.dashboard_id, level=RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
            )
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS["viewer"])
        for level in (PrivilegeLevel.CAN_EDIT, PrivilegeLevel.CAN_VIEW, PrivilegeLevel.CAN_EDIT, None):
            with self.captureOnCommitCallbacks(execute=True):
                dashboard_testing.set_dashboard_collaborator(
                    team_id=self.team.id, dashboard_id=self.dashboard_id, user_id=self.other_user.id, level=level
                )
            expected = "editor" if level == PrivilegeLevel.CAN_EDIT else "viewer"
            self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS[expected])

    @parameterized.expand([("editor", "editor"), ("viewer", "viewer")])
    def test_project_admin_legacy_bypass_respects_the_object_grant(self, _name: str, level: str) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            self._add_rule(Rule(scope="project", subject="member", level="admin"))
            self._add_rule(Rule(scope="object", subject="member", level=level))
            dashboard_testing.set_dashboard_restriction(
                team_id=self.team.id, dashboard_id=self.dashboard_id, level=RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
            )
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS[level] | {Action.MANAGE_ACCESS})

    def test_without_access_control_entitlement_stale_denials_do_not_hide_dashboards(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            self._add_rule(Rule(scope="project", subject="member", level="none"))
            self._add_rule(Rule(scope="object", subject="member", level="none"))
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS["none"])
        with self.captureOnCommitCallbacks(execute=True):
            self.organization.available_product_features = []
            self.organization.save(update_fields=["available_product_features"])
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS["editor"])
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS["editor"], dashboard_id=self.second_dashboard_id)

    @parameterized.expand([("role_grant", "editor", "none"), ("role_denial", "none", "viewer")])
    def test_role_entitlement_changes_restore_the_correct_dashboard_access(
        self, _name: str, role_level: str, default_level: str
    ) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            access_control_testing.set_access_control_level(
                team_id=self.team.id, rule_id=self.category_rule_id, access_level=default_level
            )
            self._add_rule(Rule(scope="category", subject="role", level=role_level))
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS[role_level])
        with self.captureOnCommitCallbacks(execute=True):
            self.organization.available_product_features = [
                {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
            ]
            self.organization.save(update_fields=["available_product_features"])
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS[default_level])
        with self.captureOnCommitCallbacks(execute=True):
            self.organization.available_product_features.append(
                {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS}
            )
            self.organization.save(update_fields=["available_product_features"])
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS[role_level])

    def test_foreign_organization_admin_cannot_access_but_a_valid_local_grant_works(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            other_org = Organization.objects.create(name="Other organization")
            OrganizationMembership.objects.create(
                organization=other_org, user=self.other_user, level=OrganizationMembership.Level.ADMIN
            )
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS["none"])
        self._grant("viewer")
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS["viewer"])

    @parameterized.expand([("member", "member"), ("role", "role")])
    def test_foreign_subject_rules_do_not_override_a_valid_local_grant(
        self, _name: str, subject: Literal["member", "role"]
    ) -> None:
        self._grant("viewer")
        with self.captureOnCommitCallbacks(execute=True):
            other_org = Organization.objects.create(name="Foreign subjects")
            other_membership = OrganizationMembership.objects.create(
                organization=other_org, user=self.other_user, level=OrganizationMembership.Level.MEMBER
            )
            role_id = (
                access_control_testing.create_role(organization_id=other_org.id, name="Foreign role")
                if subject == "role"
                else None
            )
            if role_id is not None:
                access_control_testing.add_role_member(role_id=role_id, user_id=self.other_user.id)
            access_control_testing.create_access_control(
                team_id=self.team.id,
                resource="dashboard",
                resource_id=str(self.dashboard_id),
                access_level="none",
                organization_member_id=other_membership.id if subject == "member" else None,
                role_id=role_id,
            )
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS["viewer"])

    def test_non_member_cannot_access_a_dashboard_default_grant(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            other_org = Organization.objects.create(name="Outside organization")
            outsider = User.objects.create_and_join(other_org, "outside@example.com", "test-password")
            self._add_rule(Rule(scope="object", subject="default", level="manager"))
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS["manager"])
        self._assert_dashboard_permissions(DASHBOARD_PERMISSIONS["none"], subject=Subject(user_id=outsider.id))

    def test_backfill_preserves_every_authorized_dashboard_across_pages_and_write_batches(self) -> None:
        with patch.dict(os.environ, {"OPENFGA_SYNC_ENABLED": "0"}):
            ids = {
                dashboard_testing.create_dashboard(team_id=self.team.id, created_by_id=self.user.id) for _ in range(32)
            }
            self._add_rule(Rule(scope="category", subject="member", level="editor"))
        expected_ids = ids | {self.dashboard_id, self.second_dashboard_id}
        api.synchronize_organization(self.organization.id)
        api.synchronize_organization(self.organization.id)
        assert api.check(
            [
                CheckRequest(resource=self._resource(id), action=Action.VIEW, subject=self.subject)
                for id in sorted(expected_ids)
            ]
        ) == [True] * len(expected_ids)
        listed = api.list_resources(
            resource=self._resource(), action=Action.VIEW, subject=self.subject, limit=len(expected_ids)
        )
        assert listed.complete and listed.ids == frozenset(str(id) for id in expected_ids)
