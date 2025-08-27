import time
from typing import Any

from posthog.test.base import BaseTest

from posthog.models import Organization, Team, User

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
        self.summary_data = {
            "key_actions": ["Clicked login button", "Navigated to dashboard"],
            "insights": "User successfully logged in and accessed main dashboard",
            "exceptions": [],
        }
        self.exception_event_ids = ["evt-001", "evt-002"]
        self.extra_context = ExtraSummaryContext(focus_area="authentication")
        self.run_metadata = SessionSummaryRunMeta(model_used="gpt-4", visual_confirmation=False)

    def test_add_summary(self) -> None:
        summary: SingleSessionSummary = SingleSessionSummary.objects.add_summary(
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
        self.assertEqual(summary.extra_summary_context, {"focus_area": "authentication"})
        self.assertEqual(summary.run_metadata, {"model_used": "gpt-4", "visual_confirmation": False})
        self.assertEqual(summary.created_by, self.user)
        self.assertEqual(summary.team, self.team)

    def test_get_summary_basic(self) -> None:
        created_summary: SingleSessionSummary = SingleSessionSummary.objects.add_summary(
            team=self.team,
            session_id=self.session_id,
            summary=self.summary_data,
            exception_event_ids=self.exception_event_ids,
        )

        retrieved_summary: SingleSessionSummary | None = SingleSessionSummary.objects.get_summary(
            team=self.team, session_id=self.session_id
        )

        self.assertIsNotNone(retrieved_summary)
        assert retrieved_summary is not None
        self.assertEqual(retrieved_summary.id, created_summary.id)
        self.assertEqual(retrieved_summary.session_id, self.session_id)

    def test_get_summary_with_context(self) -> None:
        summary_with_context: SingleSessionSummary = SingleSessionSummary.objects.add_summary(
            team=self.team,
            session_id=self.session_id,
            summary=self.summary_data,
            exception_event_ids=self.exception_event_ids,
            extra_summary_context=self.extra_context,
        )

        summary_without_context: SingleSessionSummary = SingleSessionSummary.objects.add_summary(
            team=self.team,
            session_id=self.session_id,
            summary=self.summary_data,
            exception_event_ids=[],
        )

        retrieved: SingleSessionSummary | None = SingleSessionSummary.objects.get_summary(
            team=self.team, session_id=self.session_id, extra_summary_context=self.extra_context
        )
        assert retrieved is not None
        self.assertEqual(retrieved.id, summary_with_context.id)

        retrieved_any: SingleSessionSummary | None = SingleSessionSummary.objects.get_summary(
            team=self.team, session_id=self.session_id
        )
        assert retrieved_any is not None
        self.assertEqual(retrieved_any.id, summary_without_context.id)

    def test_get_summary_nonexistent(self) -> None:
        result: SingleSessionSummary | None = SingleSessionSummary.objects.get_summary(
            team=self.team, session_id="non-existent-session"
        )
        self.assertIsNone(result)

    def test_exception_event_ids_limit(self) -> None:
        long_exception_list: list[str] = [f"evt-{i:03d}" for i in range(150)]

        summary: SingleSessionSummary = SingleSessionSummary.objects.add_summary(
            team=self.team,
            session_id=self.session_id,
            summary=self.summary_data,
            exception_event_ids=long_exception_list,
        )

        self.assertEqual(len(summary.exception_event_ids), 100)
        self.assertEqual(summary.exception_event_ids[0], "evt-000")
        self.assertEqual(summary.exception_event_ids[99], "evt-099")

    def test_team_isolation(self) -> None:
        other_team: Team = Organization.objects.bootstrap(None)[2]

        SingleSessionSummary.objects.add_summary(
            team=self.team,
            session_id=self.session_id,
            summary=self.summary_data,
            exception_event_ids=self.exception_event_ids,
        )

        result: SingleSessionSummary | None = SingleSessionSummary.objects.get_summary(
            team=other_team, session_id=self.session_id
        )
        self.assertIsNone(result)

    def test_multiple_summaries_ordering(self) -> None:
        SingleSessionSummary.objects.add_summary(
            team=self.team,
            session_id=self.session_id,
            summary={"version": 1},
            exception_event_ids=[],
        )

        second_summary: SingleSessionSummary = SingleSessionSummary.objects.add_summary(
            team=self.team,
            session_id=self.session_id,
            summary={"version": 2},
            exception_event_ids=[],
        )

        retrieved: SingleSessionSummary | None = SingleSessionSummary.objects.get_summary(
            team=self.team, session_id=self.session_id
        )
        assert retrieved is not None
        self.assertEqual(retrieved.id, second_summary.id)
        self.assertEqual(retrieved.summary["version"], 2)

    def test_str_representation(self) -> None:
        summary_no_context: SingleSessionSummary = SingleSessionSummary.objects.add_summary(
            team=self.team,
            session_id=self.session_id,
            summary=self.summary_data,
            exception_event_ids=[],
        )
        self.assertEqual(str(summary_no_context), f"Summary for session {self.session_id}")

        summary_with_context: SingleSessionSummary = SingleSessionSummary.objects.add_summary(
            team=self.team,
            session_id=self.session_id,
            summary=self.summary_data,
            exception_event_ids=[],
            extra_summary_context=self.extra_context,
        )
        expected_str: str = (
            f"Summary for session {self.session_id} with extra context {{'focus_area': 'authentication'}}"
        )
        self.assertEqual(str(summary_with_context), expected_str)


class TestSingleSessionSummaryBatch(BaseTest):
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
        for session_id in self.session_ids[:3]:
            SingleSessionSummary.objects.add_summary(
                team=self.team,
                session_id=session_id,
                summary={"content": f"Summary for {session_id} without context"},
                exception_event_ids=[],
                extra_summary_context=None,
            )

        for session_id in self.session_ids[3:5]:
            SingleSessionSummary.objects.add_summary(
                team=self.team,
                session_id=session_id,
                summary={"content": f"Summary for {session_id} without context - older"},
                exception_event_ids=[],
                extra_summary_context=None,
            )
            SingleSessionSummary.objects.add_summary(
                team=self.team,
                session_id=session_id,
                summary={"content": f"Summary for {session_id} with auth context - newer"},
                exception_event_ids=[],
                extra_summary_context=self.extra_context,
            )

        for session_id in self.session_ids[5:8]:
            SingleSessionSummary.objects.add_summary(
                team=self.team,
                session_id=session_id,
                summary={"content": f"Summary for {session_id} with auth context"},
                exception_event_ids=[],
                extra_summary_context=self.extra_context,
            )

        other_context: ExtraSummaryContext = ExtraSummaryContext(focus_area="checkout")
        SingleSessionSummary.objects.add_summary(
            team=self.team,
            session_id=self.session_ids[7],
            summary={"content": f"Summary for {self.session_ids[7]} with checkout context"},
            exception_event_ids=[],
            extra_summary_context=other_context,
        )

    def test_get_bulk_summaries_without_context(self) -> None:
        result: SessionSummaryPage = SingleSessionSummary.objects.get_bulk_summaries(
            team=self.team,
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
            team=self.team,
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
            team=self.team,
            session_ids=self.session_ids,
            extra_summary_context=None,
            limit=2,
            offset=0,
        )

        self.assertEqual(len(result_offset_0.results), 2)
        self.assertTrue(result_offset_0.has_next)

        result_offset_2: SessionSummaryPage = SingleSessionSummary.objects.get_bulk_summaries(
            team=self.team,
            session_ids=self.session_ids,
            extra_summary_context=None,
            limit=2,
            offset=2,
        )

        self.assertEqual(len(result_offset_2.results), 2)
        self.assertTrue(result_offset_2.has_next)

        result_offset_4: SessionSummaryPage = SingleSessionSummary.objects.get_bulk_summaries(
            team=self.team,
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

        SingleSessionSummary.objects.add_summary(
            team=self.team,
            session_id=session_id,
            summary={"content": "Older summary", "version": 1},
            exception_event_ids=[],
            extra_summary_context=None,
        )

        time.sleep(0.01)

        newer: SingleSessionSummary = SingleSessionSummary.objects.add_summary(
            team=self.team,
            session_id=session_id,
            summary={"content": "Newer summary", "version": 2},
            exception_event_ids=[],
            extra_summary_context=None,
        )

        result: SessionSummaryPage = SingleSessionSummary.objects.get_bulk_summaries(
            team=self.team,
            session_ids=[session_id],
            extra_summary_context=None,
        )

        self.assertEqual(len(result.results), 1)
        self.assertEqual(result.results[0].id, newer.id)
        self.assertEqual(result.results[0].summary["version"], 2)

    def test_get_bulk_summaries_team_isolation(self) -> None:
        other_team: Team = Organization.objects.bootstrap(None)[2]

        for session_id in self.session_ids[:3]:
            SingleSessionSummary.objects.add_summary(
                team=other_team,
                session_id=session_id,
                summary={"content": f"Other team summary for {session_id}"},
                exception_event_ids=[],
                extra_summary_context=None,
            )

        result: SessionSummaryPage = SingleSessionSummary.objects.get_bulk_summaries(
            team=self.team,
            session_ids=self.session_ids[:3],
            extra_summary_context=None,
        )

        self.assertEqual(len(result.results), 3)
        for summary in result.results:
            self.assertEqual(summary.team_id, self.team.id)

    def test_get_bulk_summaries_nonexistent_sessions(self) -> None:
        nonexistent_ids: list[str] = ["nonexistent-1", "nonexistent-2", "nonexistent-3"]

        result: SessionSummaryPage = SingleSessionSummary.objects.get_bulk_summaries(
            team=self.team,
            session_ids=nonexistent_ids,
            extra_summary_context=None,
        )

        self.assertEqual(len(result.results), 0)
        self.assertFalse(result.has_next)

    def test_get_bulk_summaries_mixed_sessions(self) -> None:
        mixed_ids: list[str] = [self.session_ids[0], "nonexistent", self.session_ids[1]]

        result: SessionSummaryPage = SingleSessionSummary.objects.get_bulk_summaries(
            team=self.team,
            session_ids=mixed_ids,
            extra_summary_context=None,
        )

        self.assertEqual(len(result.results), 2)
        result_session_ids: set[str] = {s.session_id for s in result.results}
        self.assertEqual(result_session_ids, {self.session_ids[0], self.session_ids[1]})

    def test_get_bulk_summaries_invalid_offset(self) -> None:
        result: SessionSummaryPage = SingleSessionSummary.objects.get_bulk_summaries(
            team=self.team,
            session_ids=self.session_ids,
            extra_summary_context=None,
            offset=999,
        )

        self.assertEqual(len(result.results), 0)
        self.assertFalse(result.has_next)

    def test_summaries_exist_single_without_context(self) -> None:
        # Test with non-existent session
        result: dict[str, bool] = SingleSessionSummary.objects.summaries_exist(
            team_id=self.team.id,
            session_ids=["non-existent"],
            extra_summary_context=None,
        )
        self.assertEqual(result, {"non-existent": False})
        # Add a summary and test again
        SingleSessionSummary.objects.add_summary(
            team_id=self.team.id,
            session_id="test-session-1",
            summary={"content": "test"},
            exception_event_ids=[],
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
        SingleSessionSummary.objects.add_summary(
            team_id=other_team.id,
            session_id="cross-team-session",
            summary={"content": "other team"},
            exception_event_ids=[],
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
        # The latest should have auth context
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
        # Should not match no context since latest has context
        result = SingleSessionSummary.objects.summaries_exist(
            team_id=self.team.id,
            session_ids=[self.session_ids[3], self.session_ids[4]],
            extra_summary_context=None,
        )
        self.assertEqual(
            result,
            {
                self.session_ids[3]: False,
                self.session_ids[4]: False,
            },
        )

    def test_summaries_exist_empty_list(self) -> None:
        result: dict[str, bool] = SingleSessionSummary.objects.summaries_exist(
            team_id=self.team.id,
            session_ids=[],
            extra_summary_context=None,
        )
        self.assertEqual(result, {})

    def test_summaries_exist_large_batch(self) -> None:
        # Create many sessions
        large_session_ids: list[str] = [f"large-batch-{i:04d}" for i in range(200)]
        # Add summaries for half of them
        for i in range(100):
            SingleSessionSummary.objects.add_summary(
                team_id=self.team.id,
                session_id=large_session_ids[i],
                summary={"content": f"Summary {i}"},
                exception_event_ids=[],
            )
        # Check all at once
        result: dict[str, bool] = SingleSessionSummary.objects.summaries_exist(
            team_id=self.team.id,
            session_ids=large_session_ids,
            extra_summary_context=None,
        )
        # First 100 should exist, last 100 should not
        for i in range(200):
            expected = i < 100
            self.assertEqual(result[large_session_ids[i]], expected, f"Session {i} existence check failed")
