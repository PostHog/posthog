from parameterized import parameterized

from products.ai_observability.backend.eval_suggestions import adapters, cards
from products.ai_observability.backend.eval_suggestions.profile import FieldMeaning, StructuredGap


@parameterized.expand(
    [
        ("rare_failure_reads_as_one_in_n", 2 / 250, None, "1 in 125 traces ends on a failed call"),
        ("common_failure_reads_as_a_share", 0.12, None, "12% of traces end on a failed call"),
        ("filtered_check_names_its_segment", 0.05, "batch", "1 in 20 batch traces ends on a failed call"),
    ]
)
def test_code_check_headline(_name: str, failure_rate: float, segment: str | None, expected: str) -> None:
    assert cards.code_check_text(adapters.unrecovered_errors([]), failure_rate, segment).headline == expected


@parameterized.expand(
    [
        (
            "top_priorities_read_as_urgent",
            "findings[].priority",
            "urgency",
            ("P0", "P1"),
            (0.32, 0.032),
            "Security findings are marked urgent 10× more often",
        ),
        (
            "low_priorities_keep_their_value",
            "findings[].priority",
            "urgency",
            ("P3",),
            (0.6, 0.2),
            'Security findings are marked "P3" 3× more often',
        ),
        (
            "categories_read_as_labels",
            "findings[].category",
            "label",
            ("bug", "regression"),
            (0.4, 0.1),
            'Security findings are labeled "bug" or "regression" 4× more often',
        ),
        (
            "no_ratio_when_other_segments_never_use_the_value",
            "findings[].priority",
            "urgency",
            ("P0",),
            (0.32, 0.0),
            "32% of security findings are marked urgent, compared with 0% elsewhere",
        ),
    ]
)
def test_gap_headline(
    _name: str,
    field: str,
    meaning: FieldMeaning,
    values: tuple[str, ...],
    rates: tuple[float, float],
    expected: str,
) -> None:
    gap = StructuredGap(
        field=field,
        meaning=meaning,
        values=values,
        segment_key="review_lens",
        segment_value="security",
        segment_rate=rates[0],
        other_rate=rates[1],
        segment_items=100,
        other_items=300,
        examples=(),
    )
    assert cards.gap_text(gap, cost="").headline == expected
