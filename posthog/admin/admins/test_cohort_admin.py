from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory
from django.utils import timezone

from dateutil.relativedelta import relativedelta

from posthog.admin.admins.cohort_admin import CohortAdmin
from posthog.models import Cohort, User


class TestCohortAdminActions(BaseTest):
    def setUp(self):
        super().setUp()
        self.site = AdminSite()
        self.admin = CohortAdmin(Cohort, self.site)
        self.factory = RequestFactory()
        self.user = User.objects.create_user("admin", "admin@example.com", "password")
        self.user.is_staff = True
        self.user.save()

    def _get_request(self, path="/admin/"):
        """Helper to create a request with proper user"""
        request = self.factory.get(path)
        request.user = self.user
        # Mock messages framework with a simple list
        request._messages = []
        return request

    @patch("posthog.admin.admins.cohort_admin.increment_version_and_enqueue_calculate_cohort")
    def test_recalculate_cohorts_success(self, mock_enqueue):
        """Test successful recalculation of cohorts"""
        cohort1 = Cohort.objects.create(
            team=self.team,
            name="Test Cohort 1",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [{"type": "person", "key": "email", "operator": "exact", "value": "test1@example.com"}],
                }
            },
        )
        cohort2 = Cohort.objects.create(
            team=self.team,
            name="Test Cohort 2",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [{"type": "person", "key": "email", "operator": "exact", "value": "test2@example.com"}],
                }
            },
        )

        queryset = Cohort.objects.filter(id__in=[cohort1.id, cohort2.id])
        request = self._get_request()

        self.admin.recalculate_cohorts(request, queryset)

        # Check that both cohorts were enqueued
        self.assertEqual(mock_enqueue.call_count, 2)
        mock_enqueue.assert_any_call(cohort1, initiating_user=self.user)
        mock_enqueue.assert_any_call(cohort2, initiating_user=self.user)

    def test_recalculate_cohorts_skips_static(self):
        """Test that static cohorts are skipped"""
        static_cohort = Cohort.objects.create(
            team=self.team,
            name="Static Cohort",
            is_static=True,
        )

        queryset = Cohort.objects.filter(id=static_cohort.id)
        request = self._get_request()

        with patch("posthog.admin.admins.cohort_admin.increment_version_and_enqueue_calculate_cohort") as mock_enqueue:
            self.admin.recalculate_cohorts(request, queryset)
            mock_enqueue.assert_not_called()

    def test_recalculate_cohorts_skips_deleted(self):
        """Test that deleted cohorts are skipped"""
        deleted_cohort = Cohort.objects.create(
            team=self.team,
            name="Deleted Cohort",
            deleted=True,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [{"type": "person", "key": "email", "operator": "exact", "value": "test@example.com"}],
                }
            },
        )

        queryset = Cohort.objects.filter(id=deleted_cohort.id)
        request = self._get_request()

        with patch("posthog.admin.admins.cohort_admin.increment_version_and_enqueue_calculate_cohort") as mock_enqueue:
            self.admin.recalculate_cohorts(request, queryset)
            mock_enqueue.assert_not_called()

    def test_recalculate_cohorts_skips_calculating(self):
        """Test that cohorts already calculating are skipped"""
        calculating_cohort = Cohort.objects.create(
            team=self.team,
            name="Calculating Cohort",
            is_calculating=True,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [{"type": "person", "key": "email", "operator": "exact", "value": "test@example.com"}],
                }
            },
        )

        queryset = Cohort.objects.filter(id=calculating_cohort.id)
        request = self._get_request()

        with patch("posthog.admin.admins.cohort_admin.increment_version_and_enqueue_calculate_cohort") as mock_enqueue:
            self.admin.recalculate_cohorts(request, queryset)
            mock_enqueue.assert_not_called()

    @patch("posthog.admin.admins.cohort_admin.increment_version_and_enqueue_calculate_cohort")
    def test_recalculate_cohorts_handles_failures(self, mock_enqueue):
        """Test error handling when recalculation fails"""
        cohort = Cohort.objects.create(
            team=self.team,
            name="Test Cohort",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [{"type": "person", "key": "email", "operator": "exact", "value": "test@example.com"}],
                }
            },
        )

        mock_enqueue.side_effect = Exception("Enqueue failed")

        queryset = Cohort.objects.filter(id=cohort.id)
        request = self._get_request()

        # This should not raise an exception, just handle the error gracefully
        self.admin.recalculate_cohorts(request, queryset)

    def test_reset_stuck_cohorts_resets_stuck_cohorts(self):
        """Test that stuck cohorts are reset"""
        # Create a cohort that's been calculating for more than 1 hour
        old_time = timezone.now() - relativedelta(hours=2)
        stuck_cohort = Cohort.objects.create(
            team=self.team,
            name="Stuck Cohort",
            is_calculating=True,
            last_calculation=old_time,
        )

        queryset = Cohort.objects.filter(id=stuck_cohort.id)
        request = self._get_request()

        self.admin.reset_stuck_cohorts(request, queryset)

        # Check that cohort is no longer calculating
        stuck_cohort.refresh_from_db()
        self.assertFalse(stuck_cohort.is_calculating)
        self.assertIsNotNone(stuck_cohort.last_error_at)

    def test_reset_stuck_cohorts_skips_recent(self):
        """Test that recently calculating cohorts are not reset"""
        # Create a cohort that started calculating recently
        recent_time = timezone.now() - relativedelta(minutes=30)
        recent_cohort = Cohort.objects.create(
            team=self.team,
            name="Recent Cohort",
            is_calculating=True,
            last_calculation=recent_time,
        )

        queryset = Cohort.objects.filter(id=recent_cohort.id)
        request = self._get_request()

        self.admin.reset_stuck_cohorts(request, queryset)

        # Check that cohort is still calculating
        recent_cohort.refresh_from_db()
        self.assertTrue(recent_cohort.is_calculating)

    def test_reset_stuck_cohorts_skips_non_calculating(self):
        """Test that non-calculating cohorts are not affected"""
        not_calculating_cohort = Cohort.objects.create(
            team=self.team,
            name="Not Calculating Cohort",
            is_calculating=False,
            last_calculation=timezone.now() - relativedelta(hours=2),
        )

        queryset = Cohort.objects.filter(id=not_calculating_cohort.id)
        request = self._get_request()

        original_errors = not_calculating_cohort.errors_calculating
        self.admin.reset_stuck_cohorts(request, queryset)

        # Check that cohort was not modified
        not_calculating_cohort.refresh_from_db()
        self.assertFalse(not_calculating_cohort.is_calculating)
        self.assertEqual(not_calculating_cohort.errors_calculating, original_errors)
