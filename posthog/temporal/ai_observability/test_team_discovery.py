from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import partial

import pytest
from unittest.mock import AsyncMock, MagicMock, call, patch

from django.db import InterfaceError, OperationalError

from parameterized import parameterized

from posthog.dataclasses import frozen
from posthog.sync import database_sync_to_async
from posthog.temporal.ai_observability.evaluation_clustering.coordinator import (
    AIObservabilityEvaluationClusteringCoordinatorWorkflow,
    AIObservabilityEvaluationSamplerCoordinatorWorkflow,
    ClusteringCoordinatorInputs,
    SamplerCoordinatorInputs,
)
from posthog.temporal.ai_observability.team_discovery import (
    DEFAULT_DISCOVERY_LOOKBACK_DAYS,
    DEFAULT_GUARANTEED_TEAM_IDS,
    DEFAULT_SAMPLE_PERCENTAGE,
    TeamDiscoveryInput,
    _get_ai_observability_workflow_config,
    get_min_traces_override,
    get_team_ids_for_ai_observability,
)
from posthog.temporal.ai_observability.trace_clustering.coordinator import (
    TraceClusteringCoordinatorInputs,
    TraceClusteringCoordinatorWorkflow,
)
from posthog.temporal.ai_observability.trace_summarization.coordinator import (
    BatchTraceSummarizationCoordinatorInputs,
    BatchTraceSummarizationCoordinatorWorkflow,
)


@asynccontextmanager
async def _noop_heartbeater(*args, **kwargs):
    yield


FF_PAYLOAD_PATH = "posthog.temporal.ai_observability.team_discovery.posthoganalytics.get_feature_flag_payload"
CONSENT_QUERY_PATH = "posthog.temporal.ai_observability.team_discovery.consented_team_ids"


class TestGetLlmaWorkflowConfig:
    @parameterized.expand(
        [
            ("none_payload", None),
            ("string_payload", "not a dict"),
            ("list_payload", [1, 2, 3]),
            ("int_payload", 42),
        ]
    )
    @patch(FF_PAYLOAD_PATH)
    def test_non_dict_payload_returns_defaults(self, _name, payload, mock_ff):
        mock_ff.return_value = payload

        config = _get_ai_observability_workflow_config()

        assert config.guaranteed_team_ids == DEFAULT_GUARANTEED_TEAM_IDS
        assert config.skip_team_ids == []
        assert config.sample_percentage == DEFAULT_SAMPLE_PERCENTAGE
        assert config.discovery_lookback_days == DEFAULT_DISCOVERY_LOOKBACK_DAYS

    @patch(FF_PAYLOAD_PATH)
    def test_valid_payload(self, mock_ff):
        mock_ff.return_value = {
            "guaranteed_team_ids": [100, 200],
            "skip_team_ids": [300, 400],
            "sample_percentage": 0.5,
            "discovery_lookback_days": 14,
        }

        config = _get_ai_observability_workflow_config()

        assert config.guaranteed_team_ids == [100, 200]
        assert config.skip_team_ids == [300, 400]
        assert config.sample_percentage == 0.5
        assert config.discovery_lookback_days == 14

    @patch(FF_PAYLOAD_PATH)
    def test_partial_payload_fills_missing_with_defaults(self, mock_ff):
        mock_ff.return_value = {"guaranteed_team_ids": [42]}

        config = _get_ai_observability_workflow_config()

        assert config.guaranteed_team_ids == [42]
        assert config.skip_team_ids == []
        assert config.sample_percentage == DEFAULT_SAMPLE_PERCENTAGE
        assert config.discovery_lookback_days == DEFAULT_DISCOVERY_LOOKBACK_DAYS

    @parameterized.expand(
        [
            ("string_ids", {"guaranteed_team_ids": "not a list"}, "guaranteed_team_ids"),
            ("mixed_ids", {"guaranteed_team_ids": [1, "two", 3]}, "guaranteed_team_ids"),
            ("string_skip", {"skip_team_ids": "not a list"}, "skip_team_ids"),
            ("mixed_skip", {"skip_team_ids": [1, "two", 3]}, "skip_team_ids"),
            ("string_pct", {"sample_percentage": "high"}, "sample_percentage"),
            ("negative_pct", {"sample_percentage": -0.1}, "sample_percentage"),
            ("pct_above_one", {"sample_percentage": 1.5}, "sample_percentage"),
            ("nan_pct", {"sample_percentage": float("nan")}, "sample_percentage"),
            ("inf_pct", {"sample_percentage": float("inf")}, "sample_percentage"),
            ("string_lookback", {"discovery_lookback_days": "30"}, "discovery_lookback_days"),
            ("float_lookback", {"discovery_lookback_days": 3.5}, "discovery_lookback_days"),
            ("zero_lookback", {"discovery_lookback_days": 0}, "discovery_lookback_days"),
            ("negative_lookback", {"discovery_lookback_days": -5}, "discovery_lookback_days"),
            ("bool_lookback", {"discovery_lookback_days": True}, "discovery_lookback_days"),
        ]
    )
    @patch(FF_PAYLOAD_PATH)
    def test_invalid_field_types_fall_back_per_field(self, _name, payload, bad_field, mock_ff):
        mock_ff.return_value = payload

        config = _get_ai_observability_workflow_config()

        if bad_field == "guaranteed_team_ids":
            assert config.guaranteed_team_ids == DEFAULT_GUARANTEED_TEAM_IDS
        if bad_field == "skip_team_ids":
            assert config.skip_team_ids == []
        if bad_field == "sample_percentage":
            assert config.sample_percentage == DEFAULT_SAMPLE_PERCENTAGE
        if bad_field == "discovery_lookback_days":
            assert config.discovery_lookback_days == DEFAULT_DISCOVERY_LOOKBACK_DAYS

    @patch(FF_PAYLOAD_PATH)
    def test_exception_returns_defaults(self, mock_ff):
        mock_ff.side_effect = Exception("network error")

        config = _get_ai_observability_workflow_config()

        assert config.guaranteed_team_ids == DEFAULT_GUARANTEED_TEAM_IDS
        assert config.skip_team_ids == []
        assert config.sample_percentage == DEFAULT_SAMPLE_PERCENTAGE

    @patch(FF_PAYLOAD_PATH)
    def test_int_sample_percentage_cast_to_float(self, mock_ff):
        mock_ff.return_value = {"sample_percentage": 1}

        config = _get_ai_observability_workflow_config()

        assert config.sample_percentage == 1.0
        assert isinstance(config.sample_percentage, float)


class TestGetMinTracesOverride:
    @parameterized.expand(
        [
            ("no_payload", None, None),
            ("non_dict_payload", "nope", None),
            ("no_overrides_key", {"guaranteed_team_ids": [1]}, None),
            ("overrides_not_dict", {"min_traces_overrides": [1, 2]}, None),
            ("team_present", {"min_traces_overrides": {"370629": 20}}, 20),
            ("team_absent", {"min_traces_overrides": {"111": 20}}, None),
            ("zero_value", {"min_traces_overrides": {"370629": 0}}, None),
            ("negative_value", {"min_traces_overrides": {"370629": -5}}, None),
            ("bool_value", {"min_traces_overrides": {"370629": True}}, None),
            ("string_value", {"min_traces_overrides": {"370629": "20"}}, None),
        ]
    )
    @patch(FF_PAYLOAD_PATH)
    def test_override_resolution(self, _name, payload, expected, mock_ff):
        mock_ff.return_value = payload

        assert get_min_traces_override(370629) == expected

    @patch(FF_PAYLOAD_PATH)
    def test_exception_returns_none(self, mock_ff):
        mock_ff.side_effect = Exception("network error")

        assert get_min_traces_override(370629) is None


@patch("posthog.temporal.ai_observability.team_discovery.Heartbeater", _noop_heartbeater)
@pytest.mark.asyncio
class TestGetTeamIdsForAIObservability:
    @pytest.mark.django_db(transaction=True)
    @patch(FF_PAYLOAD_PATH)
    async def test_only_opted_in_consented_projects_are_discovered(self, mock_ff: MagicMock) -> None:
        @frozen
        class Projects:
            off: int
            on: int
            no_consent: int

        def create_projects() -> Projects:
            from posthog.models import Organization, Team

            from products.ai_observability.backend.models.clustering_config import ClusteringConfig

            approved = Organization.objects.create(name="Approved", is_ai_data_processing_approved=True)
            unapproved = Organization.objects.create(name="Unapproved", is_ai_data_processing_approved=False)
            off = Team.objects.create(organization=approved)
            on = Team.objects.create(organization=approved)
            no_consent = Team.objects.create(organization=unapproved)
            ClusteringConfig.objects.create(team=on, enabled=True)
            ClusteringConfig.objects.create(team=no_consent, enabled=True)
            return Projects(off=off.id, on=on.id, no_consent=no_consent.id)

        projects = await database_sync_to_async(create_projects)()
        mock_ff.return_value = {"guaranteed_team_ids": [projects.off, projects.no_consent], "sample_percentage": 0}
        assert await get_team_ids_for_ai_observability(TeamDiscoveryInput()) == [projects.on]

        mock_ff.return_value = {"skip_team_ids": [projects.on]}
        assert await get_team_ids_for_ai_observability(TeamDiscoveryInput()) == []

    @patch(FF_PAYLOAD_PATH, return_value=None)
    @patch("posthog.temporal.ai_observability.team_discovery.enabled_clustering_team_ids")
    async def test_no_opt_in_means_no_teams_even_with_default_allowlist(
        self, enabled: MagicMock, _ff: MagicMock
    ) -> None:
        enabled.return_value = set()
        with patch(CONSENT_QUERY_PATH, return_value=set()):
            assert await get_team_ids_for_ai_observability(TeamDiscoveryInput()) == []

    @pytest.mark.parametrize(
        "query_results,expected,attempts",
        [
            ([OperationalError("Postgres unavailable"), {1}], [1], 2),
            ([InterfaceError("Connection closed"), {1}], [1], 2),
            ([OperationalError("Postgres unavailable")] * 3, [], 3),
            ([RuntimeError("Unexpected query failure")], [], 1),
            ([set()], [], 1),
        ],
    )
    @patch(FF_PAYLOAD_PATH, return_value=None)
    @patch("posthog.temporal.ai_observability.team_discovery.enabled_clustering_team_ids", return_value={1})
    @patch(CONSENT_QUERY_PATH)
    async def test_consent_query_retries_fail_closed(
        self,
        query: MagicMock,
        _enabled: MagicMock,
        _ff: MagicMock,
        query_results: list[Exception | set[int]],
        expected: list[int],
        attempts: int,
    ) -> None:
        query.side_effect = query_results
        with (
            patch("asyncio.sleep", new_callable=AsyncMock) as sleep,
            patch("posthog.temporal.ai_observability.coordinator_metrics.get_metric_meter"),
        ):
            assert await get_team_ids_for_ai_observability(TeamDiscoveryInput()) == expected
        assert query.call_args_list == [call([1])] * attempts
        assert sleep.await_count == attempts - 1

    @patch(FF_PAYLOAD_PATH, return_value=None)
    @patch(
        "posthog.temporal.ai_observability.team_discovery.enabled_clustering_team_ids",
        side_effect=OperationalError("Unavailable"),
    )
    async def test_opt_in_query_failure_does_not_fall_back_to_allowlist(
        self, _enabled: MagicMock, _ff: MagicMock
    ) -> None:
        with patch("posthog.temporal.ai_observability.coordinator_metrics.get_metric_meter"):
            assert await get_team_ids_for_ai_observability(TeamDiscoveryInput()) == []


class TestCoordinatorConsentGate:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "run",
        [
            pytest.param(
                partial(BatchTraceSummarizationCoordinatorWorkflow().run, BatchTraceSummarizationCoordinatorInputs()),
                id="summarization",
            ),
            pytest.param(
                partial(TraceClusteringCoordinatorWorkflow().run, TraceClusteringCoordinatorInputs()),
                id="trace_clustering",
            ),
            pytest.param(
                partial(AIObservabilityEvaluationSamplerCoordinatorWorkflow().run, SamplerCoordinatorInputs()),
                id="evaluation_sampling",
            ),
            pytest.param(
                partial(AIObservabilityEvaluationClusteringCoordinatorWorkflow().run, ClusteringCoordinatorInputs()),
                id="evaluation_clustering",
            ),
        ],
    )
    async def test_discovery_failure_does_not_start_team_workflows(self, run: Callable[[], Awaitable[object]]) -> None:
        with (
            patch("temporalio.workflow.patched", return_value=True),
            patch(
                "temporalio.workflow.info", return_value=MagicMock(workflow_start_time=datetime(2026, 1, 1, tzinfo=UTC))
            ),
            patch("temporalio.workflow.execute_activity", side_effect=RuntimeError("Discovery unavailable")),
            patch("temporalio.workflow.start_child_workflow") as start_child,
        ):
            with pytest.raises(RuntimeError, match="Discovery unavailable"):
                await run()

        start_child.assert_not_called()
