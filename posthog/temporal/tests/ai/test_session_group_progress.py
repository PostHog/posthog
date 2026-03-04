import json

import pytest

from posthog.temporal.ai.session_summary.summarize_session_group import SummarizeSessionGroupWorkflow
from posthog.temporal.ai.session_summary.types.group import SessionSummaryStreamUpdate, WorkflowProgress


class TestSessionSummaryStreamUpdateEnum:
    def test_session_progress_value(self):
        assert SessionSummaryStreamUpdate.SESSION_PROGRESS.value == "session_progress"

    def test_all_variants_present(self):
        members = {m.name for m in SessionSummaryStreamUpdate}
        assert members == {"UI_STATUS", "FINAL_RESULT", "SESSION_PROGRESS"}


class TestWorkflowProgress:
    def test_construction(self):
        progress = WorkflowProgress(
            session_statuses={"s1": "queued", "s2": "summarizing"},
            phase="watching_sessions",
            total_sessions=2,
            patterns_found=[],
        )
        assert progress["session_statuses"] == {"s1": "queued", "s2": "summarizing"}
        assert progress["phase"] == "watching_sessions"
        assert progress["total_sessions"] == 2
        assert progress["patterns_found"] == []

    def test_is_dict_like(self):
        progress = WorkflowProgress(
            session_statuses={},
            phase="fetching_data",
            total_sessions=0,
            patterns_found=["Pattern A"],
        )
        assert isinstance(progress, dict)
        assert set(progress.keys()) == {"session_statuses", "phase", "total_sessions", "patterns_found"}

    def test_json_serializable(self):
        progress = WorkflowProgress(
            session_statuses={"s1": "summarized", "s2": "failed"},
            phase="extracting_patterns",
            total_sessions=2,
            patterns_found=["Navigation confusion"],
        )
        serialized = json.dumps(progress)
        deserialized = json.loads(serialized)
        assert deserialized == progress


class TestWorkflowProgressTracking:
    """Test the progress tracking attributes on the workflow class.

    These tests instantiate the workflow class directly (outside Temporal) to verify
    the internal state management logic for session statuses and phase tracking.
    """

    def test_initial_state(self):
        workflow = SummarizeSessionGroupWorkflow()
        assert workflow._session_statuses == {}
        assert workflow._current_phase == "fetching_data"
        assert workflow._total_sessions == 0

    def test_get_progress_returns_workflow_progress(self):
        workflow = SummarizeSessionGroupWorkflow()
        workflow._session_statuses = {"s1": "queued", "s2": "summarizing"}
        workflow._current_phase = "watching_sessions"
        workflow._total_sessions = 2

        progress = workflow.get_progress()

        assert progress["session_statuses"] == {"s1": "queued", "s2": "summarizing"}
        assert progress["phase"] == "watching_sessions"
        assert progress["total_sessions"] == 2
        assert progress["patterns_found"] == []

    def test_get_progress_returns_copy_of_statuses(self):
        workflow = SummarizeSessionGroupWorkflow()
        workflow._session_statuses = {"s1": "queued"}

        progress = workflow.get_progress()
        progress["session_statuses"]["s1"] = "modified"

        assert workflow._session_statuses["s1"] == "queued"

    @pytest.mark.parametrize(
        "status_transitions,expected_final",
        [
            (
                [("s1", "queued"), ("s1", "summarizing"), ("s1", "summarized")],
                {"s1": "summarized"},
            ),
            (
                [("s1", "queued"), ("s1", "summarizing"), ("s1", "failed")],
                {"s1": "failed"},
            ),
            (
                [("s1", "queued"), ("s2", "queued"), ("s1", "summarizing"), ("s2", "skipped")],
                {"s1": "summarizing", "s2": "skipped"},
            ),
        ],
    )
    def test_session_status_transitions(
        self,
        status_transitions: list[tuple[str, str]],
        expected_final: dict[str, str],
    ):
        workflow = SummarizeSessionGroupWorkflow()
        for session_id, status in status_transitions:
            workflow._session_statuses[session_id] = status

        assert workflow._session_statuses == expected_final

    @pytest.mark.parametrize(
        "phases",
        [
            ["fetching_data", "watching_sessions", "extracting_patterns", "assigning_patterns"],
            ["fetching_data", "watching_sessions"],
        ],
    )
    def test_phase_progression(self, phases: list[str]):
        workflow = SummarizeSessionGroupWorkflow()
        for phase in phases:
            workflow._current_phase = phase

        assert workflow._current_phase == phases[-1]
