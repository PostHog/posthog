from collections.abc import Callable
from datetime import timedelta
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import connection
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.scoping import team_scope

from products.access_control.backend.models.access_control import AccessControl
from products.alerts.backend.facade.api import take_alert_ownership
from products.alerts.backend.facade.contracts import AlertWriteRefused
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.platform_cutover import cut_over_team
from products.alerts.backend.platform_insight_alert import native_insight_alert_view
from products.alerts.backend.test.insight_alerts import create_insight_alert
from products.alerts_platform.backend.facade import testing as platform_testing
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery


class TestAlertTakeOwnership(APIBaseTest):
    def _disabled_alert_of_a_former_member(self) -> AlertConfiguration:
        former_member = User.objects.create_user(email="former-member@example.com", first_name="", password=None)
        return create_insight_alert(self.team, created_by=former_member, enabled=False)

    def test_enabling_is_rejected_when_the_owner_left(self) -> None:
        alert = self._disabled_alert_of_a_former_member()

        response = self.client.patch(f"/api/projects/{self.team.id}/alerts/{alert.id}", {"enabled": True})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert response.json()["attr"] == "enabled"
        # The frontend keys its "take ownership" offer, and the cause it shows, on this code.
        assert response.json()["code"] == "owner_left_organization"
        assert (
            "its creator, former-member@example.com, who is no longer in the organization" in response.json()["detail"]
        )

    @parameterized.expand(
        [
            (True, OrganizationMembership.Level.MEMBER, False),
            (False, OrganizationMembership.Level.MEMBER),
            (True, OrganizationMembership.Level.MEMBER),
            (True, OrganizationMembership.Level.ADMIN),
        ]
    )
    def test_take_ownership_permissions(
        self, another_member: bool, requester_level: int, member_exists: bool = True
    ) -> None:
        alert = self._disabled_alert_of_a_former_member()
        previous_owner = alert.created_by
        owner = self.user
        if another_member:
            owner = User.objects.create_user(email="new-owner@example.com", first_name="New owner", password=None)
            if member_exists:
                OrganizationMembership.objects.create(organization=self.organization, user=owner)
        self.organization_membership.level = requester_level
        self.organization_membership.save()

        response = self.client.post(
            f"/api/projects/{self.team.id}/alerts/{alert.id}/take_ownership/",
            {"user_uuid": str(owner.uuid)} if another_member else {},
        )

        alert.refresh_from_db()
        if another_member and requester_level == OrganizationMembership.Level.MEMBER:
            assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
            assert "organization admin" in response.json()["detail"]
            assert alert.created_by == previous_owner
            assert alert.enabled is False
            assert not ActivityLog.objects.filter(
                scope="AlertConfiguration",
                item_id=str(alert.id),
                activity__in=["took_ownership", "transferred_ownership"],
            ).exists()
            return
        assert response.status_code == status.HTTP_200_OK, response.content
        assert alert.created_by == owner
        assert alert.enabled is True
        # created_by is excluded from the save diff, so the takeover logs its own activity.
        takeover = ActivityLog.objects.get(
            scope="AlertConfiguration",
            item_id=str(alert.id),
            activity="transferred_ownership" if another_member else "took_ownership",
        )
        assert takeover.detail is not None
        assert [change["field"] for change in takeover.detail["changes"]] == ["created_by"]
        assert takeover.user == self.user

    @parameterized.expand(["non_member", "inactive", "no_project_access"])
    def test_transfer_ownership_rejects_ineligible_owner(self, reason: str) -> None:
        alert = self._disabled_alert_of_a_former_member()
        previous_owner = alert.created_by
        owner = User.objects.create_user(
            email="new-owner@example.com", first_name="New owner", password=None, is_active=reason != "inactive"
        )
        if reason != "non_member":
            OrganizationMembership.objects.create(organization=self.organization, user=owner)
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        if reason == "no_project_access":
            self.organization.available_product_features = [
                {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
            ]
            self.organization.save()
            AccessControl.objects.create(
                team=self.team, resource="project", resource_id=str(self.team.id), access_level="none"
            )

        response = self.client.post(
            f"/api/projects/{self.team.id}/alerts/{alert.id}/take_ownership/",
            {"user_uuid": str(owner.uuid)},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        alert.refresh_from_db()
        assert alert.created_by == previous_owner
        assert alert.enabled is False

    def test_take_ownership_is_not_blocked_by_the_alert_limit(self) -> None:
        alert = self._disabled_alert_of_a_former_member()

        with patch.object(AlertConfiguration, "check_alert_limit", return_value="Your team has reached the limit."):
            response = self.client.post(f"/api/projects/{self.team.id}/alerts/{alert.id}/take_ownership/")

        assert response.status_code == status.HTTP_200_OK, response.content

    @parameterized.expand(
        [
            (storage, enabled, denied_user)
            for storage in ("insight", "platform")
            for enabled in (False, True)
            for denied_user in ("owner", None)
        ]
        + [(storage, False, "self") for storage in ("insight", "platform")]
    )
    def test_transfer_checks_the_owners_table_access(
        self, storage: str, enabled: bool, denied_user: str | None
    ) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        self.organization_membership.level = (
            OrganizationMembership.Level.MEMBER if denied_user == "self" else OrganizationMembership.Level.ADMIN
        )
        self.organization_membership.save()
        owner = User.objects.create_user(email="new-owner@example.com", first_name="New owner", password=None)
        owner_membership = OrganizationMembership.objects.create(organization=self.organization, user=owner)
        if denied_user == "self":
            owner, owner_membership = self.user, self.organization_membership
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="governed_view",
            query={"kind": "HogQLQuery", "query": "SELECT 1 AS value"},
            columns={"value": "Integer"},
        )
        alert = create_insight_alert(
            self.team,
            created_by=self.user,
            enabled=enabled,
            next_check_at=timezone.now() + timedelta(minutes=5),
            config={"type": "HogQLAlertConfig", "evaluation": "last_row"},
        )
        alert.insight.query = {"kind": "HogQLQuery", "query": "SELECT value FROM governed_view"}
        alert.insight.save()
        alert_id = alert.id
        if storage == "platform":
            [cutover] = cut_over_team(self.team.id)
            assert cutover.skipped is None
            with team_scope(self.team.id):
                alert_id = platform_testing.copy_of(alert.id).id
                platform_testing.forget_source_row(alert_id)
            AlertConfiguration.objects.filter(id=alert.id).delete()
        if denied_user:
            AccessControl.objects.create(
                team=self.team,
                resource="warehouse_objects",
                organization_member=owner_membership,
                access_level="none",
            )

        with patch("posthog.hogql.database.database._evaluate_warehouse_access_control_flag", return_value=True):
            response = self.client.post(
                f"/api/projects/{self.team.id}/alerts/{alert_id}/take_ownership/", {"user_uuid": str(owner.uuid)}
            )

        if storage == "platform":
            view = native_insight_alert_view(self.team.id, alert_id)
            assert view is not None
            native_alert = AlertConfiguration.from_platform_view(view, team_id=self.team.id)
            assert native_alert is not None
            alert = native_alert
        else:
            alert.refresh_from_db()
        if denied_user:
            assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
            assert "governed_view" in response.json()["detail"]
            if denied_user == "self":
                assert "to take ownership of this alert" in response.json()["detail"]
            assert alert.created_by == self.user
            assert alert.enabled is enabled
            assert not ActivityLog.objects.filter(
                scope="AlertConfiguration",
                item_id=str(alert_id),
                activity__in=["took_ownership", "transferred_ownership"],
            ).exists()
        else:
            assert response.status_code == status.HTTP_200_OK, response.content
            assert alert.created_by == owner
            assert alert.enabled is True
            assert (
                ActivityLog.objects.get(
                    scope="AlertConfiguration", item_id=str(alert_id), activity="transferred_ownership"
                ).user
                == self.user
            )

    def test_take_ownership_refuses_when_query_access_check_fails(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        alert = self._disabled_alert_of_a_former_member()
        previous_owner = alert.created_by

        failed = False

        def fail_query(execute: Callable, sql: str, params: Any, many: bool, context: dict) -> Any:
            nonlocal failed
            if not failed and "posthog_datawarehousesavedquery" in sql.lower():
                failed = True
                return execute("SELECT 1 / 0", None, False, context)
            return execute(sql, params, many, context)

        alert.insight.query = {"kind": "HogQLQuery", "query": "SELECT value FROM governed_view"}
        alert.insight.save()
        with connection.execute_wrapper(fail_query):
            response = self.client.post(f"/api/projects/{self.team.id}/alerts/{alert.id}/take_ownership/")

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE, response.content
        assert response.json()["code"] == "ownership_access_check_unavailable"
        alert.refresh_from_db()
        assert alert.created_by == previous_owner
        assert alert.enabled is False

    def test_take_ownership_of_an_ai_alert_needs_the_rollout(self) -> None:
        former_member = User.objects.create_user(email="former-member@example.com", first_name="", password=None)
        # Enabled, so the enable path's admission does not run and only the takeover check applies.
        alert = create_insight_alert(self.team, created_by=former_member, enabled=True, detector_config={"type": "llm"})

        with patch("products.alerts.backend.llm_detector_limits.posthoganalytics.feature_enabled", return_value=False):
            response = self.client.post(f"/api/projects/{self.team.id}/alerts/{alert.id}/take_ownership/")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        alert.refresh_from_db()
        assert alert.created_by == former_member

    @parameterized.expand([("admin", None), ("member", 403), ("inactive_owner", 400)])
    def test_backend_ownership_operation_enforces_permissions(self, case: str, expected_status: int | None) -> None:
        alert = self._disabled_alert_of_a_former_member()
        previous_owner = alert.created_by
        owner = User.objects.create_user(
            email="new-owner@example.com", first_name="", password=None, is_active=case != "inactive_owner"
        )
        OrganizationMembership.objects.create(organization=self.organization, user=owner)
        self.organization_membership.level = (
            OrganizationMembership.Level.MEMBER if case == "member" else OrganizationMembership.Level.ADMIN
        )
        self.organization_membership.save()

        try:
            take_alert_ownership(
                team_id=self.team.id, alert_id=alert.id, actor=self.user, owner=owner, was_impersonated=False
            )
        except AlertWriteRefused as error:
            assert error.status_code == expected_status
        else:
            assert expected_status is None

        alert.refresh_from_db()
        assert alert.created_by == (owner if expected_status is None else previous_owner)
        assert alert.enabled is (expected_status is None)
        activities = ActivityLog.objects.filter(
            scope="AlertConfiguration", item_id=str(alert.id), activity="transferred_ownership"
        )
        if expected_status is None:
            assert activities.get().user == self.user
        else:
            assert not activities.exists()

    @parameterized.expand(["alert", "insight"])
    def test_take_ownership_validates_locked_settings(self, changed: str) -> None:
        alert = self._disabled_alert_of_a_former_member()
        previous_owner = alert.created_by
        edited = False

        def edit_before_lock(execute: Callable, sql: str, params: Any, many: bool, context: dict) -> Any:
            nonlocal edited
            if not edited and ("FOR UPDATE" in sql or "FOR NO KEY UPDATE" in sql):
                edited = True
                if changed == "alert":
                    AlertConfiguration.objects.filter(pk=alert.pk).update(
                        config={**(alert.config or {}), "series_index": 999}
                    )
                else:
                    type(alert.insight).objects.filter(pk=alert.insight_id).update(query=None, filters={})
            return execute(sql, params, many, context)

        url = f"/api/projects/{self.team.id}/alerts/{alert.id}/take_ownership/"
        with connection.execute_wrapper(edit_before_lock):
            response = self.client.post(url)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        alert.refresh_from_db()
        assert alert.created_by == previous_owner
        assert alert.enabled is False
        retry = self.client.post(url)
        assert retry.status_code == status.HTTP_200_OK, retry.content
