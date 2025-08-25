from posthog.test.base import BaseTest

from ee.models.session_summaries import ExtraSummaryContext, SessionSummaryRunMeta, SingleSessionSummary


class TestSingleSessionSummary(BaseTest):
    def setUp(self):
        super().setUp()
        self.session_id = "test-session-123"
        self.summary_data = {
            "key_actions": ["Clicked login button", "Navigated to dashboard"],
            "insights": "User successfully logged in and accessed main dashboard",
            "exceptions": [],
        }
        self.exception_event_ids = ["evt-001", "evt-002"]
        self.extra_context = ExtraSummaryContext(focus_area="authentication")
        self.run_metadata = SessionSummaryRunMeta(model_used="gpt-4", visual_confirmation=False)

    def test_add_summary(self):
        # Test adding a new summary
        summary = SingleSessionSummary.objects.add_summary(
            team=self.team,
            session_id=self.session_id,
            summary=self.summary_data,
            exception_event_ids=self.exception_event_ids,
            extra_summary_context=self.extra_context,
            run_metadata=self.run_metadata,
            created_by=self.user,
        )

        self.assertEqual(summary.session_id, self.session_id)
        self.assertEqual(summary.summary, self.summary_data)
        self.assertEqual(summary.exception_event_ids, self.exception_event_ids)
        # Check that dataclasses were converted to dicts
        self.assertEqual(summary.extra_summary_context, {"focus_area": "authentication"})
        self.assertEqual(summary.run_metadata, {"model_used": "gpt-4", "visual_confirmation": False})
        self.assertEqual(summary.created_by, self.user)
        self.assertEqual(summary.team, self.team)

    def test_get_summary_basic(self):
        # Add a summary first
        created_summary = SingleSessionSummary.objects.add_summary(
            team=self.team,
            session_id=self.session_id,
            summary=self.summary_data,
            exception_event_ids=self.exception_event_ids,
        )

        # Test retrieving it
        retrieved_summary = SingleSessionSummary.objects.get_summary(team=self.team, session_id=self.session_id)

        self.assertIsNotNone(retrieved_summary)
        self.assertEqual(retrieved_summary.id, created_summary.id)
        self.assertEqual(retrieved_summary.session_id, self.session_id)

    def test_get_summary_with_context(self):
        # Add summaries with different contexts
        summary_with_context = SingleSessionSummary.objects.add_summary(
            team=self.team,
            session_id=self.session_id,
            summary=self.summary_data,
            exception_event_ids=self.exception_event_ids,
            extra_summary_context=self.extra_context,
        )

        summary_without_context = SingleSessionSummary.objects.add_summary(
            team=self.team,
            session_id=self.session_id,
            summary=self.summary_data,
            exception_event_ids=[],
        )

        # Test retrieving with specific context
        retrieved = SingleSessionSummary.objects.get_summary(
            team=self.team, session_id=self.session_id, extra_summary_context=self.extra_context
        )
        self.assertEqual(retrieved.id, summary_with_context.id)

        # Test retrieving without context filter (should get most recent)
        retrieved_any = SingleSessionSummary.objects.get_summary(team=self.team, session_id=self.session_id)
        self.assertEqual(retrieved_any.id, summary_without_context.id)  # Most recent

    def test_get_summary_nonexistent(self):
        # Test retrieving non-existent summary
        result = SingleSessionSummary.objects.get_summary(team=self.team, session_id="non-existent-session")
        self.assertIsNone(result)

    def test_exception_event_ids_limit(self):
        # Test that exception_event_ids is limited to 100 items
        long_exception_list = [f"evt-{i:03d}" for i in range(150)]

        summary = SingleSessionSummary.objects.add_summary(
            team=self.team,
            session_id=self.session_id,
            summary=self.summary_data,
            exception_event_ids=long_exception_list,
        )

        # Should only store first 100
        self.assertEqual(len(summary.exception_event_ids), 100)
        self.assertEqual(summary.exception_event_ids[0], "evt-000")
        self.assertEqual(summary.exception_event_ids[99], "evt-099")

    def test_team_isolation(self):
        # Create another team using bootstrap
        from posthog.models import Organization

        other_team = Organization.objects.bootstrap(None)[2]

        # Add summary for first team
        SingleSessionSummary.objects.add_summary(
            team=self.team,
            session_id=self.session_id,
            summary=self.summary_data,
            exception_event_ids=self.exception_event_ids,
        )

        # Try to retrieve with different team
        result = SingleSessionSummary.objects.get_summary(team=other_team, session_id=self.session_id)
        self.assertIsNone(result)

    def test_multiple_summaries_ordering(self):
        # Create multiple summaries for the same session
        SingleSessionSummary.objects.add_summary(
            team=self.team,
            session_id=self.session_id,
            summary={"version": 1},
            exception_event_ids=[],
        )

        second_summary = SingleSessionSummary.objects.add_summary(
            team=self.team,
            session_id=self.session_id,
            summary={"version": 2},
            exception_event_ids=[],
        )

        # get_summary should return the most recent one
        retrieved = SingleSessionSummary.objects.get_summary(team=self.team, session_id=self.session_id)
        self.assertEqual(retrieved.id, second_summary.id)
        self.assertEqual(retrieved.summary["version"], 2)

    def test_str_representation(self):
        # Test string representation without context
        summary_no_context = SingleSessionSummary.objects.add_summary(
            team=self.team,
            session_id=self.session_id,
            summary=self.summary_data,
            exception_event_ids=[],
        )
        self.assertEqual(str(summary_no_context), f"Summary for session {self.session_id}")

        # Test string representation with context
        summary_with_context = SingleSessionSummary.objects.add_summary(
            team=self.team,
            session_id=self.session_id,
            summary=self.summary_data,
            exception_event_ids=[],
            extra_summary_context=self.extra_context,
        )
        # The context gets stored as a dict
        expected_str = f"Summary for session {self.session_id} with extra context {{'focus_area': 'authentication'}}"
        self.assertEqual(str(summary_with_context), expected_str)
