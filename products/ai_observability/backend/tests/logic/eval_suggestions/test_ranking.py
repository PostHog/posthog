from dataclasses import replace

from parameterized import parameterized

from posthog.schema import LLMTrace

from products.ai_observability.backend.llm import DEFAULT_MODEL_BY_PROVIDER
from products.ai_observability.backend.logic.eval_suggestions import adapters, ranking
from products.ai_observability.backend.logic.eval_suggestions.measure import (
    Measurement,
    Outcome,
    SampledTrace,
    TraceSample,
)
from products.ai_observability.backend.logic.eval_suggestions.profile import FieldMeaning, StructuredGap, TeamProfile


def _sampled(trace_id: str, product: str, held_out: bool = False, earlier: tuple[str, ...] = ()) -> SampledTrace:
    return SampledTrace(
        trace=LLMTrace(id=trace_id, createdAt="2026-11-01T00:00:00Z", distinctId="user", events=[]),
        held_out=held_out,
        spans_days=False,
        segments={"ai_product": product},
        segment_values={"ai_product": frozenset({product, *earlier})},
        raw_segment_values={"ai_product": frozenset({product, *earlier})},
        final_text="answer",
        turn_text="",
        user_messages=1,
        has_tool_results=False,
        input_tokens=0,
    )


def _population(
    prefix: str, product: str, total: int, failing: int, held_out: bool = False
) -> tuple[list[SampledTrace], list[Outcome]]:
    traces = [_sampled(f"{prefix}{i}", product, held_out) for i in range(total)]
    outcomes = [
        Outcome(trace_id=t.trace.id, failed=i < failing, reasoning="Turn ended with failed calls")
        for i, t in enumerate(traces)
    ]
    return traces, outcomes


PROFILE = TeamProfile(
    generations=5000,
    traces=1000,
    sessions=100,
    session_traces=1000,
    generations_by_days_ago={0: 700, 1: 700},
    traces_by_days_ago={0: 150, 1: 150},
    tool_call_share=0.5,
    tool_counts={},
    dispatcher_tools=(),
    session_share=0.0,
    mean_input_tokens=1200.0,
    models=(),
    error_prefixes=(),
    segments={"ai_product": {"chat": 4000, "batch": 1000}},
)


def _measurement(main_rate: tuple[int, int], held_rate: tuple[int, int]) -> tuple[Measurement, TraceSample]:
    main_traces, main_outcomes = _population("m", "chat", main_rate[1], main_rate[0])
    held_traces, held_outcomes = _population("h", "chat", held_rate[1], held_rate[0], held_out=True)
    check = adapters.unrecovered_errors([])
    return Measurement(check=check, main=main_outcomes, held_out=held_outcomes), TraceSample(
        main=main_traces, held_out=held_traces
    )


class TestCodeCheckValidation:
    @parameterized.expand(
        [
            ("rare_failure_kept", (3, 250), (0, 100), True),
            ("check_that_does_not_fit_the_app", (80, 250), (30, 100), False),
            ("no_failures", (0, 250), (0, 100), False),
            ("single_failure_is_not_enough", (1, 250), (0, 100), False),
            ("held_out_day_contradicts_a_common_failure", (40, 250), (0, 100), False),
            ("a_tiny_held_out_day_cannot_reject_alone", (12, 240), (1, 3), True),
            ("a_held_out_day_that_surely_fails_too_often", (12, 240), (20, 30), False),
        ]
    )
    def test_keeps_only_validated_checks(
        self, _name: str, main: tuple[int, int], held: tuple[int, int], kept: bool
    ) -> None:
        measurement, sample = _measurement(main, held)
        proposal = ranking.code_check_proposal(measurement, sample, PROFILE, similar_evaluation_id=None)
        assert (proposal is not None) is kept
        if proposal is not None:
            assert proposal.measured_failure_rate == main[0] / main[1]
            assert proposal.sample_size == main[1]


class TestFilterRule:
    @parameterized.expand(
        [
            # 24 of 26 failures in one segment, far above the rest, also on the held-out day.
            ("segment_holds_the_failures", 24, 2, 4, True),
            # Same failures, but the held-out day fails the segment no more than the rest.
            ("segment_does_not_hold_on_the_held_out_day", 24, 2, 0, False),
            # Too few failing traces to trust a narrower scope.
            ("too_few_failures", 12, 1, 4, False),
        ]
    )
    def test_filter(
        self, _name: str, failing_in: int, failing_out: int, held_failing_in: int, expect_filter: bool
    ) -> None:
        inside, inside_outcomes = _population("in", "batch", 60, failing_in)
        outside, outside_outcomes = _population("out", "chat", 240, failing_out)
        held_in, held_in_outcomes = _population("hin", "batch", 20, held_failing_in, held_out=True)
        held_rest, held_rest_outcomes = _population("hout", "chat", 80, 1, held_out=True)
        outcomes = inside_outcomes + outside_outcomes
        held = {o.trace_id: bool(o.failed) for o in held_in_outcomes + held_rest_outcomes}

        filters = ranking.filter_for(
            {o.trace_id for o in outcomes if o.failed},
            {o.trace_id: bool(o.failed) for o in outcomes},
            inside + outside,
            [(s, held[s.trace.id]) for s in held_in + held_rest],
        )

        expected = [{"key": "ai_product", "value": ["batch"], "operator": "exact", "type": "event"}]
        assert filters == (expected if expect_filter else [])

    @parameterized.expand(
        [
            # The segment fails 24 of its 100 traces, so the scoped check stands and shows the segment's rate.
            ("segment_rate_shown", 100, True, 24, 100),
            # 24 of 60 is past the fit limit, so the check runs on all traffic and shows that rate.
            ("segment_too_noisy_on_its_own", 60, False, 26, 300),
        ]
    )
    def test_rate_describes_the_traces_the_check_runs_on(
        self, _name: str, segment_size: int, filtered: bool, failed: int, sample_size: int
    ) -> None:
        inside, inside_outcomes = _population("in", "batch", segment_size, 24)
        outside, outside_outcomes = _population("out", "chat", 240, 2)
        held_in, held_in_outcomes = _population("hin", "batch", 20, 4, held_out=True)
        held_rest, held_rest_outcomes = _population("hout", "chat", 80, 1, held_out=True)
        measurement = Measurement(
            check=adapters.unrecovered_errors([]),
            main=outside_outcomes + inside_outcomes,
            held_out=held_in_outcomes + held_rest_outcomes,
        )

        proposal = ranking.code_check_proposal(
            measurement,
            TraceSample(main=outside + inside, held_out=held_in + held_rest),
            PROFILE,
            similar_evaluation_id=None,
        )

        assert proposal is not None
        assert bool(proposal.filters) is filtered
        assert (proposal.measured_failure_rate, proposal.sample_size) == (failed / sample_size, sample_size)
        assert all(evidence.trace_id.startswith("in") for evidence in proposal.evidence) is filtered
        in_scope = segment_size if filtered else segment_size + 240
        assert proposal.estimated_weekly_runs == round(PROFILE.traces * in_scope / (segment_size + 240))


def _proposal(kind: str, score: float, key: str) -> ranking.Proposal:
    return ranking.Proposal(
        kind=kind,
        template_key=key,
        dedupe_key=key,
        headline=key,
        outcome="",
        reason="",
        draft={},
        filters=[],
        rollout_percentage=100,
        measured_failure_rate=None,
        sample_size=None,
        evidence=[],
        score=score,
    )


def test_pick_keeps_cards_diverse_and_drops_unscored() -> None:
    proposals = [
        _proposal("new_hog", 3.0, "a"),
        _proposal("new_hog", 2.5, "b"),
        _proposal("new_hog", 2.0, "c"),
        _proposal("new_llm_judge", 1.0, "d"),
        _proposal("fix_eval", 0.0, "e"),
    ]
    assert [p.dedupe_key for p in ranking.pick(proposals)] == ["a", "b", "d"]
    assert ranking.pick([proposals[4]]) == []


@parameterized.expand(
    [
        ("small_team_runs_on_everything", 500, 100.0, 500),
        ("p99_team", 1_100_000, 0.09, 990),
        ("largest_team", 26_000_000, 0.01, 2600),
    ]
)
def test_judge_rollout_stays_near_the_weekly_budget(
    _name: str, weekly_units: int, rollout: float, weekly_runs: int
) -> None:
    cost = ranking.judge_cost(weekly_units, None, ranking.DEFAULT_JUDGE_MODEL)
    assert (cost.rollout_percentage, cost.weekly_runs) == (rollout, weekly_runs)


@parameterized.expand(
    [
        ("last_generation_matches", "batch", (), True),
        ("an_earlier_generation_matches", "chat", ("batch",), True),
        ("no_generation_matches", "chat", (), False),
        # batch-2 normalizes to the same segment, but the live filter compares the exact value.
        ("only_a_sibling_value_matches", "batch-2", (), False),
    ]
)
def test_a_filtered_check_runs_where_any_generation_matches(
    _name: str, last: str, earlier: tuple[str, ...], in_scope: bool
) -> None:
    filters = [{"key": "ai_product", "value": ["batch"], "operator": "exact", "type": "event"}]
    assert ranking._in_scope(filters, _sampled("t", last, earlier=earlier)) is in_scope


# Above the 1,000-run weekly budget the rollout shrinks, so generations and traces both land near 1,000.
@parameterized.expand([("generation", 1000), ("trace", 1000), ("session", 100)])
def test_a_screened_judge_counts_runs_in_its_own_unit(target: str, weekly_units: int) -> None:
    result = ranking.ScreeningResult(template_key="prompt_injection", screened=10, flagged=[("t1", "flagged")] * 3)
    sample = TraceSample(main=[_sampled("t1", "chat")], held_out=[])

    proposal = ranking.screened_proposal(
        result, PROFILE, sample, target=target, judge_model=ranking.DEFAULT_JUDGE_MODEL, similar_evaluation_id=None
    )

    assert proposal is not None and proposal.estimated_weekly_runs == weekly_units


def test_a_screened_rate_holds_only_for_traces_with_an_answer() -> None:
    result = ranking.ScreeningResult(template_key="user_correction", screened=10, flagged=[("t1", "flagged")] * 5)

    def score(main: list[SampledTrace]) -> float:
        proposal = ranking.screened_proposal(
            result,
            PROFILE,
            TraceSample(main=main, held_out=[]),
            target="trace",
            judge_model=ranking.DEFAULT_JUDGE_MODEL,
            similar_evaluation_id=None,
        )
        assert proposal is not None
        return proposal.score

    answered = [_sampled(f"a{i}", "chat") for i in range(10)]
    silent = [replace(_sampled(f"s{i}", "chat"), final_text="") for i in range(10)]
    assert score(answered[:5] + silent[:5]) < score(answered)


@parameterized.expand(
    [
        ("generation_reads_its_own_input", "generation", [5000.0], 1200.0),
        ("trace_reads_its_generations", "trace", [5000.0, 7000.0], 6000.0),
        ("trace_stops_at_the_transcript_cap", "trace", [400_000.0], 37_500.0),
        ("session_reads_its_traces", "session", [5000.0], 50_000.0),
    ]
)
def test_judge_tokens_per_run(_name: str, target: str, trace_tokens: list[float], expected: float) -> None:
    traces = [replace(_sampled(f"t{i}", "chat"), input_tokens=tokens) for i, tokens in enumerate(trace_tokens)]
    # PROFILE holds 1,000 traces in 100 sessions, 10 traces each.
    assert ranking.mean_unit_tokens(target, PROFILE, TraceSample(main=traces, held_out=[])) == expected


def test_traces_without_a_session_leave_the_session_price_alone() -> None:
    traces = [replace(_sampled("t0", "chat"), input_tokens=5000.0)]
    profile = replace(PROFILE, traces=PROFILE.traces * 2)

    assert ranking.mean_unit_tokens("session", profile, TraceSample(main=traces, held_out=[])) == 50_000.0


def test_a_long_dedupe_key_is_bounded_and_stable() -> None:
    key = "gap:" + "segment_" * 40 + "=value:findings[].priority"
    bounded = ranking.bounded_key(key)
    assert len(bounded) <= ranking.MAX_DEDUPE_KEY
    assert bounded == ranking.bounded_key(key) != ranking.bounded_key(key + "x")
    assert ranking.bounded_key("gap:lens=security:findings[].priority") == "gap:lens=security:findings[].priority"


def test_every_provider_default_model_has_a_price() -> None:
    assert set(DEFAULT_MODEL_BY_PROVIDER.values()) <= set(ranking.MODEL_PRICES)


@parameterized.expand(
    [
        ("urgency", ("P0",), "deserves that level"),
        ("status", ("P0",), "in that state"),
        ("label", ("P0",), "fits that label"),
        # Overusing the bottom of a scale is not an overstated level.
        ("urgency", ("low",), "fits that label"),
    ]
)
def test_a_gap_judge_checks_what_the_field_means(meaning: FieldMeaning, values: tuple[str, ...], phrase: str) -> None:
    gap = StructuredGap(
        field="findings[].priority",
        meaning=meaning,
        values=values,
        segment_key="ai_product",
        segment_value="chat",
        segment_rate=0.5,
        other_rate=0.05,
        segment_items=40,
        other_items=40,
        examples=(),
    )
    sample = TraceSample(main=[_sampled("t1", "chat")], held_out=[])

    proposal = ranking.gap_proposal(
        gap, sample, PROFILE, judge_model=ranking.DEFAULT_JUDGE_MODEL, similar_evaluation_id=None
    )

    assert phrase in proposal.draft["evaluation_config"]["prompt"]
