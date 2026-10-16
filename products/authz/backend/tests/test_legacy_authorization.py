from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.authz import check_dashboard_category_access
from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, Team, User

from products.access_control.backend.facade import testing as access_testing
from products.authz.backend.facade import api
from products.authz.backend.facade.contracts import CheckRequest, Resource, Subject
from products.authz.backend.facade.enums import Action, ResourceType
from products.dashboards.backend.facade import testing as dashboard_testing
from products.dashboards.backend.facade.enums import PrivilegeLevel, RestrictionLevel


class TestLegacyAuthorization(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        flag = patch("products.authz.backend.logic.rollout.get_feature_flag_or_none", return_value="v1")
        flag.start()
        self.addCleanup(flag.stop)
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        self.reader = User.objects.create_and_join(self.organization, "reader@example.com", "test-password")
        self.subject = Subject(user_id=self.reader.id)
        self.dashboard_id = dashboard_testing.create_dashboard(team_id=self.team.id, created_by_id=self.user.id)
        self.resource = Resource(type=ResourceType.DASHBOARD, id=str(self.dashboard_id), project_id=self.team.id)
        self.dashboards = Resource(type=ResourceType.DASHBOARD, project_id=self.team.id)
        self.enterContext(api.authorization_session())

    @parameterized.expand(
        [
            ("none", "none", frozenset()),
            ("viewer", "viewer", frozenset({Action.VIEW})),
            ("editor", "editor", frozenset({Action.VIEW, Action.EDIT, Action.DELETE, Action.SHARE})),
            (
                "manager",
                "manager",
                frozenset({Action.VIEW, Action.EDIT, Action.DELETE, Action.SHARE, Action.MANAGE_ACCESS}),
            ),
        ]
    )
    def test_object_overrides_preserve_legacy_permissions_and_lists(
        self, _name: str, level: str, expected: frozenset[Action]
    ) -> None:
        access_testing.create_access_control(team_id=self.team.id, resource="dashboard", access_level="none")
        membership = OrganizationMembership.objects.get(organization=self.organization, user=self.reader)
        access_testing.create_access_control(
            team_id=self.team.id,
            resource="dashboard",
            resource_id=str(self.dashboard_id),
            access_level=level,
            organization_member_id=membership.id,
        )
        assert api.permissions(resource=self.resource, subject=self.subject) == expected
        assert api.check(
            [
                CheckRequest(resource=self.resource, action=Action.VIEW, subject=self.subject),
                CheckRequest(resource=self.resource, action=Action.EDIT, subject=self.subject),
            ]
        ) == [Action.VIEW in expected, Action.EDIT in expected]
        listed = api.list_objects(resource=self.dashboards, action=Action.VIEW, subject=self.subject)
        assert listed.complete
        assert listed.allows(str(self.dashboard_id)) == (Action.VIEW in expected)
        assert not api.check(resource=self.dashboards, action=Action.CREATE, subject=self.subject)

    @parameterized.expand(
        [
            ("recording_playlist", ResourceType.SESSION_RECORDING_PLAYLIST, "session_recording"),
            ("dashboard_template", ResourceType.DASHBOARD_TEMPLATE, "dashboard"),
            ("warehouse_table", ResourceType.WAREHOUSE_TABLE, "warehouse_objects"),
            ("llm_prompt", ResourceType.LLM_PROMPT, "llm_analytics"),
        ]
    )
    def test_inherited_category_permissions_use_the_parent_resource(
        self, _name: str, child: ResourceType, parent: str
    ) -> None:
        access_testing.create_access_control(team_id=self.team.id, resource=parent, access_level="viewer")
        resource = Resource(type=child, project_id=self.team.id)
        assert api.permissions(resource=resource, subject=self.subject) == frozenset({Action.VIEW})

    def test_project_denial_tenant_scope_and_missing_objects_fail_closed(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        wrong_scope = Resource(type=ResourceType.DASHBOARD, id=str(self.dashboard_id), project_id=other_team.id)
        assert not api.check(resource=wrong_scope, action=Action.VIEW, subject=self.subject)
        other_organization = Organization.objects.create(name="Other organization")
        with self.assertRaises(ValueError):
            api.check(
                resource=Resource(
                    type=ResourceType.DASHBOARD,
                    id=str(self.dashboard_id),
                    project_id=self.team.id,
                    organization_id=other_organization.id,
                ),
                action=Action.VIEW,
                subject=self.subject,
            )
        access_testing.create_access_control(team_id=self.team.id, resource="dashboard", access_level="none")
        assert not check_dashboard_category_access(self.reader, self.team, Action.VIEW, require_category=False)
        dashboard_testing.create_dashboard(team_id=self.team.id, created_by_id=self.reader.id)
        assert check_dashboard_category_access(self.reader, self.team, Action.VIEW, require_category=False)
        access_testing.create_access_control(
            team_id=self.team.id, resource="project", resource_id=str(self.team.id), access_level="none"
        )
        assert not api.check(resource=self.resource, action=Action.VIEW, subject=self.subject)
        assert not check_dashboard_category_access(self.reader, self.team, Action.VIEW, require_category=False)
        assert not api.list_objects(resource=self.dashboards, action=Action.VIEW, subject=self.subject).allows(
            str(self.dashboard_id)
        )
        assert not api.list_objects(
            resource=self.dashboards, action=Action.VIEW, subject=self.subject, creator_exempt=True
        ).allows(str(self.dashboard_id), created_by_user_id=self.reader.id, subject_user_id=self.reader.id)
        dashboard_testing.delete_dashboard(team_id=self.team.id, dashboard_id=self.dashboard_id)
        assert not api.check(resource=self.resource, action=Action.VIEW, subject=Subject(user_id=self.user.id))

    @parameterized.expand(
        [
            ("member", OrganizationMembership.Level.MEMBER, False, False),
            ("admin", OrganizationMembership.Level.ADMIN, True, False),
            ("owner", OrganizationMembership.Level.OWNER, True, True),
        ]
    )
    def test_organization_project_and_role_checks_preserve_membership_levels(
        self, _name: str, level: int, is_admin: bool, is_owner: bool
    ) -> None:
        membership = OrganizationMembership.objects.get(organization=self.organization, user=self.reader)
        membership.level = level
        membership.save()
        access_testing.create_access_control(
            team_id=self.team.id, resource="project", resource_id=str(self.team.id), access_level="member"
        )
        organization = Resource(type=ResourceType.ORGANIZATION, id=str(self.organization.id))
        project = Resource(type=ResourceType.PROJECT, id=str(self.team.id))
        role_id = access_testing.create_role(organization_id=self.organization.id, name="Reviewers")
        role = Resource(type=ResourceType.ROLE, id=str(role_id), organization_id=self.organization.id)
        for resource in (organization, project, role):
            assert api.check(resource=resource, action=Action.VIEW, subject=self.subject)
            assert api.check(resource=resource, action=Action.EDIT, subject=self.subject) is is_admin
            assert api.check(resource=resource, action=Action.MANAGE_ACCESS, subject=self.subject) is is_admin
        assert api.check(resource=organization, action=Action.DELETE, subject=self.subject) is is_owner
        other_organization = Organization.objects.create(name="Other organization")
        assert not api.check(
            resource=Resource(type=ResourceType.ROLE, id=str(role_id), organization_id=other_organization.id),
            action=Action.VIEW,
            subject=self.subject,
        )

    def test_collaborator_restriction_and_list_limit(self) -> None:
        access_testing.create_access_control(
            team_id=self.team.id, resource="project", resource_id=str(self.team.id), access_level="member"
        )
        dashboard_testing.set_dashboard_restriction(
            team_id=self.team.id, dashboard_id=self.dashboard_id, level=RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        )
        assert api.permissions(resource=self.resource, subject=self.subject) == frozenset({Action.VIEW})
        dashboard_testing.set_dashboard_collaborator(
            team_id=self.team.id, dashboard_id=self.dashboard_id, user_id=self.reader.id, level=PrivilegeLevel.CAN_EDIT
        )
        assert api.check(resource=self.resource, action=Action.EDIT, subject=self.subject)
        second_id = dashboard_testing.create_dashboard(team_id=self.team.id, created_by_id=self.user.id)
        for id in (self.dashboard_id, second_id):
            access_testing.create_access_control(
                team_id=self.team.id, resource="dashboard", resource_id=str(id), access_level="viewer"
            )
        capped = api.list_objects(resource=self.dashboards, action=Action.VIEW, subject=self.subject, limit=1)
        assert not capped.complete and not capped.ids
        assert api.check(resource=self.resource, action=Action.MANAGE_ACCESS, subject=Subject(user_id=self.user.id))

    def test_builtin_denial_applies_without_access_control_entitlement(self) -> None:
        self.organization.available_product_features = []
        self.organization.save()
        result = api.list_objects(
            resource=Resource(type=ResourceType.DATA_DELETION, project_id=self.team.id),
            action=Action.VIEW,
            subject=self.subject,
        )
        assert not result.allows("1")
