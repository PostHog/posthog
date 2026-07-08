import math
from contextlib import asynccontextmanager

import pytest
from unittest.mock import patch

from parameterized import parameterized

from posthog.temporal.ai_observability.team_discovery import (
    DEFAULT_DISCOVERY_LOOKBACK_DAYS,
    DEFAULT_GUARANTEED_TEAM_IDS,
    DEFAULT_SAMPLE_PERCENTAGE,
    TeamDiscoveryInput,
    _get_ai_observability_workflow_config,
    get_min_traces_override,
    get_team_ids_for_ai_observability,
)


@asynccontextmanager
async def _noop_heartbeater(*args, **kwargs):
    yield


FF_PAYLOAD_PATH = "posthog.temporal.ai_observability.team_discovery.posthoganalytics.get_feature_flag_payload"


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


@patch(FF_PAYLOAD_PATH, return_value=None)
@patch("posthog.temporal.ai_observability.team_discovery.Heartbeater", _noop_heartbeater)
@pytest.mark.asyncio
class TestGetTeamIdsForAIObservability:
    @patch("posthog.tasks.ai_observability_usage_report.get_teams_with_ai_events")
    async def test_guaranteed_teams_always_included(self, mock_get_teams, _mock_ff):
        mock_get_teams.return_value = [9999, 8888]
        inputs = TeamDiscoveryInput()

        result = await get_team_ids_for_ai_observability(inputs)

        for team_id in DEFAULT_GUARANTEED_TEAM_IDS:
            assert team_id in result

    @patch("posthog.tasks.ai_observability_usage_report.get_teams_with_ai_events")
    async def test_no_duplicates_when_guaranteed_in_ai_events(self, mock_get_teams, _mock_ff):
        mock_get_teams.return_value = [DEFAULT_GUARANTEED_TEAM_IDS[0], 9999]
        inputs = TeamDiscoveryInput()

        result = await get_team_ids_for_ai_observability(inputs)

        assert len(result) == len(set(result))

    @patch("posthog.tasks.ai_observability_usage_report.get_teams_with_ai_events")
    async def test_guaranteed_teams_ordered_before_sampled(self, mock_get_teams, mock_ff):
        # High guaranteed id placed ahead of a lower sampled id proves ordering is by
        # guaranteed-first, not global sort — the coordinator must reach allowlisted
        # teams before it exhausts its run budget on the sampled tail.
        mock_ff.return_value = {"guaranteed_team_ids": [9000], "sample_percentage": 1.0}
        mock_get_teams.return_value = [5555, 3333, 7777]
        inputs = TeamDiscoveryInput()

        result = await get_team_ids_for_ai_observability(inputs)

        assert result == [9000, 3333, 5555, 7777]

    @patch("posthog.tasks.ai_observability_usage_report.get_teams_with_ai_events")
    async def test_zero_sample_returns_only_guaranteed(self, mock_get_teams, mock_ff):
        mock_ff.return_value = {"sample_percentage": 0.0}
        extra_teams = [9999, 8888, 7777]
        mock_get_teams.return_value = extra_teams
        inputs = TeamDiscoveryInput()

        result = await get_team_ids_for_ai_observability(inputs)

        assert set(result) == set(DEFAULT_GUARANTEED_TEAM_IDS)

    @patch("posthog.tasks.ai_observability_usage_report.get_teams_with_ai_events")
    async def test_full_sample_returns_all(self, mock_get_teams, mock_ff):
        mock_ff.return_value = {"sample_percentage": 1.0}
        extra_teams = [9999, 8888, 7777]
        mock_get_teams.return_value = extra_teams
        inputs = TeamDiscoveryInput()

        result = await get_team_ids_for_ai_observability(inputs)

        assert set(result) == set(DEFAULT_GUARANTEED_TEAM_IDS) | set(extra_teams)

    @patch("posthog.tasks.ai_observability_usage_report.get_teams_with_ai_events")
    async def test_sampling_math(self, mock_get_teams, _mock_ff):
        extra_teams = list(range(10000, 10100))  # 100 non-guaranteed teams
        mock_get_teams.return_value = extra_teams
        inputs = TeamDiscoveryInput()

        result = await get_team_ids_for_ai_observability(inputs)

        sampled_non_guaranteed = [t for t in result if t not in DEFAULT_GUARANTEED_TEAM_IDS]
        expected_sample_size = math.ceil(len(extra_teams) * DEFAULT_SAMPLE_PERCENTAGE)
        assert len(sampled_non_guaranteed) == expected_sample_size

    @patch("posthog.tasks.ai_observability_usage_report.get_teams_with_ai_events")
    async def test_empty_ai_events_returns_guaranteed(self, mock_get_teams, _mock_ff):
        mock_get_teams.return_value = []
        inputs = TeamDiscoveryInput()

        result = await get_team_ids_for_ai_observability(inputs)

        assert set(result) == set(DEFAULT_GUARANTEED_TEAM_IDS)

    @patch("posthog.tasks.ai_observability_usage_report.get_teams_with_ai_events")
    async def test_fallback_on_exception(self, mock_get_teams, _mock_ff):
        mock_get_teams.side_effect = Exception("ClickHouse down")
        inputs = TeamDiscoveryInput()

        result = await get_team_ids_for_ai_observability(inputs)

        assert set(result) == set(DEFAULT_GUARANTEED_TEAM_IDS)

    @patch("posthog.tasks.ai_observability_usage_report.get_teams_with_ai_events")
    async def test_feature_flag_overrides_config(self, mock_get_teams, mock_ff):
        mock_ff.return_value = {
            "guaranteed_team_ids": [42],
            "sample_percentage": 0.0,
        }
        mock_get_teams.return_value = [9999, 8888]
        inputs = TeamDiscoveryInput()

        result = await get_team_ids_for_ai_observability(inputs)

        assert result == [42]

    @patch("posthog.tasks.ai_observability_usage_report.get_teams_with_ai_events")
    async def test_skip_team_ids_excludes_from_sampled(self, mock_get_teams, mock_ff):
        mock_ff.return_value = {
            "guaranteed_team_ids": [1],
            "skip_team_ids": [9999],
            "sample_percentage": 1.0,
        }
        mock_get_teams.return_value = [9999, 8888, 7777]
        inputs = TeamDiscoveryInput()

        result = await get_team_ids_for_ai_observability(inputs)

        assert 9999 not in result
        assert 8888 in result
        assert 7777 in result

    @patch("posthog.tasks.ai_observability_usage_report.get_teams_with_ai_events")
    async def test_skip_team_ids_excludes_from_guaranteed(self, mock_get_teams, mock_ff):
        mock_ff.return_value = {
            "guaranteed_team_ids": [1, 2, 3],
            "skip_team_ids": [2],
            "sample_percentage": 0.0,
        }
        mock_get_teams.return_value = []
        inputs = TeamDiscoveryInput()

        result = await get_team_ids_for_ai_observability(inputs)

        assert result == [1, 3]

    @patch("posthog.tasks.ai_observability_usage_report.get_teams_with_ai_events")
    async def test_skip_team_ids_applied_in_fallback(self, mock_get_teams, mock_ff):
        mock_ff.return_value = {
            "guaranteed_team_ids": [1, 2, 3],
            "skip_team_ids": [2],
        }
        mock_get_teams.side_effect = Exception("ClickHouse down")
        inputs = TeamDiscoveryInput()

        result = await get_team_ids_for_ai_observability(inputs)

        assert result == [1, 3]

    @patch("posthog.tasks.ai_observability_usage_report.get_teams_with_ai_events")
    async def test_uses_discovery_trigger_events_not_report_list(self, mock_get_teams, _mock_ff):
        """Discovery must pass the narrow trigger list — excluding server-emitted
        $ai_*_clusters / $ai_*_summary events — to avoid the self-perpetuating
        eligibility loop. The broader AI_OBSERVABILITY_REPORT_TRIGGER_EVENTS list is
        reserved for the usage-report caller.
        """
        from posthog.tasks.ai_observability_usage_report import (
            AI_OBSERVABILITY_REPORT_TRIGGER_EVENTS,
            LLM_ANALYTICS_DISCOVERY_TRIGGER_EVENTS,
        )

        mock_get_teams.return_value = []
        inputs = TeamDiscoveryInput()

        await get_team_ids_for_ai_observability(inputs)

        assert mock_get_teams.called
        passed_trigger_events = mock_get_teams.call_args.args[2]
        assert passed_trigger_events == LLM_ANALYTICS_DISCOVERY_TRIGGER_EVENTS
        assert "$ai_trace_clusters" not in passed_trigger_events
        assert "$ai_generation_clusters" not in passed_trigger_events
        assert "$ai_trace_summary" not in passed_trigger_events
        assert "$ai_generation_summary" not in passed_trigger_events
        assert "$ai_tag" not in passed_trigger_events
        assert "$llm_prompt_fetched" not in passed_trigger_events
        assert "$ai_generation" in passed_trigger_events
        assert set(passed_trigger_events) < set(AI_OBSERVABILITY_REPORT_TRIGGER_EVENTS)

    @patch("posthog.tasks.ai_observability_usage_report.get_teams_with_ai_events")
    async def test_lookback_uses_ff_payload_value(self, mock_get_teams, mock_ff):
        """The discovery activity scopes its eligibility query to the
        discovery_lookback_days from the feature flag payload.
        """
        mock_ff.return_value = {"discovery_lookback_days": 3}
        mock_get_teams.return_value = []

        await get_team_ids_for_ai_observability(TeamDiscoveryInput())

        begin, end = mock_get_teams.call_args.args[0], mock_get_teams.call_args.args[1]
        delta_days = (end - begin).total_seconds() / 86400
        assert 2.99 < delta_days < 3.01
