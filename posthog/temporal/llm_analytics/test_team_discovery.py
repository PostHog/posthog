import math
from contextlib import asynccontextmanager

import pytest
from unittest.mock import patch

from parameterized import parameterized

from posthog.temporal.llm_analytics.team_discovery import (
    GUARANTEED_TEAM_IDS,
    TeamDiscoveryInput,
    get_team_ids_for_llm_analytics,
)


@asynccontextmanager
async def _noop_heartbeater(*args, **kwargs):
    yield


@patch("posthog.temporal.llm_analytics.team_discovery.Heartbeater", _noop_heartbeater)
@pytest.mark.asyncio
class TestGetTeamIdsForLlmAnalytics:
    @parameterized.expand(
        [
            ("zero_percent", 0.0),
            ("ten_percent", 0.1),
            ("fifty_percent", 0.5),
            ("hundred_percent", 1.0),
        ]
    )
    @patch("posthog.tasks.llm_analytics_usage_report.get_teams_with_ai_events")
    async def test_guaranteed_teams_always_included(self, _name, sample_pct, mock_get_teams):
        mock_get_teams.return_value = [9999, 8888]
        inputs = TeamDiscoveryInput(lookback_days=30, sample_percentage=sample_pct)

        result = await get_team_ids_for_llm_analytics(inputs)

        for team_id in GUARANTEED_TEAM_IDS:
            assert team_id in result

    @patch("posthog.tasks.llm_analytics_usage_report.get_teams_with_ai_events")
    async def test_no_duplicates_when_guaranteed_in_ai_events(self, mock_get_teams):
        mock_get_teams.return_value = [GUARANTEED_TEAM_IDS[0], 9999]
        inputs = TeamDiscoveryInput(lookback_days=30, sample_percentage=1.0)

        result = await get_team_ids_for_llm_analytics(inputs)

        assert len(result) == len(set(result))

    @patch("posthog.tasks.llm_analytics_usage_report.get_teams_with_ai_events")
    async def test_result_is_sorted(self, mock_get_teams):
        mock_get_teams.return_value = [9999, 5555, 3333]
        inputs = TeamDiscoveryInput(lookback_days=30, sample_percentage=1.0)

        result = await get_team_ids_for_llm_analytics(inputs)

        assert result == sorted(result)

    @patch("posthog.tasks.llm_analytics_usage_report.get_teams_with_ai_events")
    async def test_zero_sample_returns_only_guaranteed(self, mock_get_teams):
        extra_teams = [9999, 8888, 7777]
        mock_get_teams.return_value = extra_teams
        inputs = TeamDiscoveryInput(lookback_days=30, sample_percentage=0.0)

        result = await get_team_ids_for_llm_analytics(inputs)

        assert set(result) == set(GUARANTEED_TEAM_IDS)

    @patch("posthog.tasks.llm_analytics_usage_report.get_teams_with_ai_events")
    async def test_full_sample_returns_all(self, mock_get_teams):
        extra_teams = [9999, 8888, 7777]
        mock_get_teams.return_value = extra_teams
        inputs = TeamDiscoveryInput(lookback_days=30, sample_percentage=1.0)

        result = await get_team_ids_for_llm_analytics(inputs)

        assert set(result) == set(GUARANTEED_TEAM_IDS) | set(extra_teams)

    @patch("posthog.tasks.llm_analytics_usage_report.get_teams_with_ai_events")
    async def test_sampling_math(self, mock_get_teams):
        extra_teams = list(range(10000, 10100))  # 100 non-guaranteed teams
        mock_get_teams.return_value = extra_teams
        inputs = TeamDiscoveryInput(lookback_days=30, sample_percentage=0.1)

        result = await get_team_ids_for_llm_analytics(inputs)

        sampled_non_guaranteed = [t for t in result if t not in GUARANTEED_TEAM_IDS]
        expected_sample_size = math.ceil(len(extra_teams) * 0.1)
        assert len(sampled_non_guaranteed) == expected_sample_size

    @patch("posthog.tasks.llm_analytics_usage_report.get_teams_with_ai_events")
    async def test_empty_ai_events_returns_guaranteed(self, mock_get_teams):
        mock_get_teams.return_value = []
        inputs = TeamDiscoveryInput(lookback_days=30, sample_percentage=0.1)

        result = await get_team_ids_for_llm_analytics(inputs)

        assert set(result) == set(GUARANTEED_TEAM_IDS)

    @patch("posthog.tasks.llm_analytics_usage_report.get_teams_with_ai_events")
    async def test_fallback_on_exception(self, mock_get_teams):
        mock_get_teams.side_effect = Exception("ClickHouse down")
        inputs = TeamDiscoveryInput(lookback_days=30, sample_percentage=0.1)

        result = await get_team_ids_for_llm_analytics(inputs)

        assert set(result) == set(GUARANTEED_TEAM_IDS)
