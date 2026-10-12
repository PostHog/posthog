import os
from uuid import UUID

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import transaction
from django.test import override_settings

from openfga_sdk import CreateStoreRequest

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, Team, User

from products.access_control.backend.facade import testing as access_control_testing
from products.access_control.backend.facade.api import set_object_access_control
from products.access_control.backend.facade.contracts import SetObjectAccessControlInput
from products.authz.backend.bootstrap import bootstrap_openfga
from products.authz.backend.client import get_openfga_client
from products.authz.backend.facade import api
from products.authz.backend.facade.contracts import CheckRequest, Resource, Subject
from products.authz.backend.facade.enums import Action, ResourceType
from products.dashboards.backend.facade import testing as dashboard_testing


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
