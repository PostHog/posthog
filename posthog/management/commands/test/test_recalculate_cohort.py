from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

from posthog.models import Cohort


class TestRecalculateCohortCommand(BaseTest):
    def setUp(self):
        super().setUp()
        self.cohort = Cohort.objects.create(
            team=self.team,
            name="Test Cohort",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [{"type": "person", "key": "email", "operator": "exact", "value": "test@example.com"}],
                }
            },
        )

    @patch("posthog.management.commands.recalculate_cohort.increment_version_and_enqueue_calculate_cohort")
    def test_successful_recalculation(self, mock_enqueue):
        """Test successful cohort recalculation"""
        call_command("recalculate_cohort", str(self.cohort.id))
        mock_enqueue.assert_called_once_with(self.cohort, initiating_user=None)

    def test_nonexistent_cohort(self):
        """Test error when cohort doesn't exist"""
        with self.assertRaises(CommandError) as cm:
            call_command("recalculate_cohort", "99999")
        self.assertIn("does not exist", str(cm.exception))

    def test_deleted_cohort(self):
        """Test error when trying to recalculate deleted cohort"""
        self.cohort.deleted = True
        self.cohort.save()

        with self.assertRaises(CommandError) as cm:
            call_command("recalculate_cohort", str(self.cohort.id))
        self.assertIn("is deleted and cannot be recalculated", str(cm.exception))

    def test_static_cohort(self):
        """Test error when trying to recalculate static cohort"""
        self.cohort.is_static = True
        self.cohort.save()

        with self.assertRaises(CommandError) as cm:
            call_command("recalculate_cohort", str(self.cohort.id))
        self.assertIn("is static and cannot be recalculated", str(cm.exception))

    def test_calculating_cohort_without_force(self):
        """Test error when cohort is already calculating and force is not used"""
        self.cohort.is_calculating = True
        self.cohort.save()

        with self.assertRaises(CommandError) as cm:
            call_command("recalculate_cohort", str(self.cohort.id))
        self.assertIn("is currently calculating", str(cm.exception))

    @patch("posthog.management.commands.recalculate_cohort.increment_version_and_enqueue_calculate_cohort")
    def test_force_recalculation(self, mock_enqueue):
        """Test force recalculation when cohort is already calculating"""
        self.cohort.is_calculating = True
        self.cohort.save()

        call_command("recalculate_cohort", str(self.cohort.id), "--force")

        # Check that is_calculating was reset
        self.cohort.refresh_from_db()
        self.assertFalse(self.cohort.is_calculating)
        mock_enqueue.assert_called_once_with(self.cohort, initiating_user=None)

    @patch("posthog.management.commands.recalculate_cohort.increment_version_and_enqueue_calculate_cohort")
    def test_enqueue_failure_handling(self, mock_enqueue):
        """Test error handling when enqueue fails"""
        mock_enqueue.side_effect = Exception("Enqueue failed")

        with self.assertRaises(CommandError) as cm:
            call_command("recalculate_cohort", str(self.cohort.id))
        self.assertIn("Failed to recalculate cohort", str(cm.exception))
        self.assertIn("Enqueue failed", str(cm.exception))
