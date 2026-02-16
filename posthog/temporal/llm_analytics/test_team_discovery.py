import math
from contextlib import asynccontextmanager

import pytest
from unittest.mock import patch

from parameterized import parameterized

from posthog.temporal.llm_analytics.team_discovery import (
    DEFAULT_DISCOVERY_LOOKBACK_DAYS,
    DEFAULT_GUARANTEED_TEAM_IDS,
    DEFAULT_SAMPLE_PERCENTAGE,
    TeamDiscoveryInput,
    _get_llma_workflow_config,
    get_team_ids_for_llm_analytics,
)


@asynccontextmanager
async def _noop_heartbeater(*args, **kwargs):
    yield


FF_PAYLOAD_PATH = "posthog.temporal.llm_analytics.team_discovery.posthoganalytics.get_feature_flag_payload"


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

        config = _get_llma_workflow_config()

        assert config.guaranteed_team_ids == DEFAULT_GUARANTEED_TEAM_IDS
        assert config.sample_percentage == DEFAULT_SAMPLE_PERCENTAGE
        assert config.discovery_lookback_days == DEFAULT_DISCOVERY_LOOKBACK_DAYS

    @patch(FF_PAYLOAD_PATH)
    def test_valid_payload(self, mock_ff):
        mock_ff.return_value = {
            "guaranteed_team_ids": [100, 200],
            "sample_percentage": 0.5,
            "discovery_lookback_days": 7,
        }

        config = _get_llma_workflow_config()

        assert config.guaranteed_team_ids == [100, 200]
        assert config.sample_percentage == 0.5
        assert config.discovery_lookback_days == 7

    @patch(FF_PAYLOAD_PATH)
    def test_partial_payload_fills_missing_with_defaults(self, mock_ff):
        mock_ff.return_value = {"guaranteed_team_ids": [42]}

        config = _get_llma_workflow_config()

        assert config.guaranteed_team_ids == [42]
        assert config.sample_percentage == DEFAULT_SAMPLE_PERCENTAGE
        assert config.discovery_lookback_days == DEFAULT_DISCOVERY_LOOKBACK_DAYS

    @parameterized.expand(
        [
            ("string_ids", {"guaranteed_team_ids": "not a list"}, "guaranteed_team_ids"),
            ("mixed_ids", {"guaranteed_team_ids": [1, "two", 3]}, "guaranteed_team_ids"),
            ("string_pct", {"sample_percentage": "high"}, "sample_percentage"),
            ("negative_pct", {"sample_percentage": -0.1}, "sample_percentage"),
            ("pct_above_one", {"sample_percentage": 1.5}, "sample_percentage"),
            ("nan_pct", {"sample_percentage": float("nan")}, "sample_percentage"),
            ("inf_pct", {"sample_percentage": float("inf")}, "sample_percentage"),
            ("float_lookback", {"discovery_lookback_days": 7.5}, "discovery_lookback_days"),
            ("zero_lookback", {"discovery_lookback_days": 0}, "discovery_lookback_days"),
            ("negative_lookback", {"discovery_lookback_days": -5}, "discovery_lookback_days"),
        ]
    )
    @patch(FF_PAYLOAD_PATH)
    def test_invalid_field_types_fall_back_per_field(self, _name, payload, bad_field, mock_ff):
        mock_ff.return_value = payload

        config = _get_llma_workflow_config()

        if bad_field == "guaranteed_team_ids":
            assert config.guaranteed_team_ids == DEFAULT_GUARANTEED_TEAM_IDS
        if bad_field == "sample_percentage":
            assert config.sample_percentage == DEFAULT_SAMPLE_PERCENTAGE
        if bad_field == "discovery_lookback_days":
            assert config.discovery_lookback_days == DEFAULT_DISCOVERY_LOOKBACK_DAYS

    @patch(FF_PAYLOAD_PATH)
    def test_exception_returns_defaults(self, mock_ff):
        mock_ff.side_effect = Exception("network error")

        config = _get_llma_workflow_config()

        assert config.guaranteed_team_ids == DEFAULT_GUARANTEED_TEAM_IDS
        assert config.sample_percentage == DEFAULT_SAMPLE_PERCENTAGE
        assert config.discovery_lookback_days == DEFAULT_DISCOVERY_LOOKBACK_DAYS

    @patch(FF_PAYLOAD_PATH)
    def test_int_sample_percentage_cast_to_float(self, mock_ff):
        mock_ff.return_value = {"sample_percentage": 1}

        config = _get_llma_workflow_config()

        assert config.sample_percentage == 1.0
        assert isinstance(config.sample_percentage, float)


@patch(FF_PAYLOAD_PATH, return_value=None)
@patch("posthog.temporal.llm_analytics.team_discovery.Heartbeater", _noop_heartbeater)
@pytest.mark.asyncio
class TestGetTeamIdsForLlmAnalytics:
    @patch("posthog.tasks.llm_analytics_usage_report.get_teams_with_ai_events")
    async def test_guaranteed_teams_always_included(self, mock_get_teams, _mock_ff):
        mock_get_teams.return_value = [9999, 8888]
        inputs = TeamDiscoveryInput()

        result = await get_team_ids_for_llm_analytics(inputs)

        for team_id in DEFAULT_GUARANTEED_TEAM_IDS:
            assert team_id in result

    @patch("posthog.tasks.llm_analytics_usage_report.get_teams_with_ai_events")
    async def test_no_duplicates_when_guaranteed_in_ai_events(self, mock_get_teams, _mock_ff):
        mock_get_teams.return_value = [DEFAULT_GUARANTEED_TEAM_IDS[0], 9999]
        inputs = TeamDiscoveryInput()

        result = await get_team_ids_for_llm_analytics(inputs)

        assert len(result) == len(set(result))

    @patch("posthog.tasks.llm_analytics_usage_report.get_teams_with_ai_events")
    async def test_result_is_sorted(self, mock_get_teams, mock_ff):
        mock_ff.return_value = {"sample_percentage": 1.0}
        mock_get_teams.return_value = [9999, 5555, 3333]
        inputs = TeamDiscoveryInput()

        result = await get_team_ids_for_llm_analytics(inputs)

        assert result == sorted(result)

    @patch("posthog.tasks.llm_analytics_usage_report.get_teams_with_ai_events")
    async def test_zero_sample_returns_only_guaranteed(self, mock_get_teams, mock_ff):
        mock_ff.return_value = {"sample_percentage": 0.0}
        extra_teams = [9999, 8888, 7777]
        mock_get_teams.return_value = extra_teams
        inputs = TeamDiscoveryInput()

        result = await get_team_ids_for_llm_analytics(inputs)

        assert set(result) == set(DEFAULT_GUARANTEED_TEAM_IDS)

    @patch("posthog.tasks.llm_analytics_usage_report.get_teams_with_ai_events")
    async def test_full_sample_returns_all(self, mock_get_teams, mock_ff):
        mock_ff.return_value = {"sample_percentage": 1.0}
        extra_teams = [9999, 8888, 7777]
        mock_get_teams.return_value = extra_teams
        inputs = TeamDiscoveryInput()

        result = await get_team_ids_for_llm_analytics(inputs)

        assert set(result) == set(DEFAULT_GUARANTEED_TEAM_IDS) | set(extra_teams)

    @patch("posthog.tasks.llm_analytics_usage_report.get_teams_with_ai_events")
    async def test_sampling_math(self, mock_get_teams, _mock_ff):
        extra_teams = list(range(10000, 10100))  # 100 non-guaranteed teams
        mock_get_teams.return_value = extra_teams
        inputs = TeamDiscoveryInput()

        result = await get_team_ids_for_llm_analytics(inputs)

        sampled_non_guaranteed = [t for t in result if t not in DEFAULT_GUARANTEED_TEAM_IDS]
        expected_sample_size = math.ceil(len(extra_teams) * DEFAULT_SAMPLE_PERCENTAGE)
        assert len(sampled_non_guaranteed) == expected_sample_size

    @patch("posthog.tasks.llm_analytics_usage_report.get_teams_with_ai_events")
    async def test_empty_ai_events_returns_guaranteed(self, mock_get_teams, _mock_ff):
        mock_get_teams.return_value = []
        inputs = TeamDiscoveryInput()

        result = await get_team_ids_for_llm_analytics(inputs)

        assert set(result) == set(DEFAULT_GUARANTEED_TEAM_IDS)

    @patch("posthog.tasks.llm_analytics_usage_report.get_teams_with_ai_events")
    async def test_fallback_on_exception(self, mock_get_teams, _mock_ff):
        mock_get_teams.side_effect = Exception("ClickHouse down")
        inputs = TeamDiscoveryInput()

        result = await get_team_ids_for_llm_analytics(inputs)

        assert set(result) == set(DEFAULT_GUARANTEED_TEAM_IDS)

    @patch("posthog.tasks.llm_analytics_usage_report.get_teams_with_ai_events")
    async def test_feature_flag_overrides_config(self, mock_get_teams, mock_ff):
        mock_ff.return_value = {
            "guaranteed_team_ids": [42],
            "sample_percentage": 0.0,
            "discovery_lookback_days": 7,
        }
        mock_get_teams.return_value = [9999, 8888]
        inputs = TeamDiscoveryInput()

        result = await get_team_ids_for_llm_analytics(inputs)

        assert result == [42]
