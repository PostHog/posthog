"""Unit tests for the evaluation sampler workflow window math and coordinator job filtering."""

from datetime import UTC, datetime, timedelta

from posthog.temporal.llm_analytics.evaluation_clustering.constants import (
    SAMPLER_MAX_SAMPLES_PER_JOB,
    SAMPLER_WINDOW_MINUTES,
    SAMPLER_WINDOW_OFFSET_MINUTES,
)
from posthog.temporal.llm_analytics.evaluation_clustering.coordinator import _evaluation_jobs_for_team
from posthog.temporal.llm_analytics.shared_activities import JobConfig


class TestEvaluationJobsForTeam:
    def test_picks_only_evaluation_level_jobs(self):
        jobs = [
            JobConfig(job_id="j1", name="Trace", analysis_level="trace", event_filters=[]),
            JobConfig(job_id="j2", name="Gen", analysis_level="generation", event_filters=[]),
            JobConfig(job_id="j3", name="Eval", analysis_level="evaluation", event_filters=[]),
            JobConfig(job_id="j4", name="Eval2", analysis_level="evaluation", event_filters=[{"key": "x"}]),
        ]
        result = _evaluation_jobs_for_team(jobs)
        assert [j.job_id for j in result] == ["j3", "j4"]

    def test_no_evaluation_jobs_returns_empty(self):
        jobs = [
            JobConfig(job_id="j1", name="Trace", analysis_level="trace", event_filters=[]),
        ]
        assert _evaluation_jobs_for_team(jobs) == []

    def test_empty_input_returns_empty(self):
        assert _evaluation_jobs_for_team([]) == []


class TestWindowMath:
    """Sampler workflow derives window from workflow.now(); verify it independently.

    The workflow code does:
        window_end   = now - OFFSET
        window_start = window_end - WINDOW
    """

    def test_window_matches_spec(self):
        now = datetime(2026, 4, 15, 12, 0, 0, tzinfo=UTC)
        expected_end = now - timedelta(minutes=SAMPLER_WINDOW_OFFSET_MINUTES)
        expected_start = expected_end - timedelta(minutes=SAMPLER_WINDOW_MINUTES)

        # Window is 1h, offset is 30min — so [11:30 - 30, 11:30)
        assert expected_end == datetime(2026, 4, 15, 11, 30, 0, tzinfo=UTC)
        assert expected_start == datetime(2026, 4, 15, 10, 30, 0, tzinfo=UTC)

    def test_sample_cap_is_250(self):
        # Locked in the spec — warn loudly if someone changes this without updating Stage B's
        # assumptions about daily accumulation volume.
        assert SAMPLER_MAX_SAMPLES_PER_JOB == 250
