from typing import Any
from uuid import UUID

import pytest
from posthog.test.base import BaseTest

from django.contrib.auth.models import AnonymousUser
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, Team, User

from products.access_control.backend.facade.testing import create_access_control
from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.authorization.backend.facade import api as authorization
from products.authorization.backend.facade.contracts import CheckRequest, Context, Parent, Resource, Subject
from products.authorization.backend.facade.enums import Action, ResourceType
from products.authorization.backend.middleware import AuthorizationSessionMiddleware
from products.authorization.backend.presentation.resources import resource_for_object
from products.dashboards.backend.models.dashboard import Dashboard
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSource

V1_LEVELS = {Action.VIEW: "viewer", Action.CREATE: "editor", Action.EDIT: "editor", Action.DELETE: "editor"}
OBJECT_ACTIONS = [Action.VIEW, Action.EDIT, Action.DELETE, Action.MANAGE_ACCESS]
CATEGORY_ACTIONS = [Action.VIEW, Action.CREATE, Action.MANAGE_ACCESS]


class TestCheckMatchesCurrentRules(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        self.other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "testtest")
        self.dashboard = Dashboard.objects.create(team=self.team, name="Revenue", created_by=self.other_user)

    def _rule(self, resource: str, level: str, resource_id: str | None = None, member: bool = False) -> None:
        create_access_control(
            team_id=self.team.id,
            resource=resource,
            access_level=level,
            resource_id=resource_id,
            organization_member_id=self.organization_membership.id if member else None,
        )

    def _v1(self, action: Action, obj: Any = None) -> bool:
        access = UserAccessControl(self.user, self.team)
        if obj is None:
            if action == Action.MANAGE_ACCESS:
                return access.check_can_modify_access_levels_for_object(self.team)
            return access.check_access_level_for_resource("dashboard", V1_LEVELS[action])  # type: ignore[arg-type]
        if action == Action.MANAGE_ACCESS:
            return access.check_can_modify_access_levels_for_object(obj)
        return access.check_access_level_for_object(obj, V1_LEVELS[action])  # type: ignore[arg-type]

    @parameterized.expand(
        [
            ("no_rules",),
            ("resource_none",),
            ("object_none",),
            ("member_viewer_on_object",),
            ("member_editor_on_object",),
            ("member_manager_on_object",),
            ("creator_with_object_none",),
            ("project_admin_with_object_none",),
            ("org_admin_with_object_none",),
        ]
    )
    def test_object_check_matches_v1(self, scenario: str) -> None:
        dashboard_id = str(self.dashboard.id)
        if scenario == "resource_none":
            self._rule("dashboard", "none")
        elif scenario in ("object_none", "creator_with_object_none", "project_admin_with_object_none"):
            self._rule("dashboard", "none", dashboard_id)
        elif scenario in ("member_viewer_on_object", "member_editor_on_object"):
            self._rule("dashboard", "none")
            self._rule("dashboard", scenario.split("_")[1], dashboard_id, member=True)
        elif scenario == "member_manager_on_object":
            self._rule("dashboard", "manager", dashboard_id, member=True)
        elif scenario == "org_admin_with_object_none":
            self._rule("dashboard", "none", dashboard_id)
            self.organization_membership.level = OrganizationMembership.Level.ADMIN
            self.organization_membership.save()
        if scenario == "creator_with_object_none":
            self.dashboard.created_by = self.user
            self.dashboard.save()
        if scenario == "project_admin_with_object_none":
            self._rule("project", "admin", str(self.team.id), member=True)

        resource = resource_for_object(self.dashboard)
        results = authorization.check(
            [
                CheckRequest(resource=resource, action=action, subject=Subject(user_id=self.user.id))
                for action in OBJECT_ACTIONS
            ]
        )

        assert results == [self._v1(action, self.dashboard) for action in OBJECT_ACTIONS]

    @parameterized.expand([("no_rules",), ("resource_none",), ("member_viewer_on_resource",), ("project_admin",)])
    def test_category_check_matches_v1(self, scenario: str) -> None:
        if scenario == "resource_none":
            self._rule("dashboard", "none")
        elif scenario == "member_viewer_on_resource":
            self._rule("dashboard", "none")
            self._rule("dashboard", "viewer", member=True)
        elif scenario == "project_admin":
            self._rule("project", "admin", str(self.team.id), member=True)

        category = Resource(type=ResourceType.DASHBOARD, project_id=self.team.id)
        results = [
            authorization.check(resource=category, action=action, subject=Subject(user_id=self.user.id))
            for action in CATEGORY_ACTIONS
        ]

        assert results == [self._v1(action) for action in CATEGORY_ACTIONS]

    @parameterized.expand([("sourced_table", True, False), ("self_managed_table", False, True)])
    def test_warehouse_table_falls_back_to_its_source(self, _name: str, sourced: bool, expected: bool) -> None:
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id="src",
            connection_id="conn",
            destination_id="dest",
            source_type="Stripe",
            prefix="test",
        )
        table = DataWarehouseTable.objects.create(
            name="customers",
            format="Parquet",
            team=self.team,
            external_data_source=source if sourced else None,
            columns={},
        )
        self._rule("external_data_source", "none", str(source.id))

        allowed = authorization.check(
            resource=resource_for_object(table), action=Action.VIEW, subject=Subject(user_id=self.user.id)
        )

        assert allowed is expected
        assert allowed == UserAccessControl(self.user, self.team).check_access_level_for_object(table, "viewer")

    def test_check_without_a_subject_reads_the_user_that_authentication_set(self) -> None:
        self._rule("dashboard", "none", str(self.dashboard.id), member=True)
        results: list[bool] = []

        def view(request: HttpRequest) -> HttpResponse:
            # DRF sets the user here, after every middleware has run.
            request.user = self.other_user
            results.append(authorization.check(resource=resource_for_object(self.dashboard), action=Action.EDIT))
            return HttpResponse()

        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        AuthorizationSessionMiddleware(view)(request)

        assert results == [True]

    @parameterized.expand([("no_session", False), ("task_session", True)])
    def test_check_without_a_subject_outside_a_request_raises(self, _name: str, in_session: bool) -> None:
        resource = resource_for_object(self.dashboard)

        with pytest.raises(ValueError, match="Pass a subject"):
            if in_session:
                with authorization.authorization_session():
                    authorization.check(resource=resource, action=Action.VIEW)
            else:
                authorization.check(resource=resource, action=Action.VIEW)

    def test_rule_write_clears_the_rules_a_session_loaded(self) -> None:
        resource = resource_for_object(self.dashboard)
        subject = Subject(user_id=self.user.id)

        with authorization.authorization_session():
            before = authorization.check(resource=resource, action=Action.EDIT, subject=subject)
            self._rule("dashboard", "none", str(self.dashboard.id))
            after = authorization.check(resource=resource, action=Action.EDIT, subject=subject)

        assert (before, after) == (True, False)

    def test_rolled_back_grant_is_not_kept(self) -> None:
        self._rule("dashboard", "none", str(self.dashboard.id))
        resource = resource_for_object(self.dashboard)
        subject = Subject(user_id=self.user.id)

        with authorization.authorization_session():
            with pytest.raises(RuntimeError):
                with transaction.atomic():
                    self._rule("dashboard", "editor", str(self.dashboard.id), member=True)
                    during = authorization.check(resource=resource, action=Action.EDIT, subject=subject)
                    raise RuntimeError
            after = authorization.check(resource=resource, action=Action.EDIT, subject=subject)

        assert (during, after) == (True, False)

    def test_rolled_back_user_deletion_is_not_kept(self) -> None:
        user = User.objects.create_and_join(self.organization, "third@posthog.com", "testtest")
        resource = resource_for_object(self.dashboard)
        subject = Subject(user_id=user.id)

        with authorization.authorization_session():
            with pytest.raises(RuntimeError):
                with transaction.atomic():
                    self._rule("dashboard", "editor", str(self.dashboard.id))
                    User.objects.filter(pk=user.id).delete()
                    during = authorization.check(resource=resource, action=Action.VIEW, subject=subject)
                    raise RuntimeError
            after = authorization.check(resource=resource, action=Action.VIEW, subject=subject)

        assert (during, after) == (False, True)

    def test_session_answers_each_team_with_its_own_rules(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        other_dashboard = Dashboard.objects.create(team=other_team, name="Costs", created_by=self.other_user)
        create_access_control(
            team_id=other_team.id, resource="dashboard", access_level="none", resource_id=str(other_dashboard.id)
        )
        subject = Subject(user_id=self.user.id)

        with authorization.authorization_session():
            results = [
                authorization.check(resource=resource_for_object(dashboard), action=Action.EDIT, subject=subject)
                for dashboard in (self.dashboard, other_dashboard, self.dashboard)
            ]

        assert results == [True, False, True]

    def test_project_admin_cannot_manage_a_dashboard_in_another_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        other_dashboard = Dashboard.objects.create(team=other_team, name="Costs", created_by=self.other_user)
        self._rule("project", "admin", str(self.team.id), member=True)
        subject = Subject(user_id=self.user.id)

        own_team = authorization.check(
            resource=resource_for_object(self.dashboard), action=Action.MANAGE_ACCESS, subject=subject
        )
        other = authorization.check(
            resource=resource_for_object(other_dashboard), action=Action.MANAGE_ACCESS, subject=subject
        )
        other_with_view_team = authorization.check(
            resource=resource_for_object(other_dashboard, team=self.team),
            action=Action.MANAGE_ACCESS,
            subject=subject,
        )

        assert (own_team, other, other_with_view_team) == (True, False, False)

    def test_resource_for_object_with_a_team_reads_that_team_rules(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        source = ExternalDataSource.objects.create(
            team_id=other_team.pk,
            source_id="src",
            connection_id="conn",
            destination_id="dest",
            source_type="Stripe",
            prefix="test",
        )
        create_access_control(
            team_id=other_team.id, resource="external_data_source", access_level="none", resource_id=str(source.id)
        )
        subject = Subject(user_id=self.user.id)

        own_team = authorization.check(resource=resource_for_object(source), action=Action.EDIT, subject=subject)
        view_team = authorization.check(
            resource=resource_for_object(source, team=self.team), action=Action.EDIT, subject=subject
        )

        assert (own_team, view_team) == (False, True)
        assert view_team == UserAccessControl(self.user, self.team).check_access_level_for_object(source, "editor")

    @parameterized.expand(
        [
            (
                "organization",
                {"resource": Resource(type=ResourceType.ORGANIZATION, id=str(UUID(int=1)))},
                NotImplementedError,
            ),
            ("action_without_a_level", {"action": Action.JOIN}, ValueError),
            ("no_project", {"resource": Resource(type=ResourceType.DASHBOARD, id="1")}, ValueError),
            (
                "warehouse_table_without_parent",
                {"resource": Resource(type=ResourceType.WAREHOUSE_TABLE, id="1", project_id=1)},
                ValueError,
            ),
            (
                "parent_of_another_type",
                {
                    "resource": Resource(
                        type=ResourceType.WAREHOUSE_TABLE,
                        id="1",
                        project_id=1,
                        parent=Parent(type=ResourceType.WAREHOUSE_OBJECTS, id="1"),
                    )
                },
                ValueError,
            ),
            ("context", {"context": Context(channel="mcp")}, NotImplementedError),
            ("api_key_subject", {"subject": Subject(api_key_id="key")}, NotImplementedError),
        ]
    )
    def test_unsupported_check_raises(self, _name: str, overrides: dict[str, Any], error: type[Exception]) -> None:
        kwargs: dict[str, Any] = {
            "resource": resource_for_object(self.dashboard),
            "action": Action.VIEW,
            "subject": Subject(user_id=self.user.id),
            **overrides,
        }

        with pytest.raises(error):
            authorization.check(**kwargs)
