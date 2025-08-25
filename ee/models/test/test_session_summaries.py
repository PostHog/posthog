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


class TestSingleSessionSummaryBatch(BaseTest):
    def setUp(self):
        super().setUp()
        # Create test data for multiple sessions
        self.session_ids = [f"session-{i:03d}" for i in range(10)]
        self.extra_context = ExtraSummaryContext(focus_area="authentication")

        # Create summaries for testing
        # Sessions 0, 1, 2 - only have summaries without context
        for session_id in self.session_ids[:3]:
            SingleSessionSummary.objects.add_summary(
                team=self.team,
                session_id=session_id,
                summary={"content": f"Summary for {session_id} without context"},
                exception_event_ids=[],
                extra_summary_context=None,
            )

        # Sessions 3, 4 - have BOTH null and non-null context summaries (null created first)
        for session_id in self.session_ids[3:5]:
            # First create summary without context
            SingleSessionSummary.objects.add_summary(
                team=self.team,
                session_id=session_id,
                summary={"content": f"Summary for {session_id} without context - older"},
                exception_event_ids=[],
                extra_summary_context=None,
            )
            # Then create summary with context (newer)
            SingleSessionSummary.objects.add_summary(
                team=self.team,
                session_id=session_id,
                summary={"content": f"Summary for {session_id} with auth context - newer"},
                exception_event_ids=[],
                extra_summary_context=self.extra_context,
            )

        # Sessions 5, 6, 7 - only have summaries with context
        for session_id in self.session_ids[5:8]:
            SingleSessionSummary.objects.add_summary(
                team=self.team,
                session_id=session_id,
                summary={"content": f"Summary for {session_id} with auth context"},
                exception_event_ids=[],
                extra_summary_context=self.extra_context,
            )

        # Session 7 also has another context (for testing multiple contexts)
        other_context = ExtraSummaryContext(focus_area="checkout")
        SingleSessionSummary.objects.add_summary(
            team=self.team,
            session_id=self.session_ids[7],
            summary={"content": f"Summary for {self.session_ids[7]} with checkout context"},
            exception_event_ids=[],
            extra_summary_context=other_context,
        )

    def test_get_bulk_summaries_without_context(self):
        # Test retrieving summaries without extra context
        result = SingleSessionSummary.objects.get_bulk_summaries(
            team=self.team,
            session_ids=self.session_ids,
            extra_summary_context=None,
        )

        # Should get sessions 0, 1, 2, 3, 4 (all that have null context summaries)
        self.assertEqual(result.total_count, 5)
        self.assertEqual(len(result.results), 5)

        result_session_ids = {s.session_id for s in result.results}
        expected_session_ids = {self.session_ids[i] for i in [0, 1, 2, 3, 4]}
        self.assertEqual(result_session_ids, expected_session_ids)

        # All results should have null extra_summary_context
        for summary in result.results:
            self.assertIsNone(summary.extra_summary_context)

    def test_get_bulk_summaries_with_context(self):
        # Test retrieving summaries with specific extra context
        result = SingleSessionSummary.objects.get_bulk_summaries(
            team=self.team,
            session_ids=self.session_ids,
            extra_summary_context=self.extra_context,
        )

        # Should get sessions 3, 4, 5, 6, 7 with auth context
        self.assertEqual(result.total_count, 5)
        self.assertEqual(len(result.results), 5)

        result_session_ids = {s.session_id for s in result.results}
        expected_session_ids = {self.session_ids[i] for i in [3, 4, 5, 6, 7]}
        self.assertEqual(result_session_ids, expected_session_ids)

        # All results should have the auth context
        for summary in result.results:
            self.assertEqual(summary.extra_summary_context, {"focus_area": "authentication"})

    def test_get_bulk_summaries_pagination(self):
        # Test pagination with page size 2
        result_page1 = SingleSessionSummary.objects.get_bulk_summaries(
            team=self.team,
            session_ids=self.session_ids,
            extra_summary_context=None,
            limit=2,
            page=1,
        )

        self.assertEqual(result_page1.total_count, 5)  # Sessions 0, 1, 2, 3, 4 have null context
        self.assertEqual(len(result_page1.results), 2)
        self.assertTrue(result_page1.has_next)
        self.assertFalse(result_page1.has_previous)

        # Get page 2
        result_page2 = SingleSessionSummary.objects.get_bulk_summaries(
            team=self.team,
            session_ids=self.session_ids,
            extra_summary_context=None,
            limit=2,
            page=2,
        )

        self.assertEqual(result_page2.total_count, 5)
        self.assertEqual(len(result_page2.results), 2)
        self.assertTrue(result_page2.has_next)
        self.assertTrue(result_page2.has_previous)

        # Get page 3
        result_page3 = SingleSessionSummary.objects.get_bulk_summaries(
            team=self.team,
            session_ids=self.session_ids,
            extra_summary_context=None,
            limit=2,
            page=3,
        )

        self.assertEqual(result_page3.total_count, 5)
        self.assertEqual(len(result_page3.results), 1)
        self.assertFalse(result_page3.has_next)
        self.assertTrue(result_page3.has_previous)

        # Ensure no overlap between pages
        page1_ids = {s.session_id for s in result_page1.results}
        page2_ids = {s.session_id for s in result_page2.results}
        page3_ids = {s.session_id for s in result_page3.results}
        self.assertEqual(len(page1_ids & page2_ids), 0)
        self.assertEqual(len(page2_ids & page3_ids), 0)
        self.assertEqual(len(page1_ids & page3_ids), 0)

    def test_get_bulk_summaries_latest_per_session(self):
        # Create multiple summaries for the same session
        session_id = "session-latest-test"

        # Create older summary
        SingleSessionSummary.objects.add_summary(
            team=self.team,
            session_id=session_id,
            summary={"content": "Older summary", "version": 1},
            exception_event_ids=[],
            extra_summary_context=None,
        )

        # Wait a moment to ensure different timestamps
        import time

        time.sleep(0.01)

        # Create newer summary
        newer = SingleSessionSummary.objects.add_summary(
            team=self.team,
            session_id=session_id,
            summary={"content": "Newer summary", "version": 2},
            exception_event_ids=[],
            extra_summary_context=None,
        )

        # Retrieve bulk summaries
        result = SingleSessionSummary.objects.get_bulk_summaries(
            team=self.team,
            session_ids=[session_id],
            extra_summary_context=None,
        )

        # Should get only the latest summary
        self.assertEqual(result.total_count, 1)
        self.assertEqual(len(result.results), 1)
        self.assertEqual(result.results[0].id, newer.id)
        self.assertEqual(result.results[0].summary["version"], 2)

    def test_get_bulk_summaries_team_isolation(self):
        # Create another team
        from posthog.models import Organization

        other_team = Organization.objects.bootstrap(None)[2]

        # Create summaries for the other team
        for session_id in self.session_ids[:3]:
            SingleSessionSummary.objects.add_summary(
                team=other_team,
                session_id=session_id,
                summary={"content": f"Other team summary for {session_id}"},
                exception_event_ids=[],
                extra_summary_context=None,
            )

        # Try to retrieve with original team
        result = SingleSessionSummary.objects.get_bulk_summaries(
            team=self.team,
            session_ids=self.session_ids[:3],
            extra_summary_context=None,
        )

        # Should only get summaries for the original team
        self.assertEqual(result.total_count, 3)
        for summary in result.results:
            self.assertEqual(summary.team_id, self.team.id)

    def test_get_bulk_summaries_nonexistent_sessions(self):
        # Test with session IDs that don't exist
        nonexistent_ids = ["nonexistent-1", "nonexistent-2", "nonexistent-3"]

        result = SingleSessionSummary.objects.get_bulk_summaries(
            team=self.team,
            session_ids=nonexistent_ids,
            extra_summary_context=None,
        )

        # Should return empty results
        self.assertEqual(result.total_count, 0)
        self.assertEqual(len(result.results), 0)
        self.assertFalse(result.has_next)
        self.assertFalse(result.has_previous)

    def test_get_bulk_summaries_mixed_sessions(self):
        # Test with mix of existing and non-existing session IDs
        mixed_ids = [self.session_ids[0], "nonexistent", self.session_ids[1]]

        result = SingleSessionSummary.objects.get_bulk_summaries(
            team=self.team,
            session_ids=mixed_ids,
            extra_summary_context=None,
        )

        # Should only return existing sessions
        self.assertEqual(result.total_count, 2)
        result_session_ids = {s.session_id for s in result.results}
        self.assertEqual(result_session_ids, {self.session_ids[0], self.session_ids[1]})

    def test_get_bulk_summaries_invalid_page(self):
        # Test with invalid page number
        result = SingleSessionSummary.objects.get_bulk_summaries(
            team=self.team,
            session_ids=self.session_ids,
            extra_summary_context=None,
            page=999,
        )

        # Should return empty page
        self.assertEqual(result.total_count, 0)
        self.assertEqual(len(result.results), 0)
        self.assertFalse(result.has_next)
        self.assertFalse(result.has_previous)
