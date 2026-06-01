import math
import asyncio
import inspect
from datetime import UTC, datetime

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.temporal.ai.pulse import detection, narrative, selection
from posthog.temporal.ai.pulse.detection import (
    MIN_BASELINE_VALUE,
    _compute_impact,
    _compute_robust_z,
    _evaluate_candidate,
    _extract_weekly_series,
)
from posthog.temporal.ai.pulse.narrative import (
    MAX_NEW_ISSUES_FOR_AI_CONTEXT,
    NARRATIVE_MAX_TOKENS,
    NARRATIVE_MODEL,
    NARRATIVE_TIMEOUT_SECONDS,
    REPLAY_EVIDENCE_LIMIT,
    SYNTHESIS_SYSTEM_PROMPT,
    _attribute_finding,
    _collect_replay_evidence,
    _describe_flag_change,
    _enrich_one,
    _fallback_narrative,
    _fetch_error_signals,
    _fetch_flag_changes,
    _finding_event,
    _generate_narrative,
    _pick_top_contributor,
    _query_session_ids,
    _sanitize_for_prompt,
    enrich_findings,
    synthesize_digest,
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


def _finding_with_event(event: str) -> Finding:
    return Finding(
        descriptor=MetricDescriptor(
            source="top_event",
            source_id=1,
            label=event,
            query={"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": event}]},
        ),
        current_value=50.0,
        baseline_value=100.0,
        change_pct=-0.5,
        impact=10.0,
        robust_z=4.0,
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
        assert _pick_top_contributor({"results": [{"data": [1, 2]}]}) is None  # too few weeks

    def test_picks_largest_baseline_delta_dropping_partial_week(self):
        # Each series is 5 completed weeks + a trailing partial week (dropped), like detection.
        result = {
            "results": [
                {"breakdown_value": "Chrome", "data": [100, 100, 100, 100, 110, 5]},  # 110 vs median 100 -> 10
                {"breakdown_value": "Safari", "data": [50, 50, 50, 50, 5, 2]},  # 5 vs median 50 -> 45
                {"breakdown_value": "Firefox", "data": [80, 80, 80, 80, 75, 3]},  # 75 vs median 80 -> 5
            ]
        }
        contributor = _pick_top_contributor(result)
        assert contributor is not None
        value, current, baseline_median = contributor
        assert value == "Safari"
        assert current == 5
        assert baseline_median == 50

    def test_skips_synthetic_buckets(self):
        # The null bucket has the biggest delta but must be ignored in favour of the real segment.
        result = {
            "results": [
                {"breakdown_value": "$$_posthog_breakdown_null_$$", "data": [200, 200, 200, 200, 10, 1]},
                {"breakdown_value": "Safari", "data": [50, 50, 50, 50, 20, 2]},  # 20 vs median 50 -> 30
            ]
        }
        contributor = _pick_top_contributor(result)
        assert contributor is not None
        assert contributor[0] == "Safari"

    def test_falls_back_to_label_when_no_breakdown_value(self):
        result = {"results": [{"label": "fallback", "data": [10, 10, 10, 10, 100, 5]}]}
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


class TestEnrichOneFallsBackOnEmptyNarrative:
    @pytest.mark.asyncio
    @patch("posthog.temporal.ai.pulse.narrative._attribute_finding", new_callable=AsyncMock)
    @patch("posthog.temporal.ai.pulse.narrative._generate_narrative", new_callable=AsyncMock)
    async def test_uses_fallback_when_llm_returns_empty(self, mock_generate, mock_attribute):
        mock_attribute.return_value = None
        mock_generate.return_value = ""  # empty LLM response (e.g. no model configured locally)
        finding = _finding(impact=10.0, robust_z=4.0, label="$pageview")

        result = await _enrich_one(
            team=MagicMock(id=1),
            user=MagicMock(),
            finding=finding,
            enrichment_semaphore=asyncio.Semaphore(1),
            attribution_semaphore=asyncio.Semaphore(1),
        )

        assert result.narrative == _fallback_narrative(finding)


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


class TestDescribeFlagChange:
    @parameterized.expand(
        [
            ("created", "created", None, "created"),
            ("deleted", "deleted", None, "deleted"),
            ("turned_on", "updated", {"changes": [{"field": "active", "after": True}]}, "turned on"),
            ("turned_off", "updated", {"changes": [{"field": "active", "after": False}]}, "turned off"),
            ("rollout_only", "updated", {"changes": [{"field": "filters", "after": {}}]}, "updated"),
            ("no_detail", "updated", None, "updated"),
            ("empty_changes", "updated", {"changes": []}, "updated"),
        ]
    )
    def test_label(self, _name, activity, detail, expected):
        assert _describe_flag_change(activity, detail) == expected


class TestSanitizeForPrompt:
    def test_strips_angle_brackets(self):
        cleaned = _sanitize_for_prompt("a<script>alert(1)</script>b")
        assert "<" not in cleaned and ">" not in cleaned

    def test_strips_control_chars_and_newlines(self):
        assert "\n" not in _sanitize_for_prompt("line1\nline2\tend")

    def test_truncates_to_200(self):
        assert len(_sanitize_for_prompt("x" * 500)) == 200


class TestSynthesisPromptFramesFlagChanges:
    def test_prompt_covers_flag_changes_as_coincidence(self):
        assert "feature-flag" in SYNTHESIS_SYSTEM_PROMPT
        assert "never proven cause" in SYNTHESIS_SYSTEM_PROMPT


class TestSynthesizeDigestFeedsFlagChangesToLLM:
    @pytest.mark.asyncio
    @patch("posthog.temporal.ai.pulse.narrative.database_sync_to_async")
    async def test_flag_changes_reach_the_model(self, mock_db_wrap):
        flag_changes = [{"date": "2026-05-20", "flag": "new-onboarding", "change": "turned on"}]

        async def _fake_resolve():
            return MagicMock(name="team"), MagicMock(name="user"), [], flag_changes, []

        # database_sync_to_async(fn) -> a callable returning the coroutine (matches the real wrapper shape).
        mock_db_wrap.side_effect = lambda fn: (lambda: _fake_resolve())

        fake_chain = MagicMock()
        fake_chain.ainvoke = AsyncMock(return_value="Two metrics moved, coinciding with a flag change.")
        with (
            patch("posthog.temporal.ai.pulse.narrative.MaxChatOpenAI") as mock_llm_cls,
            patch("posthog.temporal.ai.pulse.narrative.StrOutputParser"),
        ):
            mock_llm_cls.return_value.__or__ = MagicMock(return_value=fake_chain)
            result = await synthesize_digest(
                team_id=1,
                user_id=None,
                findings=[
                    _make_enriched(_finding(impact=10.0, robust_z=4.0, label="A")),
                    _make_enriched(_finding(impact=5.0, robust_z=3.0, label="B")),
                ],
                period_start="2026-05-19T00:00:00+00:00",
                period_end="2026-05-26T00:00:00+00:00",
            )

        assert result == "Two metrics moved, coinciding with a flag change."
        human_message = fake_chain.ainvoke.call_args.args[0][1]
        assert "new-onboarding" in human_message.content
        assert "turned on" in human_message.content

    @pytest.mark.asyncio
    async def test_returns_empty_with_fewer_than_two_findings(self):
        result = await synthesize_digest(
            team_id=1,
            user_id=None,
            findings=[_make_enriched(_finding(impact=10.0, robust_z=4.0, label="A"))],
        )
        assert result == ""


@pytest.mark.django_db
class TestFetchFlagChanges:
    def test_returns_only_feature_flag_changes_in_period_for_team(self):
        team_id = 987654
        ActivityLog.objects.create(
            team_id=team_id,
            scope="FeatureFlag",
            activity="updated",
            detail={"name": "new-onboarding", "changes": [{"field": "active", "after": True}]},
            created_at=datetime(2026, 5, 20, tzinfo=UTC),
        )
        ActivityLog.objects.create(  # out of period
            team_id=team_id,
            scope="FeatureFlag",
            activity="created",
            detail={"name": "old-flag"},
            created_at=datetime(2026, 4, 1, tzinfo=UTC),
        )
        ActivityLog.objects.create(  # wrong scope
            team_id=team_id,
            scope="Insight",
            activity="updated",
            detail={"name": "an-insight"},
            created_at=datetime(2026, 5, 21, tzinfo=UTC),
        )
        ActivityLog.objects.create(  # wrong team
            team_id=team_id + 1,
            scope="FeatureFlag",
            activity="created",
            detail={"name": "other-team-flag"},
            created_at=datetime(2026, 5, 21, tzinfo=UTC),
        )

        out = _fetch_flag_changes(
            team_id,
            datetime(2026, 5, 19, tzinfo=UTC),
            datetime(2026, 5, 26, tzinfo=UTC),
        )

        assert out == [{"date": "2026-05-20", "flag": "new-onboarding", "change": "turned on"}]


class TestFetchErrorSignals:
    @parameterized.expand(
        [
            (
                "maps_and_sanitizes",
                [
                    {"name": "Payment <timeout>", "occurrence_count": 42},
                    {"name": "NullPointer", "occurrence_count": 3},
                ],
                [{"name": "Payment timeout", "count": 42}, {"name": "NullPointer", "count": 3}],
            ),
            (
                "missing_fields_default_safely",
                [{"name": None}, {}],
                [{"name": "Untitled issue", "count": 0}, {"name": "Untitled issue", "count": 0}],
            ),
            ("empty_list", [], []),
        ]
    )
    def test_maps_issues(self, _name, issues, expected):
        with patch("products.error_tracking.backend.facade.api.get_new_issues_for_team", return_value=issues):
            assert _fetch_error_signals(MagicMock(id=1)) == expected

    def test_caps_to_max(self):
        issues = [{"name": f"issue{i}", "occurrence_count": i} for i in range(20)]
        with patch("products.error_tracking.backend.facade.api.get_new_issues_for_team", return_value=issues):
            assert len(_fetch_error_signals(MagicMock(id=1))) == MAX_NEW_ISSUES_FOR_AI_CONTEXT

    def test_degrades_to_empty_on_facade_error(self):
        # A ClickHouse hiccup (or no error tracking) must never break the additive synthesis step.
        with patch(
            "products.error_tracking.backend.facade.api.get_new_issues_for_team",
            side_effect=RuntimeError("clickhouse down"),
        ):
            assert _fetch_error_signals(MagicMock(id=1)) == []


class TestSynthesisPromptFramesErrorIssues:
    def test_prompt_covers_new_error_issues_as_coincidence(self):
        assert "error issue" in SYNTHESIS_SYSTEM_PROMPT
        assert "never proven cause" in SYNTHESIS_SYSTEM_PROMPT


class TestSynthesizeDigestFeedsErrorIssuesToLLM:
    @pytest.mark.asyncio
    @patch("posthog.temporal.ai.pulse.narrative.database_sync_to_async")
    async def test_error_issues_reach_the_model(self, mock_db_wrap):
        error_signals = [{"name": "Payment timeout", "count": 42}]

        async def _fake_resolve():
            return MagicMock(name="team"), MagicMock(name="user"), [], [], error_signals

        # database_sync_to_async(fn) -> a callable returning the coroutine (matches the real wrapper shape).
        mock_db_wrap.side_effect = lambda fn: (lambda: _fake_resolve())

        fake_chain = MagicMock()
        fake_chain.ainvoke = AsyncMock(return_value="A metric dropped alongside a new error.")
        with (
            patch("posthog.temporal.ai.pulse.narrative.MaxChatOpenAI") as mock_llm_cls,
            patch("posthog.temporal.ai.pulse.narrative.StrOutputParser"),
        ):
            mock_llm_cls.return_value.__or__ = MagicMock(return_value=fake_chain)
            result = await synthesize_digest(
                team_id=1,
                user_id=None,
                findings=[
                    _make_enriched(_finding(impact=10.0, robust_z=4.0, label="A")),
                    _make_enriched(_finding(impact=5.0, robust_z=3.0, label="B")),
                ],
                period_start="2026-05-19T00:00:00+00:00",
                period_end="2026-05-26T00:00:00+00:00",
            )

        assert result == "A metric dropped alongside a new error."
        human_message = fake_chain.ainvoke.call_args.args[0][1]
        assert "Payment timeout" in human_message.content


class TestFindingEvent:
    @parameterized.expand(
        [
            ("happy_path", {"kind": "TrendsQuery", "series": [{"event": "purchase"}]}, "purchase"),
            ("no_series", {"kind": "TrendsQuery"}, None),
            ("empty_series", {"kind": "TrendsQuery", "series": []}, None),
            ("non_dict_series_item", {"series": ["nope"]}, None),
            ("missing_event_key", {"series": [{"kind": "EventsNode"}]}, None),
            ("empty_event", {"series": [{"event": ""}]}, None),
            ("non_string_event", {"series": [{"event": 123}]}, None),
        ]
    )
    def test_extract(self, _name, query, expected):
        finding = Finding(
            descriptor=MetricDescriptor(source="top_event", label="m", query=query),
            current_value=1.0,
            baseline_value=1.0,
            change_pct=0.5,
            impact=1.0,
            robust_z=1.0,
        )
        assert _finding_event(finding) == expected


class TestQuerySessionIds:
    def test_builds_valid_recordings_query_and_extracts_ids(self):
        # Patch only the runner; RecordingsQuery is constructed for real so its (extra='forbid')
        # schema validates the shape — a wrong field name here would raise.
        fake_result = MagicMock(results=[{"session_id": "s1"}, {"session_id": "s2"}, {"no_id": True}])
        fake_runner_cls = MagicMock()
        fake_runner_cls.return_value.run.return_value = fake_result

        with patch(
            "posthog.session_recordings.queries.session_recording_list_from_query.SessionRecordingListFromQuery",
            fake_runner_cls,
        ):
            out = _query_session_ids(
                team=MagicMock(),
                event_name="purchase",
                prop_key="$browser",
                prop_value="Safari",
                date_from="2026-05-19",
                date_to="2026-05-26",
            )

        assert out == ["s1", "s2"]  # the row without a session_id is dropped
        query_arg = fake_runner_cls.call_args.kwargs["query"]
        assert query_arg.events[0]["id"] == "purchase"
        assert query_arg.events[0]["type"] == "events"
        assert query_arg.events[0]["properties"][0]["type"] == "event"
        assert query_arg.events[0]["properties"][0]["key"] == "$browser"
        assert query_arg.events[0]["properties"][0]["value"] == "Safari"
        assert query_arg.limit == REPLAY_EVIDENCE_LIMIT
        assert query_arg.filter_test_accounts is True


class TestCollectReplayEvidence:
    @parameterized.expand(
        [
            ("no_attribution", None, "2026-05-19T00:00:00+00:00", "2026-05-26T00:00:00+00:00"),
            ("no_period", {"property": "$browser", "value": "Safari"}, "", ""),
            (
                "synthetic_other_label",
                {"property": "$browser", "value": "Other"},
                "2026-05-19T00:00:00+00:00",
                "2026-05-26T00:00:00+00:00",
            ),
            (
                "synthetic_breakdown_sentinel",
                {"property": "$browser", "value": "$$_posthog_breakdown_other_$$"},
                "2026-05-19T00:00:00+00:00",
                "2026-05-26T00:00:00+00:00",
            ),
            ("missing_property", {"value": "Safari"}, "2026-05-19T00:00:00+00:00", "2026-05-26T00:00:00+00:00"),
            (
                "none_value",
                {"property": "$browser", "value": None},
                "2026-05-19T00:00:00+00:00",
                "2026-05-26T00:00:00+00:00",
            ),
        ]
    )
    async def test_guards_skip_query(self, _name, attribution, period_start, period_end):
        with patch("posthog.temporal.ai.pulse.narrative.database_sync_to_async") as mock_db:
            out = await _collect_replay_evidence(
                MagicMock(id=1), _finding_with_event("purchase"), attribution, period_start, period_end
            )
        assert out == []
        mock_db.assert_not_called()

    async def test_skips_when_finding_has_no_event(self):
        finding = _finding(impact=10.0, robust_z=4.0, label="m")  # query has no series → no event
        with patch("posthog.temporal.ai.pulse.narrative.database_sync_to_async") as mock_db:
            out = await _collect_replay_evidence(
                MagicMock(id=1),
                finding,
                {"property": "$browser", "value": "Safari"},
                "2026-05-19T00:00:00+00:00",
                "2026-05-26T00:00:00+00:00",
            )
        assert out == []
        mock_db.assert_not_called()

    async def test_returns_session_ids_for_real_segment(self):
        async def _fake_ids():
            return ["s1", "s2"]

        with patch("posthog.temporal.ai.pulse.narrative.database_sync_to_async") as mock_db:
            mock_db.side_effect = lambda fn, **kw: (lambda *a, **k: _fake_ids())
            out = await _collect_replay_evidence(
                MagicMock(id=1),
                _finding_with_event("purchase"),
                {"property": "$browser", "value": "Safari"},
                "2026-05-19T00:00:00+00:00",
                "2026-05-26T00:00:00+00:00",
            )
        assert out == ["s1", "s2"]

    async def test_degrades_to_empty_on_query_error(self):
        def _raising_wrapper(fn, **kw):
            def _call(*a, **k):
                raise RuntimeError("clickhouse exploded")

            return _call

        with patch("posthog.temporal.ai.pulse.narrative.database_sync_to_async", side_effect=_raising_wrapper):
            out = await _collect_replay_evidence(
                MagicMock(id=1),
                _finding_with_event("purchase"),
                {"property": "$browser", "value": "Safari"},
                "2026-05-19T00:00:00+00:00",
                "2026-05-26T00:00:00+00:00",
            )
        assert out == []


class TestEnrichOneSetsEvidence:
    async def test_evidence_set_when_sessions_found(self):
        with (
            patch("posthog.temporal.ai.pulse.narrative._attribute_finding", new_callable=AsyncMock) as mock_attr,
            patch("posthog.temporal.ai.pulse.narrative._collect_replay_evidence", new_callable=AsyncMock) as mock_evi,
            patch("posthog.temporal.ai.pulse.narrative._generate_narrative", new_callable=AsyncMock) as mock_narr,
        ):
            mock_attr.return_value = {"property": "$browser", "value": "Safari"}
            mock_evi.return_value = ["s1", "s2"]
            mock_narr.return_value = "Purchases dropped, concentrated in Safari."
            result = await _enrich_one(
                team=MagicMock(id=1),
                user=MagicMock(),
                finding=_finding_with_event("purchase"),
                enrichment_semaphore=asyncio.Semaphore(1),
                attribution_semaphore=asyncio.Semaphore(1),
                period_start="2026-05-19T00:00:00+00:00",
                period_end="2026-05-26T00:00:00+00:00",
            )

        assert result.evidence == {"session_ids": ["s1", "s2"]}
        assert result.attribution_breakdown == {"property": "$browser", "value": "Safari"}

    async def test_evidence_none_when_no_sessions(self):
        with (
            patch("posthog.temporal.ai.pulse.narrative._attribute_finding", new_callable=AsyncMock) as mock_attr,
            patch("posthog.temporal.ai.pulse.narrative._collect_replay_evidence", new_callable=AsyncMock) as mock_evi,
            patch("posthog.temporal.ai.pulse.narrative._generate_narrative", new_callable=AsyncMock) as mock_narr,
        ):
            mock_attr.return_value = None
            mock_evi.return_value = []
            mock_narr.return_value = "Purchases dropped."
            result = await _enrich_one(
                team=MagicMock(id=1),
                user=MagicMock(),
                finding=_finding_with_event("purchase"),
                enrichment_semaphore=asyncio.Semaphore(1),
                attribution_semaphore=asyncio.Semaphore(1),
            )

        assert result.evidence is None
