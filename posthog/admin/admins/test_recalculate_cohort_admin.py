from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test.client import RequestFactory
from django.utils import timezone

from dateutil.relativedelta import relativedelta

from posthog.admin.admins.recalculate_cohort_admin import recalculate_cohort_view
from posthog.models import Cohort

User = get_user_model()


class TestRecalculateCohortAdmin(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        # Make the user a staff member for admin access
        self.user.is_staff = True
        self.user.save()

    def _add_messages_framework_to_request(self, request):
        """Add Django messages framework to request for testing"""
        request.session = "session"
        messages = FallbackStorage(request)
        request._messages = messages

    @patch("posthog.admin.admins.recalculate_cohort_admin.increment_version_and_enqueue_calculate_cohort")
    def test_recalculate_cohort_success(self, mock_enqueue):
        """Test successful cohort recalculation"""
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

        request = self.factory.post(
            "/admin/recalculate-cohort/",
            {"action": "recalculate", "cohort_id": cohort.id, "force": False},
        )
        request.user = self.user
        self._add_messages_framework_to_request(request)

        response = recalculate_cohort_view(request)

        self.assertEqual(response.status_code, 302)  # Redirect after success
        mock_enqueue.assert_called_once_with(cohort, initiating_user=self.user)

    def test_reset_stuck_cohort_success(self):
        """Test successful reset of stuck cohort"""
        # Create a cohort that has been calculating for more than 1 hour
        stuck_time = timezone.now() - relativedelta(hours=2)
        cohort = Cohort.objects.create(
            team=self.team,
            name="Stuck Cohort",
            is_calculating=True,
            last_calculation=stuck_time,
        )

        request = self.factory.post(
            "/admin/recalculate-cohort/",
            {"action": "reset", "cohort_id": cohort.id, "force_reset": False},
        )
        request.user = self.user
        self._add_messages_framework_to_request(request)

        response = recalculate_cohort_view(request)

        self.assertEqual(response.status_code, 302)  # Redirect after success

        # Check that cohort was reset
        cohort.refresh_from_db()
        self.assertFalse(cohort.is_calculating)
        self.assertEqual(cohort.errors_calculating, 1)
        self.assertIsNotNone(cohort.last_error_at)

    def test_reset_recent_cohort_without_force(self):
        """Test that recent cohorts are not reset without force flag"""
        # Create a cohort that started calculating recently
        recent_time = timezone.now() - relativedelta(minutes=30)
        cohort = Cohort.objects.create(
            team=self.team,
            name="Recent Cohort",
            is_calculating=True,
            last_calculation=recent_time,
        )

        request = self.factory.post(
            "/admin/recalculate-cohort/",
            {"action": "reset", "cohort_id": cohort.id, "force_reset": False},
        )
        request.user = self.user
        self._add_messages_framework_to_request(request)

        response = recalculate_cohort_view(request)

        self.assertEqual(response.status_code, 302)  # Redirect

        # Check that cohort was NOT reset
        cohort.refresh_from_db()
        self.assertTrue(cohort.is_calculating)
        self.assertEqual(cohort.errors_calculating, 0)

    def test_reset_recent_cohort_with_force(self):
        """Test that recent cohorts are reset with force flag"""
        # Create a cohort that started calculating recently
        recent_time = timezone.now() - relativedelta(minutes=30)
        cohort = Cohort.objects.create(
            team=self.team,
            name="Recent Cohort",
            is_calculating=True,
            last_calculation=recent_time,
        )

        request = self.factory.post(
            "/admin/recalculate-cohort/",
            {"action": "reset", "cohort_id": cohort.id, "force_reset": True},
        )
        request.user = self.user
        self._add_messages_framework_to_request(request)

        response = recalculate_cohort_view(request)

        self.assertEqual(response.status_code, 302)  # Redirect after success

        # Check that cohort was reset
        cohort.refresh_from_db()
        self.assertFalse(cohort.is_calculating)
        self.assertEqual(cohort.errors_calculating, 1)
        self.assertIsNotNone(cohort.last_error_at)

    def test_reset_non_calculating_cohort(self):
        """Test resetting a cohort that is not calculating"""
        cohort = Cohort.objects.create(
            team=self.team,
            name="Normal Cohort",
            is_calculating=False,
        )

        request = self.factory.post(
            "/admin/recalculate-cohort/",
            {"action": "reset", "cohort_id": cohort.id, "force_reset": False},
        )
        request.user = self.user
        self._add_messages_framework_to_request(request)

        response = recalculate_cohort_view(request)

        self.assertEqual(response.status_code, 302)  # Redirect

        # Check that cohort was not modified
        cohort.refresh_from_db()
        self.assertFalse(cohort.is_calculating)
        self.assertEqual(cohort.errors_calculating, 0)

    def test_nonexistent_cohort(self):
        """Test handling of non-existent cohort"""
        request = self.factory.post(
            "/admin/recalculate-cohort/",
            {"action": "reset", "cohort_id": 99999, "force_reset": False},
        )
        request.user = self.user
        self._add_messages_framework_to_request(request)

        response = recalculate_cohort_view(request)

        self.assertEqual(response.status_code, 302)  # Redirect with error

    @patch("posthog.admin.admins.recalculate_cohort_admin.render")
    def test_get_request_returns_forms(self, mock_render):
        """Test that GET request returns both forms"""
        # Mock the render function to avoid static files issues in tests
        mock_render.return_value = Mock(status_code=200)

        request = self.factory.get("/admin/recalculate-cohort/")
        request.user = self.user

        recalculate_cohort_view(request)

        # Check that render was called with the correct context
        mock_render.assert_called_once()
        call_args = mock_render.call_args
        context = call_args[0][2]  # Third argument is context

        self.assertIn("form", context)
        self.assertIn("reset_form", context)
        self.assertEqual(context["title"], "Cohort Management")
