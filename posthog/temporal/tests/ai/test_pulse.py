import math
import asyncio
import inspect

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized

from posthog.temporal.ai.pulse import detection, narrative, selection
from posthog.temporal.ai.pulse.detection import (
    MIN_BASELINE_VALUE,
    _compute_impact,
    _compute_robust_z,
    _evaluate_candidate,
    _extract_weekly_series,
)
from posthog.temporal.ai.pulse.narrative import (
    NARRATIVE_MAX_TOKENS,
    NARRATIVE_MODEL,
    NARRATIVE_TIMEOUT_SECONDS,
    _attribute_finding,
    _enrich_one,
    _fallback_narrative,
    _generate_narrative,
    _pick_top_contributor,
    enrich_findings,
)
from posthog.temporal.ai.pulse.types import (
    CandidateMetric,
    EnrichedFinding,
    EnrichFindingsInputs,
    Finding,
    MetricDescriptor,
)


def _finding(*, impact: float, robust_z: float, label: str) -> Finding:
    return Finding(
        descriptor=MetricDescriptor(source="top_event", source_id=1, label=label, query={"kind": "TrendsQuery"}),
        current_value=50.0,
        baseline_value=100.0,
        change_pct=-0.5,
        impact=impact,
        robust_z=robust_z,
    )


def _make_enriched(f: Finding) -> EnrichedFinding:
    return EnrichedFinding(
        descriptor=f.descriptor,
        current_value=f.current_value,
        baseline_value=f.baseline_value,
        change_pct=f.change_pct,
        impact=f.impact,
        robust_z=f.robust_z,
        narrative="x",
    )


def _make_candidate() -> CandidateMetric:
    return CandidateMetric(
        descriptor=MetricDescriptor(source="top_event", source_id=1, label="$pageview", query={"kind": "TrendsQuery"})
    )


class TestComputeRobustZ:
    @parameterized.expand(
        [
            ("baseline_too_small_returns_zero", 5.0, [10.0], 0.0),
            ("zero_mad_returns_floor", 7.0, [5.0, 5.0, 5.0], 0.0),
        ]
    )
    def test_edge_cases(self, _name, current, baseline, expected):
        assert _compute_robust_z(current, baseline) == expected

    def test_robust_z_uses_median_not_mean(self):
        # median([10,10,10,10,90]) = 10; one outlier must not inflate the baseline.
        z = _compute_robust_z(40.0, [10.0, 10.0, 10.0, 10.0, 90.0])
        # MAD = median(|x-10|) = median([0,0,0,0,80]) = 0  -> floor 0.0
        assert z == 0.0

    def test_robust_z_positive_for_clear_outlier(self):
        # median=10, MAD=median([2,0,0,4])=1.0 ; robust_z = 0.6745*|25-10|/1.0
        z = _compute_robust_z(25.0, [8.0, 10.0, 10.0, 14.0])
        assert z == pytest.approx(0.6745 * 15.0 / 1.0)


class TestComputeImpact:
    @parameterized.expand(
        [
            ("zero_change", 0.0, 100.0, 0.0),
            ("half_drop_baseline_100", -0.5, 100.0, 0.5 * 10.0),
            ("double_baseline_64", 1.0, 64.0, 1.0 * 8.0),
        ]
    )
    def test_impact(self, _name, change_pct, baseline_median, expected):
        assert _compute_impact(change_pct, baseline_median) == pytest.approx(expected)


class TestExtractWeeklySeries:
    @parameterized.expand(
        [
            ("non_dict_returns_empty", "garbage", []),
            ("empty_results_returns_empty", {"results": []}, []),
            ("missing_results_returns_empty", {}, []),
            ("happy_path_floats", {"results": [{"data": [1, 2.5, 3]}]}, [1.0, 2.5, 3.0]),
            ("filters_bools", {"results": [{"data": [1, True, 3]}]}, [1.0, 3.0]),
            ("filters_non_numeric", {"results": [{"data": [1, "x", None, 4]}]}, [1.0, 4.0]),
        ]
    )
    def test_extraction(self, _name, result, expected):
        assert _extract_weekly_series(result) == expected


class TestEvaluateCandidate:
    def test_returns_none_when_series_too_short(self):
        assert _evaluate_candidate(_make_candidate(), [10, 10, 10, 12], 0.25, 3.5) is None

    def test_returns_none_when_baseline_too_low_volume(self):
        below = MIN_BASELINE_VALUE - 1
        series = [below, below, below, below, below, 999]
        assert _evaluate_candidate(_make_candidate(), series, 0.25, 3.5) is None

    def test_uses_median_baseline_robust_to_one_bad_week(self):
        # One spiked baseline week must not move the baseline (median=100, mean would be 280).
        series = [100.0, 100.0, 1000.0, 100.0, 50.0, 999.0]
        finding = _evaluate_candidate(_make_candidate(), series, min_change_pct=0.25, robust_z_threshold=3.5)
        assert finding is not None
        assert finding.baseline_value == pytest.approx(100.0)
        assert finding.current_value == 50.0

    def test_impact_set_on_finding(self):
        series = [100.0, 100.0, 100.0, 100.0, 50.0, 999.0]
        finding = _evaluate_candidate(_make_candidate(), series, min_change_pct=0.25, robust_z_threshold=3.5)
        assert finding is not None
        assert finding.impact == pytest.approx(0.5 * math.sqrt(100.0))

    def test_change_pct_is_primary_gate_z_alone_does_not_fire(self):
        # ~5% change but a large robust_z: must NOT fire (change_pct below min, z is secondary).
        series = [98.0, 100.0, 102.0, 100.0, 105.0, 999.0]
        assert _evaluate_candidate(_make_candidate(), series, min_change_pct=0.25, robust_z_threshold=0.1) is None

    def test_returns_finding_on_relative_change(self):
        series = [100.0, 100.0, 100.0, 100.0, 50.0, 999.0]
        finding = _evaluate_candidate(_make_candidate(), series, min_change_pct=0.25, robust_z_threshold=3.5)
        assert finding is not None
        assert finding.current_value == 50.0
        assert finding.change_pct < 0
        assert finding.baseline_value == pytest.approx(100.0)
        assert finding.robust_z >= 0.0

    def test_returns_none_when_change_below_min(self):
        series = [100.0, 102.0, 98.0, 101.0, 103.0, 999.0]  # ~3% change
        assert _evaluate_candidate(_make_candidate(), series, min_change_pct=0.25, robust_z_threshold=3.5) is None


class TestPickTopContributor:
    def test_returns_none_for_invalid_input(self):
        assert _pick_top_contributor(None) is None
        assert _pick_top_contributor({"results": []}) is None
        assert _pick_top_contributor({"results": [{"data": [1]}]}) is None  # single point

    def test_picks_largest_delta(self):
        result = {
            "results": [
                {"breakdown_value": "Chrome", "data": [100, 110]},  # delta=10
                {"breakdown_value": "Safari", "data": [50, 5]},  # delta=45
                {"breakdown_value": "Firefox", "data": [80, 75]},  # delta=5
            ]
        }
        contributor = _pick_top_contributor(result)
        assert contributor is not None
        value, current, prior = contributor
        assert value == "Safari"
        assert current == 5
        assert prior == 50

    def test_falls_back_to_label_when_no_breakdown_value(self):
        result = {"results": [{"label": "fallback", "data": [10, 100]}]}
        contributor = _pick_top_contributor(result)
        assert contributor is not None
        assert contributor[0] == "fallback"


class TestRankByImpact:
    def _finding(self, label: str, impact: float, robust_z: float) -> Finding:
        return Finding(
            descriptor=MetricDescriptor(source="top_event", label=label, query={"kind": "TrendsQuery"}),
            current_value=1.0,
            baseline_value=1.0,
            change_pct=0.5,
            impact=impact,
            robust_z=robust_z,
        )

    def test_ranking_orders_by_impact_not_robust_z(self):
        findings = [
            self._finding("low_impact_high_z", impact=1.0, robust_z=99.0),
            self._finding("high_impact_low_z", impact=50.0, robust_z=0.1),
        ]
        ranked = sorted(findings, key=lambda f: f.impact, reverse=True)
        # Confirms the sort key the module uses is impact, not robust_z.
        assert ranked[0].descriptor.label == "high_impact_low_z"
        assert narrative.enrich_findings.__module__ == "posthog.temporal.ai.pulse.narrative"


class TestNarrativeModelConstant:
    def test_model_constant_is_gpt5_mini(self):
        assert NARRATIVE_MODEL == "gpt-5-mini"


class TestGenerateNarrativeRoutesThroughMaxChatOpenAI:
    @pytest.mark.asyncio
    async def test_constructs_maxchatopenai_with_constants(self):
        fake_user = MagicMock(name="service_user")
        fake_team = MagicMock(name="team")
        fake_chain = MagicMock()
        fake_chain.ainvoke = AsyncMock(return_value="  $pageview is down 50% this week.  ")

        with (
            patch("posthog.temporal.ai.pulse.narrative.MaxChatOpenAI") as mock_llm_cls,
            patch("posthog.temporal.ai.pulse.narrative.StrOutputParser"),
        ):
            mock_llm_cls.return_value.__or__ = MagicMock(return_value=fake_chain)
            result = await _generate_narrative(
                fake_team, fake_user, _finding(impact=10.0, robust_z=4.0, label="$pageview"), attribution=None
            )

        assert result == "$pageview is down 50% this week."
        kwargs = mock_llm_cls.call_args.kwargs
        assert kwargs["model"] == NARRATIVE_MODEL
        assert kwargs["max_tokens"] == NARRATIVE_MAX_TOKENS
        assert kwargs["request_timeout"] == NARRATIVE_TIMEOUT_SECONDS
        assert kwargs["user"] is fake_user
        assert kwargs["team"] is fake_team
        assert kwargs["inject_context"] is False
        assert kwargs["posthog_properties"]["ai_product"] == "pulse"


class TestEnrichFindingsRanksByImpact:
    @pytest.mark.asyncio
    @patch("posthog.temporal.ai.pulse.narrative._enrich_one", new_callable=AsyncMock)
    @patch("posthog.temporal.ai.pulse.narrative.database_sync_to_async")
    async def test_ranks_by_impact_not_robust_z(self, mock_db_wrap, mock_enrich_one):
        async def _fake_resolve():
            return (MagicMock(), MagicMock())

        # database_sync_to_async is used as @decorator(fn) -> wrapped; the wrapped call returns the coroutine.
        mock_db_wrap.side_effect = lambda fn: (lambda: _fake_resolve())
        mock_enrich_one.side_effect = lambda team, user, f, *a: _make_enriched(f)

        low_impact = _finding(impact=1.0, robust_z=9.0, label="low")
        high_impact = _finding(impact=100.0, robust_z=2.0, label="high")

        out = await enrich_findings(team_id=1, user_id=None, findings=[low_impact, high_impact], max_findings=1)

        assert len(out) == 1
        assert out[0].descriptor.label == "high"  # ranked by impact, not robust_z


class TestEnrichOneFallsBackOnLLMError:
    @pytest.mark.asyncio
    @patch("posthog.temporal.ai.pulse.narrative._attribute_finding", new_callable=AsyncMock)
    @patch("posthog.temporal.ai.pulse.narrative._generate_narrative", new_callable=AsyncMock)
    async def test_uses_fallback_when_llm_raises(self, mock_generate, mock_attribute):
        mock_attribute.return_value = None
        mock_generate.side_effect = TimeoutError("openai timed out")
        finding = _finding(impact=10.0, robust_z=4.0, label="$pageview")

        result = await _enrich_one(
            team=MagicMock(id=1),
            user=MagicMock(),
            finding=finding,
            enrichment_semaphore=asyncio.Semaphore(1),
            attribution_semaphore=asyncio.Semaphore(1),
        )

        assert result.narrative == _fallback_narrative(finding)
        assert result.attribution_breakdown is None
        assert result.impact == 10.0
        assert result.robust_z == 4.0


class TestPureStagesHaveNoLLM:
    @parameterized.expand(
        [
            ("detection", detection),
            ("selection", selection),
        ]
    )
    def test_module_source_has_no_llm_client(self, _name, module):
        src = inspect.getsource(module)
        assert "ChatOpenAI" not in src
        assert "MaxChatOpenAI" not in src
        assert "langchain_openai" not in src

    @parameterized.expand(
        [
            ("attribution", _attribute_finding),
            ("top_contributor", _pick_top_contributor),
        ]
    )
    def test_attribution_helpers_have_no_llm_client(self, _name, fn):
        src = inspect.getsource(fn)
        assert "ChatOpenAI" not in src
        assert "MaxChatOpenAI" not in src


class TestEnrichInputsCarryServiceUser:
    @parameterized.expand(
        [
            ("with_creator", 42, 42),
            ("no_creator", None, None),
        ]
    )
    def test_user_id_propagated(self, _name, created_by_id, expected):
        inputs = EnrichFindingsInputs(
            team_id=7,
            user_id=created_by_id,
            findings=[_finding(impact=1.0, robust_z=2.0, label="$pageview")],
            max_findings=5,
        )
        assert inputs.user_id == expected
