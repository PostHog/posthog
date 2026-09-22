from posthog.test.base import BaseTest
from unittest.mock import patch

from products.customer_analytics.backend.logic.custom_property_source_disabled_notice import (
    CONFIGURATION_ACCOUNTS_PATH,
    notify_source_auto_disabled,
)
from products.customer_analytics.backend.models import CustomerTask, CustomPropertySource
from products.customer_analytics.backend.models.customer_task import CustomerTaskStatus
from products.customer_analytics.backend.test.factories import create_custom_property_definition
from products.notifications.backend.facade.enums import NotificationType, Priority, TargetType

SERVICE = "products.customer_analytics.backend.logic.custom_property_source_disabled_notice"


@patch(f"{SERVICE}.posthog_feature_flag_enabled", return_value=True)
@patch(f"{SERVICE}.create_notification")
class TestNotifySourceAutoDisabled(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        definition = create_custom_property_definition(team_id=self.team.id, name="Plan tier")
        self.source = CustomPropertySource.objects.create(
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
        assert data.idempotency_key == f"custom-property-source-disabled-{self.source.id}-job-1"

    def test_the_notification_body_keeps_the_raw_warehouse_error_out(self, mock_create, _mock_flag) -> None:
        # The error can carry a host name or a fragment of a customer row, and the owner reads the
        # real one on the run itself.
        self.source.last_sync_error = "could not connect to warehouse-host-42: relation users missing"
        self.source.save()

        self._notify()

        assert "warehouse-host-42" not in mock_create.call_args.args[0].body

    def test_one_open_task_is_assigned_to_the_owner(self, _mock_create, _mock_flag) -> None:
        self._notify()

        task = CustomerTask.objects.for_team(self.team.id).get()
        assert task.name == "Fix warehouse property sync: Plan tier"
        assert task.assigned_to_id == self.user.id
        assert task.account_id is None
        assert task.status == CustomerTaskStatus.OPEN
        assert task.due_at is not None
        # PostHog disabled the sync, so the action belongs to nobody.
        assert task.created_by_id is None

    def test_a_repeated_delivery_for_the_same_disablement_creates_one_task(self, _mock_create, _mock_flag) -> None:
        # The recorder can run twice for one disablement — an activity retry, or two workers racing.
        self._notify()
        self._notify()

        assert CustomerTask.objects.for_team(self.team.id).count() == 1

    def test_a_later_disablement_creates_a_second_task(self, _mock_create, _mock_flag) -> None:
        self._notify(disable_event_id="job-1")
        self._notify(disable_event_id="job-2")

        assert CustomerTask.objects.for_team(self.team.id).count() == 2

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

    def test_the_notification_still_goes_out_when_tasks_are_unavailable(self, mock_create, mock_flag) -> None:
        mock_flag.return_value = False

        self._notify()

        mock_create.assert_called_once()
        assert not CustomerTask.objects.for_team(self.team.id).exists()

    def test_a_failed_notification_does_not_stop_the_task(self, mock_create, _mock_flag) -> None:
        # Each branch is guarded on its own, so one broken transport cannot take the other down.
        mock_create.side_effect = RuntimeError("transport down")

        self._notify()

        assert CustomerTask.objects.for_team(self.team.id).count() == 1
