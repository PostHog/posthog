from parameterized import parameterized

from products.ai_observability.backend.logic.eval_suggestions import adapters, cards, catalog
from products.ai_observability.backend.logic.eval_suggestions.coverage import EvalFix, FilterChange
from products.ai_observability.backend.logic.eval_suggestions.profile import FieldMeaning, StructuredGap


@parameterized.expand(
    [
        ("all_traffic", 2, 250, None, "Flags traces where", "2 of 250 sampled traces flagged"),
        ("one_unit", 1, 1, None, "Flags traces where", "1 of 1 sampled trace flagged"),
        (
            "filtered_check_names_its_segment",
            5,
            100,
            "batch",
            "Flags batch traces where",
            "5 of 100 sampled traces flagged",
        ),
    ]
)
def test_a_code_check_keeps_its_title_and_reports_counts_from_its_sample(
    _name: str, failed: int, of: int, segment: str | None, opening: str, observation: str
) -> None:
    text = cards.code_check_text(adapters.unrecovered_errors([]), failed, of, segment)

    assert text.headline == "Tool or model calls that never succeed"
    assert text.outcome.startswith(opening)
    assert (text.observation, text.observation_scope) == (observation, "Sampled from the last 7 days")


@parameterized.expand([("sentiment", "generation"), ("user_correction", "session")])
def test_a_screened_judge_counts_the_traces_screening_read(key: str, target: str) -> None:
    text = cards.judge_text(catalog.template(key), target, 5, 40)

    assert text.observation == "5 of 40 sampled traces flagged by a screening model"


@parameterized.expand(
    [
        (
            "top_priorities_read_as_urgent",
            "findings[].priority",
            "urgency",
            ("P0", "P1"),
            "Security findings marked urgent",
            "32% of sampled security findings are marked urgent, compared with 3% of findings elsewhere",
        ),
        (
            "low_priorities_keep_their_value",
            "findings[].priority",
            "urgency",
            ("P3",),
            'Security findings marked "P3"',
            '32% of sampled security findings are marked "P3", compared with 3% of findings elsewhere',
        ),
        (
            "categories_read_as_labels",
            "findings[].category",
            "label",
            ("bug", "regression"),
            'Security findings labeled "bug" or "regression"',
            '32% of sampled security findings are labeled "bug" or "regression", compared with 3% of findings elsewhere',
        ),
    ]
)
def test_a_gap_card_keeps_rates_out_of_its_title(
    _name: str, field: str, meaning: FieldMeaning, values: tuple[str, ...], title: str, observation: str
) -> None:
    gap = StructuredGap(
        field=field,
        meaning=meaning,
        values=values,
        segment_key="review_lens",
        segment_value="security",
        segment_rate=0.32,
        other_rate=0.032,
        segment_items=100,
        other_items=300,
        examples=(),
    )
    text = cards.gap_text(gap)
    assert (text.headline, text.observation) == (title, observation)


@parameterized.expand(
    [
        ("judge", "llm_judge", "Check that its prompt can tell a pass from a fail."),
        ("hog_has_no_prompt", "hog", "Check that its code can return both results."),
    ]
)
def test_one_outcome_card_advice_fits_the_eval_type(_name: str, evaluation_type: str, advice: str) -> None:
    fix = EvalFix(
        evaluation_id="e1",
        evaluation_name="Grounded",
        evaluation_type=evaluation_type,
        problem="one_outcome",
        patch=None,
        weekly_units=0,
        window_days=7,
        dominant_outcome="true",
        dominant_share=0.99,
        graded_runs=1_200_000,
    )
    text = cards.fix_text(fix)
    assert text.outcome == f"It returned true on 99% of 1,200,000 graded runs in the last 30 days. {advice}"


@parameterized.expand(
    [
        (
            "stale_value",
            True,
            FilterChange(key="ai_product", old_value="signals", new_value="signals_scout"),
            "A filter value no longer appears in your events",
            "No AI events from the last 14 days have ai_product = signals. The closest value sent is signals_scout. "
            "The fix changes the filter to that value.",
        ),
        (
            # No matching events is a bounded observation, not an execution failure, and new events can match.
            "no_match",
            True,
            None,
            "No recent events match this eval",
            "No AI events from the last 14 days match this eval's filters. "
            "If you still expect traffic, check its filters.",
        ),
        (
            "no_condition_sets",
            False,
            None,
            "This eval has no trigger conditions",
            "It's enabled but has no condition sets, and it has no runs in the last 30 days. "
            "Add a condition to choose what it checks.",
        ),
    ]
)
def test_an_existing_eval_notice_names_the_condition_the_run_observed(
    _name: str, has_conditions: bool, change: FilterChange | None, headline: str, outcome: str
) -> None:
    fix = EvalFix(
        evaluation_id="e1",
        evaluation_name="Grounded",
        evaluation_type="llm_judge",
        problem="no_runs",
        patch=None,
        weekly_units=0,
        window_days=14,
        filter_change=change,
        has_conditions=has_conditions,
    )
    text = cards.fix_text(fix)
    assert (text.headline, text.outcome) == (headline, outcome)
