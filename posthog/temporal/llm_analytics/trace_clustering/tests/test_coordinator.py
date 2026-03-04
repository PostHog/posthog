"""Tests for trace clustering coordinator workflow."""

import pytest

from posthog.temporal.llm_analytics.shared_activities import JobConfig, resolve_level_jobs_for_team
from posthog.temporal.llm_analytics.trace_clustering import constants
from posthog.temporal.llm_analytics.trace_clustering.coordinator import (
    TraceClusteringCoordinatorInputs,
    TraceClusteringCoordinatorWorkflow,
    _empty_clustering_results,
)


class TestTraceClusteringCoordinatorWorkflow:
    """Tests for TraceClusteringCoordinatorWorkflow."""

    @pytest.mark.parametrize(
        "inputs,expected",
        [
            pytest.param(
                [],
                TraceClusteringCoordinatorInputs(
                    analysis_level="trace",
                    lookback_days=constants.DEFAULT_LOOKBACK_DAYS,
                    max_samples=constants.DEFAULT_MAX_SAMPLES,
                    min_k=constants.DEFAULT_MIN_K,
                    max_k=constants.DEFAULT_MAX_K,
                    max_concurrent_teams=constants.DEFAULT_MAX_CONCURRENT_TEAMS,
                ),
                id="empty_inputs_uses_defaults",
            ),
            pytest.param(
                ["generation"],
                TraceClusteringCoordinatorInputs(
                    analysis_level="generation",
                    lookback_days=constants.DEFAULT_LOOKBACK_DAYS,
                    max_samples=constants.DEFAULT_MAX_SAMPLES,
                ),
                id="generation_level",
            ),
            pytest.param(
                ["trace", "14", "2000", "3", "15", "5"],
                TraceClusteringCoordinatorInputs(
                    analysis_level="trace",
                    lookback_days=14,
                    max_samples=2000,
                    min_k=3,
                    max_k=15,
                    max_concurrent_teams=5,
                ),
                id="full_inputs",
            ),
        ],
    )
    def test_parse_inputs(self, inputs, expected):
        result = TraceClusteringCoordinatorWorkflow.parse_inputs(inputs)

        assert result.analysis_level == expected.analysis_level
        assert result.lookback_days == expected.lookback_days
        assert result.max_samples == expected.max_samples

    def test_continuation_fields_default_to_none(self):
        inputs = TraceClusteringCoordinatorInputs()

        assert inputs.remaining_team_ids is None
        assert inputs.per_team_filters is None
        assert inputs.results_so_far is None

    def test_continuation_fields_can_be_set(self):
        inputs = TraceClusteringCoordinatorInputs(
            remaining_team_ids=[100, 200, 300],
            per_team_filters={"100": [{"event": "$ai_generation"}]},
            results_so_far={
                "teams_succeeded": 5,
                "teams_failed": 1,
                "failed_team_ids": [99],
                "total_items": 50,
                "total_clusters": 10,
            },
        )

        assert inputs.remaining_team_ids == [100, 200, 300]
        assert inputs.per_team_filters == {"100": [{"event": "$ai_generation"}]}
        assert inputs.results_so_far is not None
        assert inputs.results_so_far["teams_succeeded"] == 5

    def test_empty_clustering_results(self):
        results = _empty_clustering_results()

        assert results == {
            "teams_succeeded": 0,
            "teams_failed": 0,
            "failed_team_ids": [],
            "total_items": 0,
            "total_clusters": 0,
        }

    def test_empty_results_returns_independent_instances(self):
        r1 = _empty_clustering_results()
        r2 = _empty_clustering_results()
        r1["failed_team_ids"].append(123)

        assert r2["failed_team_ids"] == []

    @pytest.mark.parametrize(
        "team_jobs,analysis_level,legacy_event_filters,expected_job_ids",
        [
            pytest.param(
                [],
                "trace",
                [{"event": "$ai_generation"}],
                [0],
                id="falls_back_to_legacy_when_no_jobs_exist",
            ),
            pytest.param(
                [
                    JobConfig(job_id=11, name="trace-job", analysis_level="trace", event_filters=[]),
                    JobConfig(job_id=22, name="gen-job", analysis_level="generation", event_filters=[]),
                ],
                "trace",
                [{"event": "$ai_generation"}],
                [11],
                id="uses_matching_jobs_when_present",
            ),
            pytest.param(
                [JobConfig(job_id=33, name="gen-job", analysis_level="generation", event_filters=[])],
                "trace",
                [{"event": "$ai_generation"}],
                [],
                id="skips_when_only_other_level_jobs_exist",
            ),
        ],
    )
    def testresolve_level_jobs_for_team(self, team_jobs, analysis_level, legacy_event_filters, expected_job_ids):
        result = resolve_level_jobs_for_team(
            team_jobs=team_jobs,
            analysis_level=analysis_level,
            legacy_event_filters=legacy_event_filters,
        )

        assert [job.job_id for job in result] == expected_job_ids
