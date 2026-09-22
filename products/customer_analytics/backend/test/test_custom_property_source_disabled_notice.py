from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.access_control.backend.models.access_control import AccessControl
from products.customer_analytics.backend.facade import contracts
from products.customer_analytics.backend.logic.custom_property_source_disabled_notice import (
    CONFIGURATION_ACCOUNTS_PATH,
    notify_source_auto_disabled,
)
from products.customer_analytics.backend.logic.customer_task_digest import build_customer_task_digest
from products.customer_analytics.backend.logic.customer_tasks import list_customer_tasks
from products.customer_analytics.backend.logic.task_digest_delivery import task_digest_enabled
from products.customer_analytics.backend.models import (
    CustomerTask,
    CustomerTaskActivity,
    CustomPropertySource,
    UserCustomerAnalyticsConfig,
)
from products.customer_analytics.backend.models.customer_task import CustomerTaskStatus
from products.customer_analytics.backend.test.factories import create_custom_property_definition
from products.notifications.backend.facade.enums import NotificationType, Priority, TargetType

SERVICE = "products.customer_analytics.backend.logic.custom_property_source_disabled_notice"


@time_machine.travel("2026-09-18T18:00:00Z", tick=False)
@patch(f"{SERVICE}.posthog_feature_flag_enabled", return_value=True)
@patch(f"{SERVICE}.create_notification")
class TestNotifySourceAutoDisabled(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.team.timezone = "America/Los_Angeles"
        self.team.save(update_fields=["timezone"])
        definition = create_custom_property_definition(team_id=self.team.id, name="Plan tier")
        self.source = CustomPropertySource.objects.for_team(self.team.id).create(
            team=self.team,
            definition=definition,
            created_by=self.user,
            key_column="external_id",
            source_column="plan",
            is_enabled=False,
        )

    def _notify(self, disable_event_id: str = "job-1") -> None:
        notify_source_auto_disabled(team_id=self.team.id, source_id=self.source.id, disable_event_id=disable_event_id)

    def test_the_owner_gets_one_notification_pointing_at_configuration(self, mock_create, _mock_flag) -> None:
        self._notify()

        data = mock_create.call_args.args[0]
        assert data.notification_type == NotificationType.PIPELINE_FAILURE
        assert data.priority == Priority.NORMAL
        assert data.target_type == TargetType.USER
        assert data.target_id == str(self.user.id)
        assert data.title == "Warehouse property sync disabled: Plan tier"
        assert data.source_url == CONFIGURATION_ACCOUNTS_PATH
        assert data.source_id == str(self.source.id)
        assert data.idempotency_key.startswith(f"custom-property-source:{self.source.id}:disabled:")
        assert len(data.idempotency_key) <= 128

    def test_the_notification_body_keeps_the_raw_warehouse_error_out(self, mock_create, _mock_flag) -> None:
        self.source.last_sync_error = "could not connect to warehouse-host-42: relation users missing"
        self.source.save()

        self._notify()

        assert "warehouse-host-42" not in mock_create.call_args.args[0].body

    def test_one_open_task_is_visible_to_the_owner_and_digest(self, _mock_create, _mock_flag) -> None:
        config = UserCustomerAnalyticsConfig.objects.for_team(self.team.id).create(
            team=self.team,
            user=self.user,
            properties={"task_digest": {"enabled": True, "send_time": "09:00", "cadence": "weekdays"}},
        )

        self._notify()

        task = CustomerTask.objects.for_team(self.team.id).get()
        assert task.name == "Fix warehouse property sync: Plan tier"
        assert task.assigned_to_id == self.user.id
        assert task.account_id is None
        assert task.status == CustomerTaskStatus.OPEN
        assert task.created_by_id is None
        assert task.due_at is not None
        local_due_at = task.due_at.astimezone(ZoneInfo(self.team.timezone))
        assert local_due_at.date().isoformat() == "2026-09-21"
        assert local_due_at.time() == time(23, 59, 59)

        access = UserAccessControl(user=self.user, team=self.team)
        tasks, count = list_customer_tasks(
            team_id=self.team.id,
            user_access_control=access,
            filters=contracts.CustomerTaskListFilters(assigned_to="me"),
            offset=0,
            limit=10,
        )
        assert count == 1
        assert [item.id for item in tasks] == [task.id]
        with patch(
            "products.customer_analytics.backend.logic.task_digest_delivery.posthoganalytics.feature_enabled",
            return_value=True,
        ):
            assert task_digest_enabled(config)
        digest = build_customer_task_digest(
            user=self.user,
            team=self.team,
            reference_time=datetime(2026, 9, 21, 12, tzinfo=UTC),
        )
        assert digest is not None
        assert [item.name for item in digest.due_today] == [task.name]

    def test_a_repeated_delivery_creates_one_task_activity_and_access_grant(self, _mock_create, _mock_flag) -> None:
        self._notify()
        self._notify()

        task = CustomerTask.objects.for_team(self.team.id).get()
        assert CustomerTaskActivity.objects.for_team(self.team.id).filter(task=task).count() == 1
        assert (
            AccessControl.objects.filter(
                team=self.team,
                resource="customer_task",
                resource_id=str(task.id),
                access_level="editor",
            ).count()
            == 1
        )

    def test_a_later_disablement_creates_a_second_task(self, _mock_create, _mock_flag) -> None:
        self._notify(disable_event_id="job-1")
        self._notify(disable_event_id="job-2")

        assert CustomerTask.objects.for_team(self.team.id).count() == 2

    def test_long_job_ids_fit_notification_idempotency_limits(self, mock_create, _mock_flag) -> None:
        self._notify(disable_event_id="j" * 400)

        data = mock_create.call_args.args[0]
        assert len(data.idempotency_key) <= 128
        assert len(data.source_id) <= 64

    def test_an_inactive_owner_is_skipped_without_notifying_the_project(self, mock_create, _mock_flag) -> None:
        self.user.is_active = False
        self.user.save()

        self._notify()

        mock_create.assert_not_called()
        assert not CustomerTask.objects.for_team(self.team.id).exists()

    def test_a_source_with_no_owner_is_skipped(self, mock_create, _mock_flag) -> None:
        self.source.created_by = None
        self.source.save()

        self._notify()

        mock_create.assert_not_called()
        assert not CustomerTask.objects.for_team(self.team.id).exists()

    def test_an_owner_without_project_membership_is_skipped(self, mock_create, _mock_flag) -> None:
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).delete()

        self._notify()

        mock_create.assert_not_called()
        assert not CustomerTask.objects.for_team(self.team.id).exists()

    def test_the_notification_still_goes_out_when_tasks_are_flag_disabled(self, mock_create, mock_flag) -> None:
        mock_flag.return_value = False

        self._notify()

        mock_create.assert_called_once()
        assert not CustomerTask.objects.for_team(self.team.id).exists()

    def test_the_notification_still_goes_out_when_task_access_is_disabled(self, mock_create, _mock_flag) -> None:
        self.organization.available_product_features = [
            {"name": AvailableFeature.ACCESS_CONTROL, "key": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="customer_analytics",
            resource_id=None,
            organization_member=membership,
            access_level="none",
        )

        self._notify()

        mock_create.assert_called_once()
        assert not CustomerTask.objects.for_team(self.team.id).exists()

    def test_a_failed_notification_does_not_stop_the_task(self, mock_create, _mock_flag) -> None:
        mock_create.side_effect = RuntimeError("transport down")

        self._notify()

        assert CustomerTask.objects.for_team(self.team.id).count() == 1

    def test_a_failed_task_does_not_stop_the_notification(self, mock_create, _mock_flag) -> None:
        with patch(f"{SERVICE}.create_customer_task", side_effect=RuntimeError("task unavailable")):
            self._notify()

        mock_create.assert_called_once()
        assert not CustomerTask.objects.for_team(self.team.id).exists()
