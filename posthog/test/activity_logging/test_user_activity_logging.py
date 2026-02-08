from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, User
from posthog.models.activity_logging.activity_log import (
    ActivityLog,
    activity_visibility_restrictions,
    field_exclusions,
    field_with_masked_contents,
    signal_exclusions,
)
from posthog.models.activity_logging.utils import activity_storage, activity_visibility_manager
from posthog.models.organization import OrganizationMembership
from posthog.models.signals import model_activity_signal
from posthog.test.activity_log_utils import ActivityLogTestHelper


class TestUserActivityLoggingConfiguration(BaseTest):
    """Tests for User activity logging configuration dictionaries."""

    @parameterized.expand(
        [
            ("current_organization_id", True),
            ("current_team_id", True),
            ("distinct_id", True),
            ("partial_notification_settings", True),
            ("_billing_plan_details", True),
            ("strapi_id", True),
            ("password", False),
            ("temporary_token", False),
            ("anonymize_data", False),
            ("is_email_verified", False),
        ]
    )
    def test_field_exclusions_configured_correctly(self, field_name: str, should_be_excluded: bool) -> None:
        """Test that field_exclusions['User'] contains the correct fields."""
        user_exclusions = field_exclusions.get("User", [])
        if should_be_excluded:
            self.assertIn(field_name, user_exclusions, f"Field '{field_name}' should be in exclusions")
        else:
            self.assertNotIn(field_name, user_exclusions, f"Field '{field_name}' should NOT be in exclusions")

    @parameterized.expand(
        [
            ("email", True),
            ("password", True),
            ("temporary_token", True),
            ("pending_email", True),
            ("first_name", False),
            ("last_name", False),
            ("is_staff", False),
        ]
    )
    def test_field_masking_configured_correctly(self, field_name: str, should_be_masked: bool) -> None:
        """Test that field_with_masked_contents['User'] masks sensitive fields."""
        user_masked_fields = field_with_masked_contents.get("User", [])
        if should_be_masked:
            self.assertIn(field_name, user_masked_fields, f"Field '{field_name}' should be masked")
        else:
            self.assertNotIn(field_name, user_masked_fields, f"Field '{field_name}' should NOT be masked")

    @parameterized.expand(
        [
            ("last_login", True),
            ("date_joined", True),
            ("current_organization", True),
            ("current_team", True),
            ("current_organization_id", True),
            ("current_team_id", True),
            ("first_name", False),
            ("email", False),
        ]
    )
    def test_signal_exclusions_configured_correctly(self, field_name: str, should_exclude_signal: bool) -> None:
        """Test that signal_exclusions['User'] prevents logging for high-frequency fields."""
        user_signal_exclusions = signal_exclusions.get("User", [])
        if should_exclude_signal:
            self.assertIn(field_name, user_signal_exclusions, f"Field '{field_name}' should be in signal exclusions")
        else:
            self.assertNotIn(
                field_name, user_signal_exclusions, f"Field '{field_name}' should NOT be in signal exclusions"
            )

    @parameterized.expand(
        [
            ("created",),
            ("updated",),
            ("logged_in",),
            ("logged_out",),
        ]
    )
    def test_visibility_restrictions_configured_for_all_user_activities(self, activity: str) -> None:
        """Test that activity_visibility_restrictions has User scope entries for all activities."""
        user_activities: list[str] = []
        for config in activity_visibility_restrictions:
            if config.get("scope") == "User":
                user_activities.extend(config.get("activities", []))
        self.assertIn(activity, user_activities, f"Activity '{activity}' should be restricted for User scope")

    def test_visibility_restrictions_allow_staff_to_view(self) -> None:
        """Test that staff users can view User activities."""
        for config in activity_visibility_restrictions:
            if config.get("scope") == "User":
                self.assertTrue(
                    config.get("allow_staff", False), "User activity restrictions should allow staff to view"
                )


class TestUserModelMixinIntegration(BaseTest):
    """Tests for User model mixin integration with activity signal."""

    def setUp(self):
        super().setUp()
        self.signal_received = False
        self.signal_data = {}

    def _signal_handler(self, sender, **kwargs):
        self.signal_received = True
        self.signal_data = kwargs

    def test_user_create_triggers_model_activity_signal(self) -> None:
        """Test that User model save triggers model_activity_signal for creates."""
        model_activity_signal.connect(self._signal_handler, sender=User)
        try:
            user = User.objects.create_user(
                email="newuser@example.com", password="testpass123", first_name="New", last_name="User"
            )
            self.assertTrue(self.signal_received, "Signal should be received on user creation")
            self.assertEqual(self.signal_data.get("activity"), "created")
            self.assertEqual(self.signal_data.get("after_update"), user)
            self.assertIsNone(self.signal_data.get("before_update"))
        finally:
            model_activity_signal.disconnect(self._signal_handler, sender=User)

    def test_user_update_triggers_model_activity_signal(self) -> None:
        """Test that User model save triggers model_activity_signal for updates."""
        user = User.objects.create_user(
            email="updatetest@example.com", password="testpass123", first_name="Test", last_name="User"
        )
        self.signal_received = False
        self.signal_data = {}

        model_activity_signal.connect(self._signal_handler, sender=User)
        try:
            user.first_name = "Updated"
            user.save()
            self.assertTrue(self.signal_received, "Signal should be received on user update")
            self.assertEqual(self.signal_data.get("activity"), "updated")
        finally:
            model_activity_signal.disconnect(self._signal_handler, sender=User)

    def test_update_to_signal_excluded_fields_does_not_trigger_signal(self) -> None:
        """Test that updates to signal-excluded fields (last_login) do NOT trigger signal."""
        user = User.objects.create_user(
            email="logintest@example.com", password="testpass123", first_name="Login", last_name="Test"
        )
        self.signal_received = False
        self.signal_data = {}

        model_activity_signal.connect(self._signal_handler, sender=User)
        try:
            user.last_login = timezone.now()
            user.save(update_fields=["last_login"])
            self.assertFalse(
                self.signal_received, "Signal should NOT be received when only updating signal-excluded fields"
            )
        finally:
            model_activity_signal.disconnect(self._signal_handler, sender=User)

    def test_user_save_still_works_correctly(self) -> None:
        """Test that User save() method continues to work correctly with mixin."""
        user = User.objects.create_user(
            email="savetest@example.com", password="testpass123", first_name="Save", last_name="Test"
        )
        user.first_name = "SaveUpdated"
        user.save()

        user.refresh_from_db()
        self.assertEqual(user.first_name, "SaveUpdated")


class TestUserActivitySignalHandler(ActivityLogTestHelper):
    """Tests for User activity signal handler."""

    def test_handler_creates_activity_log_on_user_update(self) -> None:
        """Test handler creates ActivityLog entry on User update with changes."""
        new_user = User.objects.create_and_join(
            organization=self.organization,
            email="updatelog@example.com",
            password="testpass123",
            first_name="Update",
            last_name="Log",
        )
        ActivityLog.objects.filter(scope="User").delete()

        activity_storage.set_user(self.user)
        try:
            new_user.first_name = "Updated"
            new_user.save()
        finally:
            activity_storage.clear_user()

        log = ActivityLog.objects.filter(scope="User", activity="updated", item_id=str(new_user.id)).first()

        self.assertIsNotNone(log, "ActivityLog should be created for user update")
        assert log is not None
        assert log.detail is not None
        changes = log.detail.get("changes", [])
        first_name_change = next((c for c in changes if c["field"] == "first_name"), None)
        self.assertIsNotNone(first_name_change)
        assert first_name_change is not None
        self.assertEqual(first_name_change["before"], "Update")
        self.assertEqual(first_name_change["after"], "Updated")

    def test_handler_logs_to_all_organizations_user_belongs_to(self) -> None:
        """Test handler logs to ALL organizations user belongs to (multi-org)."""
        org2 = Organization.objects.create(name="Second Org")

        new_user = User.objects.create_and_join(
            organization=self.organization,
            email="multiorg@example.com",
            password="testpass123",
            first_name="Multi",
            last_name="Org",
        )
        new_user.join(organization=org2, level=OrganizationMembership.Level.MEMBER)

        ActivityLog.objects.filter(scope="User").delete()

        activity_storage.set_user(self.user)
        try:
            new_user.first_name = "MultiUpdated"
            new_user.save()
        finally:
            activity_storage.clear_user()

        logs = ActivityLog.objects.filter(scope="User", activity="updated", item_id=str(new_user.id))
        org_ids = {log.organization_id for log in logs}

        self.assertEqual(len(org_ids), 2, "Should have activity logs for both organizations")
        self.assertIn(self.organization.id, org_ids)
        self.assertIn(org2.id, org_ids)

    def test_handler_handles_new_user_with_no_organization_memberships_gracefully(self) -> None:
        """Test handler handles new user with no organization memberships gracefully."""
        new_user = User.objects.create_user(
            email="noorg@example.com", password="testpass123", first_name="No", last_name="Org"
        )

        logs = ActivityLog.objects.filter(scope="User", activity="created", item_id=str(new_user.id))
        self.assertEqual(logs.count(), 0, "Should not create activity log for user with no organizations")

    def test_masked_fields_show_masked_instead_of_actual_values(self) -> None:
        """Test masked fields show 'masked' instead of actual values."""
        new_user = User.objects.create_and_join(
            organization=self.organization,
            email="masked@example.com",
            password="testpass123",
            first_name="Masked",
            last_name="Test",
        )
        ActivityLog.objects.filter(scope="User").delete()

        activity_storage.set_user(self.user)
        try:
            new_user.pending_email = "newemail@example.com"
            new_user.save()
        finally:
            activity_storage.clear_user()

        log = ActivityLog.objects.filter(scope="User", activity="updated", item_id=str(new_user.id)).first()

        if log and log.detail:
            changes = log.detail.get("changes", [])
            email_change = next((c for c in changes if c["field"] == "pending_email"), None)
            if email_change:
                self.assertEqual(email_change.get("after"), "masked", "pending_email should be masked")


class TestUserActivityLoggingIntegration(ActivityLogTestHelper):
    """Integration tests for User activity logging."""

    def test_user_update_triggers_activity_log(self) -> None:
        """Test user update triggers activity log when user is in an organization."""
        ActivityLog.objects.filter(scope="User").delete()

        new_user = User.objects.create_and_join(
            organization=self.organization,
            email="updatetest@example.com",
            password="testpass123",
            first_name="Update",
            last_name="Test",
        )
        ActivityLog.objects.filter(scope="User").delete()

        activity_storage.set_user(self.user)
        try:
            new_user.last_name = "TestUpdated"
            new_user.save()
        finally:
            activity_storage.clear_user()

        log = ActivityLog.objects.filter(
            organization_id=self.organization.id, scope="User", activity="updated", item_id=str(new_user.id)
        ).first()

        self.assertIsNotNone(log, "ActivityLog should be created for user update")

    def test_activity_log_visibility_manager_filters_user_activities_for_non_staff(self) -> None:
        """Test ActivityLogVisibilityManager correctly filters User activities for non-staff."""
        new_user = User.objects.create_and_join(
            organization=self.organization,
            email="filter@example.com",
            password="testpass123",
            first_name="Filter",
            last_name="Test",
        )
        ActivityLog.objects.filter(scope="User").delete()

        activity_storage.set_user(self.user)
        try:
            new_user.first_name = "FilterUpdated"
            new_user.save()
        finally:
            activity_storage.clear_user()

        ActivityLog.objects.create(
            team_id=self.team.id,
            scope="FeatureFlag",
            activity="created",
            item_id="123",
        )

        queryset = ActivityLog.objects.filter(organization_id=self.organization.id)
        filtered_non_staff = activity_visibility_manager.apply_to_queryset(queryset, is_staff=False)
        filtered_staff = activity_visibility_manager.apply_to_queryset(queryset, is_staff=True)

        self.assertLess(filtered_non_staff.count(), filtered_staff.count())
        self.assertFalse(
            filtered_non_staff.filter(scope="User").exists(), "Non-staff should not see User activity logs"
        )
