from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from posthog.models import User
from posthog.models.hog_flow import HogFlow


class BackfillHogFlowBillableActionTypesTest(TestCase):
    def setUp(self):
        self.organization, self.team, self.user = User.objects.bootstrap("Test Organization", "test@example.com", None)

    def test_backfill_with_various_billable_action_types(self):
        """Test that the command correctly backfills various billable action configurations"""
        flow1 = HogFlow.objects.create(
            team=self.team,
            created_by=self.user,
            name="Email and Destination Flow",
            actions=[
                {"type": "trigger", "config": {}},
                {"type": "function_email", "config": {}},
                {"type": "function", "config": {}},
                {"type": "delay", "config": {}},
            ],
            trigger={"type": "event"},
        )

        flow2 = HogFlow.objects.create(
            team=self.team,
            created_by=self.user,
            name="Complex Flow with SMS and Push",
            actions=[
                {"type": "trigger", "config": {}},
                {"type": "delay", "config": {}},
                {"type": "conditional_branch", "config": {}},
                {"type": "function_email", "config": {}},
                {"type": "function", "config": {}},
                {"type": "function", "config": {}},  # Duplicate function action
                {"type": "function_sms", "config": {}},
                {"type": "function_push", "config": {}},
            ],
            trigger={"type": "event"},
        )

        flow3 = HogFlow.objects.create(
            team=self.team,
            created_by=self.user,
            name="Only Non-Billable Actions Flow",
            actions=[
                {"type": "trigger", "config": {}},
                {"type": "delay", "config": {}},
                {"type": "conditional_branch", "config": {}},
                {"type": "exit", "config": {}},
            ],
            trigger={"type": "event"},
        )

        # Run the command
        out = StringIO()
        call_command("backfill_hogflow_billable_action_types", stdout=out)

        # Refresh from database
        flow1.refresh_from_db()
        flow2.refresh_from_db()
        flow3.refresh_from_db()

        # Check results - only billable action types
        self.assertEqual(sorted(flow1.billable_action_types or []), ["function", "function_email"])
        self.assertEqual(
            sorted(flow2.billable_action_types or []), ["function", "function_email", "function_push", "function_sms"]
        )
        self.assertEqual(flow3.billable_action_types, [])

        # Check output
        output = out.getvalue()
        # Should have processed flows and updated at least the 3 we created
        self.assertIn("Backfill completed", output)

    def test_dry_run_mode(self):
        """Test that dry-run mode doesn't make changes"""
        flow = HogFlow.objects.create(
            team=self.team,
            created_by=self.user,
            name="Test Flow",
            actions=[{"type": "function", "config": {}}],
            trigger={"type": "event"},
            billable_action_types=None,  # Simulate unmigrated flow
        )

        out = StringIO()
        call_command("backfill_hogflow_billable_action_types", "--dry-run", stdout=out)

        flow.refresh_from_db()
        self.assertIsNone(flow.billable_action_types)

        output = out.getvalue()
        self.assertIn("DRY RUN mode", output)
        self.assertIn("DRY RUN completed", output)

    def test_recomputation_of_wrong_values(self):
        """Test that the command fixes incorrect billable_action_types values"""
        flow = HogFlow.objects.create(
            team=self.team,
            created_by=self.user,
            name="Test Flow",
            actions=[{"type": "function", "config": {}}, {"type": "delay", "config": {}}],
            trigger={"type": "event"},
            billable_action_types=["old_value"],  # Pre-existing wrong value
        )

        # Run the command - should fix the wrong value
        call_command("backfill_hogflow_billable_action_types")
        flow.refresh_from_db()
        self.assertEqual(sorted(flow.billable_action_types or []), ["function"])  # Only function is billable

    def test_handles_duplicates(self):
        """Test that duplicate action types are deduplicated"""
        flow = HogFlow.objects.create(
            team=self.team,
            created_by=self.user,
            name="Duplicate Actions Flow",
            actions=[
                {"type": "function", "config": {}},
                {"type": "function", "config": {}},  # Duplicate
                {"type": "delay", "config": {}},
                {"type": "delay", "config": {}},  # Duplicate
            ],
            trigger={"type": "event"},
        )

        call_command("backfill_hogflow_billable_action_types")
        flow.refresh_from_db()

        # Should have unique types only (and only billable ones)
        self.assertEqual(sorted(flow.billable_action_types or []), ["function"])

    def test_batch_processing(self):
        """Test that batch processing works correctly"""
        # Clean up any leftover flows from previous runs
        HogFlow.objects.filter(name__startswith="Batch Flow Test").delete()

        # Create 25 flows to test batching
        created_ids = []
        for i in range(25):
            flow = HogFlow.objects.create(
                team=self.team,
                created_by=self.user,
                name=f"Batch Flow Test {i}",
                actions=[{"type": "function", "config": {}}],
                trigger={"type": "event"},
                # Don't set billable_action_types, it will default to []
            )
            created_ids.append(flow.id)

        # Run with small page size
        out = StringIO()
        call_command("backfill_hogflow_billable_action_types", "--page-size", "10", stdout=out)

        output = out.getvalue()

        # Check all were processed
        flows = HogFlow.objects.filter(id__in=created_ids)
        self.assertEqual(flows.count(), 25)

        for flow in flows:
            flow.refresh_from_db()
            self.assertEqual(flow.billable_action_types, ["function"])

        self.assertIn("Backfill completed", output)
        # Should have updated flows
        self.assertIn("Updated:", output)
