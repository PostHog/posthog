from dataclasses import asdict
from typing import Any

from posthog.test.base import BaseTest

from posthog.models import Organization, Team, User

from ee.hogai.session_summaries.session.output_data import SessionSummarySerializer
from ee.hogai.session_summaries.tests.conftest import get_mock_enriched_llm_json_response
from ee.models.session_summaries import (
    ExtraSummaryContext,
    SessionGroupSummary,
    SessionSummaryPage,
    SessionSummaryRunMeta,
    SingleSessionSummary,
)
import pytest


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
        self.summary_data = get_mock_enriched_llm_json_response(self.session_id)
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

        assert summary is not None
        assert summary is not None
        assert summary.session_id == self.session_id
        assert "segments" in summary.summary
        assert "key_actions" in summary.summary
        assert "segment_outcomes" in summary.summary
        assert "session_outcome" in summary.summary
        assert summary.exception_event_ids == self.exception_event_ids
        assert summary.extra_summary_context == {"focus_area": "authentication"}
        assert summary.run_metadata == {"model_used": "gpt-4", "visual_confirmation": False, "visual_confirmation_results": None}
        assert summary.created_by == self.user
        assert summary.team_id == self.team.id

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
        assert retrieved.extra_summary_context == {"focus_area": "authentication"}

        # Get the latest one (which has no context)
        retrieved_any: SingleSessionSummary | None = SingleSessionSummary.objects.get_summary(
            team_id=self.team.id, session_id=self.session_id
        )
        assert retrieved_any is not None
        assert retrieved_any.extra_summary_context is None

    def test_get_summary_nonexistent(self) -> None:
        result: SingleSessionSummary | None = SingleSessionSummary.objects.get_summary(
            team_id=self.team.id, session_id="non-existent-session"
        )
        assert result is None

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
        assert len(summary.exception_event_ids) == 100
        assert summary.exception_event_ids[0] == "evt-000"
        assert summary.exception_event_ids[99] == "evt-099"

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
        assert result is None

    def test_multiple_summaries_ordering(self) -> None:
        summary_data_1 = get_mock_enriched_llm_json_response(self.session_id)
        summary_data_1["session_outcome"]["description"] = "Version 1"
        summary_serializer_1 = SessionSummarySerializer(data=summary_data_1)
        summary_serializer_1.is_valid(raise_exception=True)
        SingleSessionSummary.objects.add_summary(
            team_id=self.team.id,
            session_id=self.session_id,
            summary=summary_serializer_1,
            exception_event_ids=[],
            created_by=self.user,
        )

        summary_data_2 = get_mock_enriched_llm_json_response(self.session_id)
        summary_data_2["session_outcome"]["description"] = "Version 2"
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
        assert retrieved.summary["session_outcome"]["description"] == "Version 2"


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

        def create_summary_data(session_id: str, content: str) -> dict[str, Any]:
            data = get_mock_enriched_llm_json_response(session_id)
            data["session_outcome"]["description"] = content
            return data

        for session_id in self.session_ids[:3]:
            summary_data = create_summary_data(session_id, f"Summary for {session_id} without context")
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
            summary_data_1 = create_summary_data(session_id, f"Summary for {session_id} without context - older")
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
            summary_data_2 = create_summary_data(session_id, f"Summary for {session_id} with auth context - newer")
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
            summary_data = create_summary_data(session_id, f"Summary for {session_id} with auth context")
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
        summary_data = create_summary_data(
            self.session_ids[7], f"Summary for {self.session_ids[7]} with checkout context"
        )
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

        assert len(result.results) == 5

        result_session_ids: set[str] = {s.session_id for s in result.results}
        expected_session_ids: set[str] = {self.session_ids[i] for i in [0, 1, 2, 3, 4]}
        assert result_session_ids == expected_session_ids

        for summary in result.results:
            assert summary.extra_summary_context is None

    def test_get_bulk_summaries_with_context(self) -> None:
        result: SessionSummaryPage = SingleSessionSummary.objects.get_bulk_summaries(
            team_id=self.team.id,
            session_ids=self.session_ids,
            extra_summary_context=self.extra_context,
        )

        assert len(result.results) == 4

        result_session_ids: set[str] = {s.session_id for s in result.results}
        expected_session_ids: set[str] = {self.session_ids[i] for i in [3, 4, 5, 6]}
        assert result_session_ids == expected_session_ids

        for summary in result.results:
            assert summary.extra_summary_context == {"focus_area": "authentication"}

    def test_get_bulk_summaries_pagination(self) -> None:
        result_offset_0: SessionSummaryPage = SingleSessionSummary.objects.get_bulk_summaries(
            team_id=self.team.id,
            session_ids=self.session_ids,
            extra_summary_context=None,
            limit=2,
            offset=0,
        )

        assert len(result_offset_0.results) == 2
        assert result_offset_0.has_next

        result_offset_2: SessionSummaryPage = SingleSessionSummary.objects.get_bulk_summaries(
            team_id=self.team.id,
            session_ids=self.session_ids,
            extra_summary_context=None,
            limit=2,
            offset=2,
        )

        assert len(result_offset_2.results) == 2
        assert result_offset_2.has_next

        result_offset_4: SessionSummaryPage = SingleSessionSummary.objects.get_bulk_summaries(
            team_id=self.team.id,
            session_ids=self.session_ids,
            extra_summary_context=None,
            limit=2,
            offset=4,
        )

        assert len(result_offset_4.results) == 1
        assert not result_offset_4.has_next

        offset_0_ids: set[str] = {s.session_id for s in result_offset_0.results}
        offset_2_ids: set[str] = {s.session_id for s in result_offset_2.results}
        offset_4_ids: set[str] = {s.session_id for s in result_offset_4.results}
        assert len(offset_0_ids & offset_2_ids) == 0
        assert len(offset_2_ids & offset_4_ids) == 0
        assert len(offset_0_ids & offset_4_ids) == 0

    def test_get_bulk_summaries_latest_per_session(self) -> None:
        session_id: str = "session-latest-test"
        summary_data_1 = get_mock_enriched_llm_json_response(session_id)
        summary_data_1["session_outcome"]["description"] = "Older summary - version 1"
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
        summary_data_2 = get_mock_enriched_llm_json_response(session_id)
        summary_data_2["session_outcome"]["description"] = "Newer summary - version 2"
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
        assert len(result.results) == 1
        # Should get the latest one (version 2)
        assert result.results[0].summary["session_outcome"]["description"] == "Newer summary - version 2"

    def test_get_bulk_summaries_mixed_sessions(self) -> None:
        mixed_ids: list[str] = [self.session_ids[0], "nonexistent", self.session_ids[1]]

        result: SessionSummaryPage = SingleSessionSummary.objects.get_bulk_summaries(
            team_id=self.team.id,
            session_ids=mixed_ids,
            extra_summary_context=None,
        )

        assert len(result.results) == 2
        result_session_ids: set[str] = {s.session_id for s in result.results}
        assert result_session_ids == {self.session_ids[0], self.session_ids[1]}

    def test_summaries_exist_multiple_without_context(self) -> None:
        # Use existing test data - sessions 0-4 have summaries without context
        result: dict[str, bool] = SingleSessionSummary.objects.summaries_exist(
            team_id=self.team.id,
            session_ids=[self.session_ids[0], self.session_ids[1], self.session_ids[8], "non-existent"],
            extra_summary_context=None,
        )
        assert result == {
                self.session_ids[0]: True,
                self.session_ids[1]: True,
                self.session_ids[8]: False,  # Has no summary
                "non-existent": False,
            }

    def test_summaries_exist_with_context(self) -> None:
        # Use existing test data - sessions 3-6 have summaries with auth context
        result: dict[str, bool] = SingleSessionSummary.objects.summaries_exist(
            team_id=self.team.id,
            session_ids=[self.session_ids[3], self.session_ids[5], self.session_ids[0], self.session_ids[9]],
            extra_summary_context=self.extra_context,
        )
        assert result == {
                self.session_ids[3]: True,  # Has auth context
                self.session_ids[5]: True,  # Has auth context
                self.session_ids[0]: False,  # Has no context
                self.session_ids[9]: False,  # Has no summary
            }

    def test_summaries_exist_context_mismatch(self) -> None:
        different_context: ExtraSummaryContext = ExtraSummaryContext(focus_area="checkout")
        # Session 7 has checkout context (from _setup_test_data)
        result: dict[str, bool] = SingleSessionSummary.objects.summaries_exist(
            team_id=self.team.id,
            session_ids=[self.session_ids[7]],
            extra_summary_context=different_context,
        )
        assert result == {self.session_ids[7]: True}
        # But not auth context
        result = SingleSessionSummary.objects.summaries_exist(
            team_id=self.team.id,
            session_ids=[self.session_ids[7]],
            extra_summary_context=self.extra_context,
        )
        assert result == {self.session_ids[7]: False}

    def test_summaries_exist_team_isolation(self) -> None:
        other_team: Team = Organization.objects.bootstrap(None)[2]
        # Add summary for other team
        summary_data = get_mock_enriched_llm_json_response("cross-team-session")
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
        assert result == {"cross-team-session": False}
        # Should be visible from the other team
        result = SingleSessionSummary.objects.summaries_exist(
            team_id=other_team.id,
            session_ids=["cross-team-session"],
            extra_summary_context=None,
        )
        assert result == {"cross-team-session": True}

    def test_summaries_exist_latest_only(self) -> None:
        # Sessions 3-4 have both old (no context) and new (auth context) summaries
        # Test with auth context - should find the latest summaries
        result: dict[str, bool] = SingleSessionSummary.objects.summaries_exist(
            team_id=self.team.id,
            session_ids=[self.session_ids[3], self.session_ids[4]],
            extra_summary_context=self.extra_context,
        )
        assert result == {self.session_ids[3]: True, self.session_ids[4]: True}
        # Test without context - the method returns the latest summary matching the filter
        # Since there are old summaries without context, it will return True
        result = SingleSessionSummary.objects.summaries_exist(
            team_id=self.team.id,
            session_ids=[self.session_ids[3], self.session_ids[4]],
            extra_summary_context=None,
        )
        assert result == {
                self.session_ids[3]: True,  # Has old summaries without context
                self.session_ids[4]: True,  # Has old summaries without context
            }


class TestSessionGroupSummary(BaseTest):
    session_ids: list[str]
    summary_data: dict[str, Any]
    extra_context: ExtraSummaryContext
    run_metadata: SessionSummaryRunMeta
    team: Team
    user: User

    def setUp(self) -> None:
        super().setUp()
        self.session_ids = ["session-001", "session-002", "session-003"]
        # Create a minimal valid group summary data (EnrichedSessionGroupSummaryPatternsList format)
        self.summary_data = {
            "patterns": [
                {
                    "pattern_id": 1,
                    "pattern_name": "Checkout abandonment",
                    "pattern_description": "Users abandon cart at payment step",
                    "severity": "high",
                    "indicators": ["Payment form loaded", "No submission", "User navigated away"],
                    "events": [],
                    "stats": {
                        "occurences": 5,
                        "sessions_affected": 3,
                        "sessions_affected_ratio": 0.6,
                        "segments_success_ratio": 0.2,
                    },
                }
            ]
        }
        self.extra_context = ExtraSummaryContext(focus_area="checkout flow")
        self.run_metadata = SessionSummaryRunMeta(model_used="claude-7-1-sonnet", visual_confirmation=False)

    def test_create_group_summary(self) -> None:
        summary = SessionGroupSummary.objects.create(
            team_id=self.team.id,
            title="Checkout flow analysis",
            session_ids=self.session_ids,
            summary=self.summary_data,
            extra_summary_context=asdict(self.extra_context),
            run_metadata=asdict(self.run_metadata),
            created_by=self.user,
        )
        assert summary.id is not None
        assert summary.team_id == self.team.id
        assert summary.title == "Checkout flow analysis"
        assert summary.session_ids == self.session_ids
        assert summary.summary == self.summary_data
        assert summary.extra_summary_context == asdict(self.extra_context)
        assert summary.run_metadata == asdict(self.run_metadata)
        assert summary.created_by == self.user

    def test_team_isolation(self) -> None:
        other_team: Team = Organization.objects.bootstrap(None)[2]
        summary = SessionGroupSummary.objects.create(
            team_id=self.team.id,
            title="Team isolation test",
            session_ids=self.session_ids,
            summary=self.summary_data,
            created_by=self.user,
        )
        # Should not be able to get summary with wrong team_id
        with pytest.raises(SessionGroupSummary.DoesNotExist):
            SessionGroupSummary.objects.get(id=summary.id, team_id=other_team.id)

    def test_order_by_created_at(self) -> None:
        # Create multiple summaries
        summary_1 = SessionGroupSummary.objects.create(
            team_id=self.team.id,
            title="Summary 1",
            session_ids=["session-1"],
            summary=self.summary_data,
        )
        summary_2 = SessionGroupSummary.objects.create(
            team_id=self.team.id,
            title="Summary 2",
            session_ids=["session-2"],
            summary=self.summary_data,
        )
        summary_3 = SessionGroupSummary.objects.create(
            team_id=self.team.id,
            title="Summary 3",
            session_ids=["session-3"],
            summary=self.summary_data,
        )
        # Get recent summaries ordered by creation date
        recent_summaries = list(SessionGroupSummary.objects.filter(team_id=self.team.id).order_by("-created_at"))
        assert len(recent_summaries) == 3
        assert recent_summaries[0].id == summary_3.id  # Most recent
        assert recent_summaries[1].id == summary_2.id
        assert recent_summaries[2].id == summary_1.id  # Oldest

    def test_update_summary(self) -> None:
        summary = SessionGroupSummary.objects.create(
            team_id=self.team.id,
            title="Update test summary",
            session_ids=self.session_ids,
            summary=self.summary_data,
        )
        # Update the summary data
        updated_data = {
            "patterns": [
                {
                    "pattern_id": 2,
                    "pattern_name": "Updated pattern",
                    "pattern_description": "Updated description",
                    "severity": "critical",
                    "indicators": ["New indicator"],
                    "events": [],
                    "stats": {
                        "occurences": 10,
                        "sessions_affected": 5,
                        "sessions_affected_ratio": 0.8,
                        "segments_success_ratio": 0.1,
                    },
                }
            ]
        }
        summary.summary = updated_data
        summary.save()
        # Verify the update
        retrieved = SessionGroupSummary.objects.get(id=summary.id)
        assert retrieved.summary == updated_data

    def test_str_representation(self) -> None:
        summary = SessionGroupSummary.objects.create(
            team_id=self.team.id,
            title="String repr test",
            session_ids=self.session_ids,
            summary=self.summary_data,
        )
        str_repr = str(summary)
        assert "String repr test" in str_repr
        assert "3 sessions" in str_repr
        assert str(self.team.id) in str_repr
