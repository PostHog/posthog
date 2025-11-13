from typing import Any

from posthog.test.base import BaseTest

from posthog.models import Organization, Team, User

from ee.hogai.session_summaries.session.output_data import SessionSummarySerializer
from ee.models.session_summaries import (
    ExtraSummaryContext,
    SessionSummaryPage,
    SessionSummaryRunMeta,
    SingleSessionSummary,
)


class TestSingleSessionSummary(BaseTest):
    session_id: str
    summary_data: dict[str, Any]
    exception_event_ids: list[str]
    extra_context: ExtraSummaryContext
    run_metadata: SessionSummaryRunMeta
    team: Team
    user: User

    def setUp(self) -> None:
        super().setUp()
        self.session_id = "test-session-123"
        # Create a minimal valid SessionSummarySerializer data structure
        self.summary_data = {
            "segments": [],
            "key_actions": [],
            "segment_outcomes": [],
            "session_outcome": {"description": "Test session summary", "success": True},
        }
        self.exception_event_ids = ["evt-001", "evt-002"]
        self.extra_context = ExtraSummaryContext(focus_area="authentication")
        self.run_metadata = SessionSummaryRunMeta(model_used="gpt-4", visual_confirmation=False)

    def test_add_summary(self) -> None:
        summary_serializer = SessionSummarySerializer(data=self.summary_data)
        summary_serializer.is_valid(raise_exception=True)
        SingleSessionSummary.objects.add_summary(
            team_id=self.team.id,
            session_id=self.session_id,
            summary=summary_serializer,
            exception_event_ids=self.exception_event_ids,
            extra_summary_context=self.extra_context,
            run_metadata=self.run_metadata,
            created_by=self.user,
        )

        # Retrieve the created summary
        summary = SingleSessionSummary.objects.get_summary(
            team_id=self.team.id,
            session_id=self.session_id,
            extra_summary_context=self.extra_context,
        )

        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary.session_id, self.session_id)
        self.assertEqual(summary.summary, self.summary_data)
        self.assertEqual(summary.exception_event_ids, self.exception_event_ids)
        self.assertEqual(summary.extra_summary_context, {"focus_area": "authentication"})
        self.assertEqual(
            summary.run_metadata,
            {"model_used": "gpt-4", "visual_confirmation": False, "visual_confirmation_results": None},
        )
        self.assertEqual(summary.created_by, self.user)
        self.assertEqual(summary.team_id, self.team.id)

    def test_get_summary_with_context(self) -> None:
        summary_serializer = SessionSummarySerializer(data=self.summary_data)
        summary_serializer.is_valid(raise_exception=True)
        SingleSessionSummary.objects.add_summary(
            team_id=self.team.id,
            session_id=self.session_id,
            summary=summary_serializer,
            exception_event_ids=self.exception_event_ids,
            extra_summary_context=self.extra_context,
            created_by=self.user,
        )
        SingleSessionSummary.objects.add_summary(
            team_id=self.team.id,
            session_id=self.session_id,
            summary=summary_serializer,
            exception_event_ids=[],
            created_by=self.user,
        )

        # Get the one with context
        retrieved: SingleSessionSummary | None = SingleSessionSummary.objects.get_summary(
            team_id=self.team.id, session_id=self.session_id, extra_summary_context=self.extra_context
        )
        assert retrieved is not None
        self.assertEqual(retrieved.extra_summary_context, {"focus_area": "authentication"})

        # Get the latest one (which has no context)
        retrieved_any: SingleSessionSummary | None = SingleSessionSummary.objects.get_summary(
            team_id=self.team.id, session_id=self.session_id
        )
        assert retrieved_any is not None
        self.assertIsNone(retrieved_any.extra_summary_context)

    def test_get_summary_nonexistent(self) -> None:
        result: SingleSessionSummary | None = SingleSessionSummary.objects.get_summary(
            team_id=self.team.id, session_id="non-existent-session"
        )
        self.assertIsNone(result)

    def test_exception_event_ids_limit(self) -> None:
        long_exception_list: list[str] = [f"evt-{i:03d}" for i in range(150)]

        summary_serializer = SessionSummarySerializer(data=self.summary_data)
        summary_serializer.is_valid(raise_exception=True)
        SingleSessionSummary.objects.add_summary(
            team_id=self.team.id,
            session_id=self.session_id,
            summary=summary_serializer,
            exception_event_ids=long_exception_list,
            created_by=self.user,
        )

        # Retrieve the created summary
        summary = SingleSessionSummary.objects.get_summary(
            team_id=self.team.id,
            session_id=self.session_id,
        )
        assert summary is not None
        self.assertEqual(len(summary.exception_event_ids), 100)
        self.assertEqual(summary.exception_event_ids[0], "evt-000")
        self.assertEqual(summary.exception_event_ids[99], "evt-099")

    def test_team_isolation(self) -> None:
        other_team: Team = Organization.objects.bootstrap(None)[2]

        summary_serializer = SessionSummarySerializer(data=self.summary_data)
        summary_serializer.is_valid(raise_exception=True)
        SingleSessionSummary.objects.add_summary(
            team_id=self.team.id,
            session_id=self.session_id,
            summary=summary_serializer,
            exception_event_ids=self.exception_event_ids,
            created_by=self.user,
        )

        result: SingleSessionSummary | None = SingleSessionSummary.objects.get_summary(
            team_id=other_team.id, session_id=self.session_id
        )
        self.assertIsNone(result)

    def test_multiple_summaries_ordering(self) -> None:
        # Create minimal valid data with version info in session_outcome
        summary_data_1 = {
            "segments": [],
            "key_actions": [],
            "segment_outcomes": [],
            "session_outcome": {"description": "Version 1", "success": True},
        }
        summary_serializer_1 = SessionSummarySerializer(data=summary_data_1)
        summary_serializer_1.is_valid(raise_exception=True)
        SingleSessionSummary.objects.add_summary(
            team_id=self.team.id,
            session_id=self.session_id,
            summary=summary_serializer_1,
            exception_event_ids=[],
            created_by=self.user,
        )

        summary_data_2: dict[str, Any] = {
            "segments": [],
            "key_actions": [],
            "segment_outcomes": [],
            "session_outcome": {"description": "Version 2", "success": True},
        }
        summary_serializer_2 = SessionSummarySerializer(data=summary_data_2)
        summary_serializer_2.is_valid(raise_exception=True)
        SingleSessionSummary.objects.add_summary(
            team_id=self.team.id,
            session_id=self.session_id,
            summary=summary_serializer_2,
            exception_event_ids=[],
            created_by=self.user,
        )

        retrieved: SingleSessionSummary | None = SingleSessionSummary.objects.get_summary(
            team_id=self.team.id, session_id=self.session_id
        )
        assert retrieved is not None
        # Should get the latest one (Version 2)
        self.assertEqual(retrieved.summary["session_outcome"]["description"], "Version 2")

    def test_run_metadata_storage(self) -> None:
        summary_serializer = SessionSummarySerializer(data=self.summary_data)
        summary_serializer.is_valid(raise_exception=True)

        # Test with different run metadata values
        run_metadata_gpt5 = SessionSummaryRunMeta(model_used="gpt-5", visual_confirmation=True)
        SingleSessionSummary.objects.add_summary(
            team_id=self.team.id,
            session_id="session-with-gpt5",
            summary=summary_serializer,
            exception_event_ids=[],
            run_metadata=run_metadata_gpt5,
            created_by=self.user,
        )

        run_metadata_claude = SessionSummaryRunMeta(model_used="claude-4-1-opus", visual_confirmation=False)
        SingleSessionSummary.objects.add_summary(
            team_id=self.team.id,
            session_id="session-with-claude",
            summary=summary_serializer,
            exception_event_ids=[],
            run_metadata=run_metadata_claude,
            created_by=self.user,
        )

        # Test with no run metadata (should store None)
        SingleSessionSummary.objects.add_summary(
            team_id=self.team.id,
            session_id="session-no-metadata",
            summary=summary_serializer,
            exception_event_ids=[],
            run_metadata=None,
            created_by=self.user,
        )

        # Verify GPT-5 metadata
        gpt5_summary = SingleSessionSummary.objects.get_summary(
            team_id=self.team.id,
            session_id="session-with-gpt5",
        )
        assert gpt5_summary is not None
        self.assertEqual(
            gpt5_summary.run_metadata,
            {"model_used": "gpt-5", "visual_confirmation": True, "visual_confirmation_results": None},
        )

        # Verify Claude metadata
        claude_summary = SingleSessionSummary.objects.get_summary(
            team_id=self.team.id,
            session_id="session-with-claude",
        )
        assert claude_summary is not None
        self.assertEqual(
            claude_summary.run_metadata,
            {"model_used": "claude-4-1-opus", "visual_confirmation": False, "visual_confirmation_results": None},
        )

        # Verify None metadata
        no_metadata_summary = SingleSessionSummary.objects.get_summary(
            team_id=self.team.id,
            session_id="session-no-metadata",
        )
        assert no_metadata_summary is not None
        self.assertIsNone(no_metadata_summary.run_metadata)


class TestSingleSessionSummaryBulk(BaseTest):
    session_ids: list[str]
    extra_context: ExtraSummaryContext
    team: Team
    user: User

    def setUp(self) -> None:
        super().setUp()
        self.session_ids = [f"session-{i:03d}" for i in range(10)]
        self.extra_context = ExtraSummaryContext(focus_area="authentication")
        self._setup_test_data()

    def _setup_test_data(self) -> None:
        """Set up test data for batch operations."""

        # Create a minimal valid SessionSummarySerializer data structure
        def create_summary_data(content: str) -> dict:
            return {
                "segments": [],
                "key_actions": [],
                "segment_outcomes": [],
                "session_outcome": {"description": content, "success": True},
            }

        for session_id in self.session_ids[:3]:
            summary_data = create_summary_data(f"Summary for {session_id} without context")
            summary_serializer = SessionSummarySerializer(data=summary_data)
            summary_serializer.is_valid(raise_exception=True)
            SingleSessionSummary.objects.add_summary(
                team_id=self.team.id,
                session_id=session_id,
                summary=summary_serializer,
                exception_event_ids=[],
                extra_summary_context=None,
                created_by=self.user,
            )

        for session_id in self.session_ids[3:5]:
            summary_data_1 = create_summary_data(f"Summary for {session_id} without context - older")
            summary_serializer_1 = SessionSummarySerializer(data=summary_data_1)
            summary_serializer_1.is_valid(raise_exception=True)
            SingleSessionSummary.objects.add_summary(
                team_id=self.team.id,
                session_id=session_id,
                summary=summary_serializer_1,
                exception_event_ids=[],
                extra_summary_context=None,
                created_by=self.user,
            )
            summary_data_2 = create_summary_data(f"Summary for {session_id} with auth context - newer")
            summary_serializer_2 = SessionSummarySerializer(data=summary_data_2)
            summary_serializer_2.is_valid(raise_exception=True)
            SingleSessionSummary.objects.add_summary(
                team_id=self.team.id,
                session_id=session_id,
                summary=summary_serializer_2,
                exception_event_ids=[],
                extra_summary_context=self.extra_context,
                created_by=self.user,
            )

        for session_id in self.session_ids[5:8]:
            summary_data = create_summary_data(f"Summary for {session_id} with auth context")
            summary_serializer = SessionSummarySerializer(data=summary_data)
            summary_serializer.is_valid(raise_exception=True)
            SingleSessionSummary.objects.add_summary(
                team_id=self.team.id,
                session_id=session_id,
                summary=summary_serializer,
                exception_event_ids=[],
                extra_summary_context=self.extra_context,
                created_by=self.user,
            )

        other_context: ExtraSummaryContext = ExtraSummaryContext(focus_area="checkout")
        summary_data = create_summary_data(f"Summary for {self.session_ids[7]} with checkout context")
        summary_serializer = SessionSummarySerializer(data=summary_data)
        summary_serializer.is_valid(raise_exception=True)
        SingleSessionSummary.objects.add_summary(
            team_id=self.team.id,
            session_id=self.session_ids[7],
            summary=summary_serializer,
            exception_event_ids=[],
            extra_summary_context=other_context,
            created_by=self.user,
        )

    def test_get_bulk_summaries_without_context(self) -> None:
        result: SessionSummaryPage = SingleSessionSummary.objects.get_bulk_summaries(
            team_id=self.team.id,
            session_ids=self.session_ids,
            extra_summary_context=None,
        )

        self.assertEqual(len(result.results), 5)

        result_session_ids: set[str] = {s.session_id for s in result.results}
        expected_session_ids: set[str] = {self.session_ids[i] for i in [0, 1, 2, 3, 4]}
        self.assertEqual(result_session_ids, expected_session_ids)

        for summary in result.results:
            self.assertIsNone(summary.extra_summary_context)

    def test_get_bulk_summaries_with_context(self) -> None:
        result: SessionSummaryPage = SingleSessionSummary.objects.get_bulk_summaries(
            team_id=self.team.id,
            session_ids=self.session_ids,
            extra_summary_context=self.extra_context,
        )

        self.assertEqual(len(result.results), 4)

        result_session_ids: set[str] = {s.session_id for s in result.results}
        expected_session_ids: set[str] = {self.session_ids[i] for i in [3, 4, 5, 6]}
        self.assertEqual(result_session_ids, expected_session_ids)

        for summary in result.results:
            self.assertEqual(summary.extra_summary_context, {"focus_area": "authentication"})

    def test_get_bulk_summaries_pagination(self) -> None:
        result_offset_0: SessionSummaryPage = SingleSessionSummary.objects.get_bulk_summaries(
            team_id=self.team.id,
            session_ids=self.session_ids,
            extra_summary_context=None,
            limit=2,
            offset=0,
        )

        self.assertEqual(len(result_offset_0.results), 2)
        self.assertTrue(result_offset_0.has_next)

        result_offset_2: SessionSummaryPage = SingleSessionSummary.objects.get_bulk_summaries(
            team_id=self.team.id,
            session_ids=self.session_ids,
            extra_summary_context=None,
            limit=2,
            offset=2,
        )

        self.assertEqual(len(result_offset_2.results), 2)
        self.assertTrue(result_offset_2.has_next)

        result_offset_4: SessionSummaryPage = SingleSessionSummary.objects.get_bulk_summaries(
            team_id=self.team.id,
            session_ids=self.session_ids,
            extra_summary_context=None,
            limit=2,
            offset=4,
        )

        self.assertEqual(len(result_offset_4.results), 1)
        self.assertFalse(result_offset_4.has_next)

        offset_0_ids: set[str] = {s.session_id for s in result_offset_0.results}
        offset_2_ids: set[str] = {s.session_id for s in result_offset_2.results}
        offset_4_ids: set[str] = {s.session_id for s in result_offset_4.results}
        self.assertEqual(len(offset_0_ids & offset_2_ids), 0)
        self.assertEqual(len(offset_2_ids & offset_4_ids), 0)
        self.assertEqual(len(offset_0_ids & offset_4_ids), 0)

    def test_get_bulk_summaries_latest_per_session(self) -> None:
        session_id: str = "session-latest-test"
        summary_data_1: dict[str, Any] = {
            "segments": [],
            "key_actions": [],
            "segment_outcomes": [],
            "session_outcome": {"description": "Older summary - version 1", "success": True},
        }
        summary_serializer_1 = SessionSummarySerializer(data=summary_data_1)
        summary_serializer_1.is_valid(raise_exception=True)
        SingleSessionSummary.objects.add_summary(
            team_id=self.team.id,
            session_id=session_id,
            summary=summary_serializer_1,
            exception_event_ids=[],
            extra_summary_context=None,
            created_by=self.user,
        )
        summary_data_2: dict[str, Any] = {
            "segments": [],
            "key_actions": [],
            "segment_outcomes": [],
            "session_outcome": {"description": "Newer summary - version 2", "success": True},
        }
        summary_serializer_2 = SessionSummarySerializer(data=summary_data_2)
        summary_serializer_2.is_valid(raise_exception=True)
        SingleSessionSummary.objects.add_summary(
            team_id=self.team.id,
            session_id=session_id,
            summary=summary_serializer_2,
            exception_event_ids=[],
            extra_summary_context=None,
            created_by=self.user,
        )
        result: SessionSummaryPage = SingleSessionSummary.objects.get_bulk_summaries(
            team_id=self.team.id,
            session_ids=[session_id],
            extra_summary_context=None,
        )
        self.assertEqual(len(result.results), 1)
        # Should get the latest one (version 2)
        self.assertEqual(result.results[0].summary["session_outcome"]["description"], "Newer summary - version 2")

    def test_get_bulk_summaries_team_isolation(self) -> None:
        other_team: Team = Organization.objects.bootstrap(None)[2]

        for session_id in self.session_ids[:3]:
            summary_data: dict[str, Any] = {
                "segments": [],
                "key_actions": [],
                "segment_outcomes": [],
                "session_outcome": {"description": f"Other team summary for {session_id}", "success": True},
            }
            summary_serializer = SessionSummarySerializer(data=summary_data)
            summary_serializer.is_valid(raise_exception=True)
            SingleSessionSummary.objects.add_summary(
                team_id=other_team.id,
                session_id=session_id,
                summary=summary_serializer,
                exception_event_ids=[],
                extra_summary_context=None,
                created_by=self.user,
            )

        result: SessionSummaryPage = SingleSessionSummary.objects.get_bulk_summaries(
            team_id=self.team.id,
            session_ids=self.session_ids[:3],
            extra_summary_context=None,
        )

        self.assertEqual(len(result.results), 3)
        for summary in result.results:
            self.assertEqual(summary.team_id, self.team.id)

    def test_get_bulk_summaries_mixed_sessions(self) -> None:
        mixed_ids: list[str] = [self.session_ids[0], "nonexistent", self.session_ids[1]]

        result: SessionSummaryPage = SingleSessionSummary.objects.get_bulk_summaries(
            team_id=self.team.id,
            session_ids=mixed_ids,
            extra_summary_context=None,
        )

        self.assertEqual(len(result.results), 2)
        result_session_ids: set[str] = {s.session_id for s in result.results}
        self.assertEqual(result_session_ids, {self.session_ids[0], self.session_ids[1]})

    def test_summaries_exist_single_without_context(self) -> None:
        result: dict[str, bool] = SingleSessionSummary.objects.summaries_exist(
            team_id=self.team.id,
            session_ids=["non-existent"],
            extra_summary_context=None,
        )
        self.assertEqual(result, {"non-existent": False})
        # Add a summary and test again
        summary_data = {
            "segments": [],
            "key_actions": [],
            "segment_outcomes": [],
            "session_outcome": {"description": "test", "success": True},
        }
        summary_serializer = SessionSummarySerializer(data=summary_data)
        summary_serializer.is_valid(raise_exception=True)
        SingleSessionSummary.objects.add_summary(
            team_id=self.team.id,
            session_id="test-session-1",
            summary=summary_serializer,
            exception_event_ids=[],
            created_by=self.user,
        )
        result = SingleSessionSummary.objects.summaries_exist(
            team_id=self.team.id,
            session_ids=["test-session-1"],
            extra_summary_context=None,
        )
        self.assertEqual(result, {"test-session-1": True})

    def test_summaries_exist_multiple_without_context(self) -> None:
        # Use existing test data - sessions 0-4 have summaries without context
        result: dict[str, bool] = SingleSessionSummary.objects.summaries_exist(
            team_id=self.team.id,
            session_ids=[self.session_ids[0], self.session_ids[1], self.session_ids[8], "non-existent"],
            extra_summary_context=None,
        )
        self.assertEqual(
            result,
            {
                self.session_ids[0]: True,
                self.session_ids[1]: True,
                self.session_ids[8]: False,  # Has no summary
                "non-existent": False,
            },
        )

    def test_summaries_exist_with_context(self) -> None:
        # Use existing test data - sessions 3-6 have summaries with auth context
        result: dict[str, bool] = SingleSessionSummary.objects.summaries_exist(
            team_id=self.team.id,
            session_ids=[self.session_ids[3], self.session_ids[5], self.session_ids[0], self.session_ids[9]],
            extra_summary_context=self.extra_context,
        )
        self.assertEqual(
            result,
            {
                self.session_ids[3]: True,  # Has auth context
                self.session_ids[5]: True,  # Has auth context
                self.session_ids[0]: False,  # Has no context
                self.session_ids[9]: False,  # Has no summary
            },
        )

    def test_summaries_exist_context_mismatch(self) -> None:
        different_context: ExtraSummaryContext = ExtraSummaryContext(focus_area="checkout")
        # Session 7 has checkout context (from _setup_test_data)
        result: dict[str, bool] = SingleSessionSummary.objects.summaries_exist(
            team_id=self.team.id,
            session_ids=[self.session_ids[7]],
            extra_summary_context=different_context,
        )
        self.assertEqual(result, {self.session_ids[7]: True})
        # But not auth context
        result = SingleSessionSummary.objects.summaries_exist(
            team_id=self.team.id,
            session_ids=[self.session_ids[7]],
            extra_summary_context=self.extra_context,
        )
        self.assertEqual(result, {self.session_ids[7]: False})

    def test_summaries_exist_team_isolation(self) -> None:
        other_team: Team = Organization.objects.bootstrap(None)[2]
        # Add summary for other team
        summary_data = {
            "segments": [],
            "key_actions": [],
            "segment_outcomes": [],
            "session_outcome": {"description": "other team", "success": True},
        }
        summary_serializer = SessionSummarySerializer(data=summary_data)
        summary_serializer.is_valid(raise_exception=True)
        SingleSessionSummary.objects.add_summary(
            team_id=other_team.id,
            session_id="cross-team-session",
            summary=summary_serializer,
            exception_event_ids=[],
            created_by=self.user,
        )
        # Should not be visible from our team
        result: dict[str, bool] = SingleSessionSummary.objects.summaries_exist(
            team_id=self.team.id,
            session_ids=["cross-team-session"],
            extra_summary_context=None,
        )
        self.assertEqual(result, {"cross-team-session": False})
        # Should be visible from the other team
        result = SingleSessionSummary.objects.summaries_exist(
            team_id=other_team.id,
            session_ids=["cross-team-session"],
            extra_summary_context=None,
        )
        self.assertEqual(result, {"cross-team-session": True})

    def test_summaries_exist_latest_only(self) -> None:
        # Sessions 3-4 have both old (no context) and new (auth context) summaries
        # Test with auth context - should find the latest summaries
        result: dict[str, bool] = SingleSessionSummary.objects.summaries_exist(
            team_id=self.team.id,
            session_ids=[self.session_ids[3], self.session_ids[4]],
            extra_summary_context=self.extra_context,
        )
        self.assertEqual(
            result,
            {
                self.session_ids[3]: True,
                self.session_ids[4]: True,
            },
        )
        # Test without context - the method returns the latest summary matching the filter
        # Since there are old summaries without context, it will return True
        result = SingleSessionSummary.objects.summaries_exist(
            team_id=self.team.id,
            session_ids=[self.session_ids[3], self.session_ids[4]],
            extra_summary_context=None,
        )
        self.assertEqual(
            result,
            {
                self.session_ids[3]: True,  # Has old summaries without context
                self.session_ids[4]: True,  # Has old summaries without context
            },
        )

    def test_summaries_exist_large_batch(self) -> None:
        large_session_ids: list[str] = [f"large-batch-{i:04d}" for i in range(200)]
        for i in range(100):
            summary_data: dict[str, Any] = {
                "segments": [],
                "key_actions": [],
                "segment_outcomes": [],
                "session_outcome": {"description": f"Summary {i}", "success": True},
            }
            summary_serializer = SessionSummarySerializer(data=summary_data)
            summary_serializer.is_valid(raise_exception=True)
            SingleSessionSummary.objects.add_summary(
                team_id=self.team.id,
                session_id=large_session_ids[i],
                summary=summary_serializer,
                exception_event_ids=[],
                created_by=self.user,
            )
        # Check all at once
        result: dict[str, bool] = SingleSessionSummary.objects.summaries_exist(
            team_id=self.team.id,
            session_ids=large_session_ids,
            extra_summary_context=None,
        )
        # First 100 should exist, last 100 should not
        for i in range(200):
            expected: bool = i < 100
            self.assertEqual(result[large_session_ids[i]], expected, f"Session {i} existence check failed")
