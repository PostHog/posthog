import json
from dataclasses import replace

from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import LLMTrace

from posthog.hogql import ast
from posthog.hogql.compiler.bytecode import create_bytecode
from posthog.hogql.property import property_to_expr

from products.ai_observability.backend.llm import DEFAULT_MODEL_BY_PROVIDER
from products.ai_observability.backend.logic.eval_suggestions import adapters, prices, ranking
from products.ai_observability.backend.logic.eval_suggestions.call_review import ReviewCard, ReviewExample
from products.ai_observability.backend.logic.eval_suggestions.call_review_queries import CallTypeRow, SnippetMatches
from products.ai_observability.backend.logic.eval_suggestions.judge_calibration import Calibration, CodeCheck
from products.ai_observability.backend.logic.eval_suggestions.measure import (
    Measurement,
    Outcome,
    SampledTrace,
    TraceSample,
)
from products.ai_observability.backend.logic.eval_suggestions.profile import FieldMeaning, StructuredGap, TeamProfile

from common.hogvm.python.execute import execute_bytecode


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
            ("rare_failure_kept", (5, 250), (0, 100), True),
            ("check_that_does_not_fit_the_app", (80, 250), (30, 100), False),
            ("no_failures", (0, 250), (0, 100), False),
            ("four_failures_are_not_enough", (4, 250), (0, 100), False),
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


@parameterized.expand(
    [
        ("small_team_checks_every_trace", 1000, 100.0, 1000),
        ("largest_team_gets_a_sample", 13_500_000, 0.74, 99_900),
    ]
)
def test_a_code_check_stays_near_the_weekly_run_cap(_name: str, traces: int, rollout: float, weekly_runs: int) -> None:
    measurement, sample = _measurement((5, 250), (0, 100))

    proposal = ranking.code_check_proposal(
        measurement, sample, replace(PROFILE, traces=traces), similar_evaluation_id=None
    )

    assert proposal is not None
    assert (proposal.rollout_percentage, proposal.estimated_weekly_runs) == (rollout, weekly_runs)


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
    result = ranking.ScreeningResult(template_key="user_correction", screened=10, flagged=[("t1", "flagged")] * 3)
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
    assert set(DEFAULT_MODEL_BY_PROVIDER.values()) <= set(prices.MODEL_PRICES)


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


def _messages(system: str) -> list[dict[str, str]]:
    return [{"role": "system", "content": system}, {"role": "user", "content": "The request"}]


# The system prompts hold quotes and line breaks, which the condition matcher prints escaped.
SUMMARIZER = _messages('You summarize one trace for an engineer.\nEach bullet\'s "line_refs" holds one reference.')
# Its longest plain text follows a line break, which the stored JSON escapes.
ROUTER = _messages("Route it.\nAnswer with the name of the single tool to call.")
TRANSLATOR = _messages("You translate the reply into the language of the user.")
SUPPORT_IN_JAPANESE = _messages(
    "あなたはサポート担当です。返金の日付を約束しないでください。\n「返金」は丁寧に説明します。"
)
# The team's call type that the card does not cover, by test case.
OTHER_CALL_TYPES = {"input_shared_with_another_call_type": [SUMMARIZER[0], {"role": "user", "content": "Another"}]}


def _call_type(source: str, name: str, calls: int = 100, messages: list[dict[str, str]] | None = None) -> CallTypeRow:
    example_input = json.dumps(messages, ensure_ascii=False) if messages else ""
    return CallTypeRow(source=source, name=name, calls=calls, model="gpt-5-mini", example_input=example_input)


def _review_card(call_types: list[CallTypeRow]) -> ReviewCard:
    return ReviewCard(
        title="Replies promise refund dates",
        summary="Flags replies that promise a refund date",
        rule="A reply fails when it names a date or day by which the refund arrives.",
        why="The prompt says never to promise a date",
        call_types=call_types,
        labels={},
        failed=4,
        of=20,
        examples=[ReviewExample(trace_id="t1", reason="Promised Friday")],
        judge_prompt="Does the reply avoid promising a refund date?",
    )


@parameterized.expand(
    [
        (
            "managed_prompts",
            [_call_type("prompt_name", "support-reply"), _call_type("prompt_name", "refund-reply")],
            [
                {
                    "key": "$ai_prompt_name",
                    "value": ["refund-reply", "support-reply"],
                    "operator": "exact",
                    "type": "event",
                }
            ],
            1400,
            71.43,
        ),
        (
            "span_name",
            [_call_type("span_name", "answer")],
            [
                {"key": "$ai_span_name", "value": ["answer"], "operator": "exact", "type": "event"},
                {"key": "$ai_prompt_name", "value": ["is_not_set"], "operator": "is_not_set", "type": "event"},
            ],
            700,
            100.0,
        ),
        # No one property names both, and a judge on every generation would grade mostly calls it does not fit.
        (
            "mixed_properties",
            [_call_type("prompt_name", "support-reply"), _call_type("span_name", "answer")],
            None,
            0,
            0.0,
        ),
        (
            "named_by_input",
            [_call_type("input", "1", messages=SUMMARIZER)],
            [
                {
                    "key": "$ai_input",
                    "value": "You summarize one trace for an engineer",
                    "operator": "icontains",
                    "type": "event",
                }
            ],
            700,
            100.0,
        ),
        (
            "named_by_input_in_japanese",
            [_call_type("input", "1", messages=SUPPORT_IN_JAPANESE)],
            [
                {
                    "key": "$ai_input",
                    "value": "あなたはサポート担当です。返金の日付を約束しないでください。",
                    "operator": "icontains",
                    "type": "event",
                }
            ],
            700,
            100.0,
        ),
        (
            "two_named_by_input",
            [_call_type("input", "1", messages=SUMMARIZER), _call_type("input", "2", messages=ROUTER)],
            [
                {
                    "key": "$ai_input",
                    "value": "Answer with the name of the single tool to call|You summarize one trace for an engineer",
                    "operator": "regex",
                    "type": "event",
                }
            ],
            1400,
            71.43,
        ),
        # Another call type opens with the same prompt, so no text tells the two apart.
        (
            "input_shared_with_another_call_type",
            [_call_type("input", "1", messages=SUMMARIZER)],
            None,
            0,
            0.0,
        ),
    ]
)
def test_a_reviewed_judge_runs_on_the_generations_of_its_call_types(
    _name: str, call_types: list[CallTypeRow], filters: list[dict] | None, weekly_units: int, rollout: float
) -> None:
    card = _review_card(call_types)
    other = _call_type("input", "3", messages=OTHER_CALL_TYPES.get(_name, TRANSLATOR))
    team_call_types = [*call_types, other]

    calibration = Calibration(
        review_fails=5,
        caught=4,
        review_passes=15,
        judged_passes=15,
        false_alarms=0,
        unjudged=0,
        na_on_fails=0,
        na_on_passes=0,
    )

    snippets = {
        c.key: candidates[0]
        for c in call_types
        if (candidates := ranking.prompt_snippets(c, [o for o in team_call_types if o.key != c.key]))
    }
    proposal = ranking.review_proposal(
        card, PROFILE, snippets=snippets, judge_model="gpt-5-mini", calibration=calibration
    )

    if filters is None:
        assert proposal is None
        return
    assert proposal is not None
    assert proposal.filters == filters
    assert not any(isinstance(property_to_expr(f, team=MagicMock()), ast.Constant) for f in proposal.filters)
    # The condition matcher runs the filters on each generation's parsed input.
    for call_type, selected in [*((c, True) for c in call_types), (other, False)]:
        if call_type.source == "input":
            bytecode = [create_bytecode(property_to_expr(f, team=MagicMock())).bytecode for f in proposal.filters]
            properties = {"$ai_input": json.loads(call_type.example_input)}
            assert all(execute_bytecode(b, {"properties": properties}).result for b in bytecode) is selected
    assert proposal.estimated_weekly_runs == min(weekly_units, ranking.WEEKLY_JUDGE_RUNS)
    assert proposal.rollout_percentage == rollout
    busier = replace(PROFILE, generations=100 * PROFILE.generations)
    busier_proposal = ranking.review_proposal(
        card, busier, snippets=snippets, judge_model="gpt-5-mini", calibration=calibration
    )
    assert busier_proposal is not None and busier_proposal.score == proposal.score
    assert proposal.draft["evaluation_config"] == {"prompt": card.judge_prompt}
    assert (proposal.draft["target"], proposal.draft["output_config"]) == ("generation", {"allows_na": True})
    assert (proposal.template_key, proposal.measured_failure_rate, proposal.sample_size) == ("review", 0.2, 20)
    assert proposal.score > 0


PAYMENTS_RULES = (
    "You review pull requests for the payments service and list every risk you find, ordered by how much money "
    "each one could lose for the team"
)


@parameterized.expand(
    [
        # Before stripping, the run of spaces is the longest text.
        (
            "blank_run_before_the_instructions",
            "Answer in one line." + " " * 200 + "\nYou write the release notes for a mobile app",
            "You translate the reply",
            "You write the release notes for a mobile app",
        ),
        (
            "other_prompt_shares_the_start_of_the_run",
            f"{PAYMENTS_RULES}, then you sign off as the payments reviewer",
            f"{PAYMENTS_RULES}, then you sign off as the search reviewer",
            f"{PAYMENTS_RULES}, then you sign off as the payments reviewer"[-ranking.MAX_SNIPPET_CHARS :].strip(),
        ),
    ]
)
def test_a_prompt_offers_text_that_no_other_call_type_holds(_name: str, system: str, other: str, first: str) -> None:
    call_type = _call_type("input", "1", messages=_messages(system))

    snippets = ranking.prompt_snippets(call_type, [_call_type("input", "2", messages=_messages(other))])

    assert snippets[:1] == [first]


@parameterized.expand(
    [
        ("first_selects_its_call_type", [(10, 10), (4, 4)], "first"),
        # The first text also opens other generations, so the judge would grade them too.
        ("first_matches_other_generations", [(100, 10), (4, 4)], "second"),
        ("first_absent_from_the_sample", [(0, 0), (4, 4)], "second"),
        ("none_selects_its_call_type", [(100, 10), (5, 4)], None),
    ]
)
def test_a_snippet_is_chosen_only_when_its_matches_are_its_call_type(
    _name: str, matches: list[tuple[int, int]], chosen: str | None
) -> None:
    counts = [SnippetMatches(matched=matched, in_call_type=in_call_type) for matched, in_call_type in matches]
    assert ranking.choose_snippet(["first", "second"], counts) == chosen


@parameterized.expand(
    [
        ("same_check_reworded", "support-reply", "flags REPLIES that promise a refund date!", False, True),
        ("another_check", "support-reply", "Flags replies not in the user's language", False, False),
        ("another_call_type", "refund-reply", "Flags replies that promise a refund date", False, False),
        ("named_as_the_earlier_card", "support-reply", "Whether customers hear when the money comes back", True, True),
    ]
)
def test_a_reviewed_card_keeps_its_dedupe_key_when_a_later_review_rewords_it(
    _name: str, prompt_name: str, summary: str, named_earlier: bool, same_key: bool
) -> None:
    first = _review_card([_call_type("prompt_name", "support-reply")])
    later = replace(
        first,
        title="Refund dates get promised",
        summary=summary,
        call_types=[_call_type("prompt_name", prompt_name)],
        judge_prompt="Is the customer told when the refund arrives?",
        earlier_key=ranking.review_dedupe_key(first) if named_earlier else "",
    )

    assert (ranking.review_dedupe_key(first) == ranking.review_dedupe_key(later)) is same_key


def test_a_reviewed_code_check_keeps_the_judge_card_identity_and_runs_free() -> None:
    card = _review_card([_call_type("prompt_name", "support-reply")])
    calibration = Calibration(
        review_fails=4,
        caught=4,
        review_passes=16,
        judged_passes=16,
        false_alarms=0,
        unjudged=0,
        na_on_fails=0,
        na_on_passes=0,
    )
    code = CodeCheck(source="return true", calibration=calibration, failed=5, of=25, errors=0)

    proposal = ranking.review_code_proposal(card, PROFILE, snippets={}, code=code)
    judge = ranking.review_proposal(card, PROFILE, snippets={}, judge_model="gpt-5-mini", calibration=calibration)

    assert proposal is not None and judge is not None
    assert (proposal.kind, proposal.template_key, proposal.dedupe_key, proposal.filters) == (
        "new_hog",
        judge.template_key,
        judge.dedupe_key,
        judge.filters,
    )
    assert {k: proposal.draft[k] for k in ("evaluation_type", "evaluation_config", "target", "output_type")} == {
        "evaluation_type": "hog",
        "evaluation_config": {"source": "return true"},
        "target": "generation",
        "output_type": "boolean",
    }
    assert (proposal.measured_failure_rate, proposal.sample_size, proposal.rollout_percentage) == (0.2, 25, 100.0)
    assert (proposal.estimated_weekly_cost_usd, proposal.judge_model) == (None, "")
    assert (proposal.outcome, proposal.observation, proposal.observation_scope) == (
        "Flags replies that promise a refund date.",
        "5 of 25 sampled generations flagged",
        "Sampled from the last day",
    )


@parameterized.expand(
    [
        ("most_calls_break_the_rule", 21, 30, True, {"support-reply"}),
        ("a_minority_breaks_it", 20, 30, False, {"support-reply"}),
        ("too_few_calls_to_tell", 4, 4, False, {"support-reply"}),
        # The prompt name comes from the events, and the team no longer manages a prompt by that name.
        ("prompt_no_longer_managed", 21, 30, True, set()),
    ]
)
def test_a_card_whose_rule_most_calls_break_asks_for_a_prompt_fix(
    _name: str, failed: int, of: int, prompt_bug: bool, managed: set[str]
) -> None:
    card = replace(_review_card([_call_type("prompt_name", "support-reply")]), failed=failed, of=of)

    assert ranking.is_prompt_bug(card) is prompt_bug
    proposal = ranking.prompt_fix_proposal(card, managed)
    assert (proposal.kind, proposal.dedupe_key, proposal.draft.get("prompt_name")) == (
        "fix_prompt",
        ranking.review_dedupe_key(card),
        "support-reply" if managed else None,
    )
