from parameterized import parameterized

from posthog.schema import LLMTrace

from products.ai_observability.backend.eval_suggestions import adapters, ranking
from products.ai_observability.backend.eval_suggestions.measure import Measurement, Outcome, SampledTrace, TraceSample
from products.ai_observability.backend.eval_suggestions.profile import TeamProfile


def _sampled(trace_id: str, product: str, held_out: bool = False) -> SampledTrace:
    return SampledTrace(
        trace=LLMTrace(id=trace_id, createdAt="2026-11-01T00:00:00Z", distinctId="user", events=[]),
        held_out=held_out,
        spans_days=False,
        segments={"ai_product": product},
        raw_segments={"ai_product": product},
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
    generations_by_days_ago={0: 700, 1: 700},
    traces_by_days_ago={0: 150, 1: 150},
    tool_call_share=0.5,
    tool_counts={},
    dispatcher_tools=(),
    session_share=0.0,
    error_share=0.01,
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
