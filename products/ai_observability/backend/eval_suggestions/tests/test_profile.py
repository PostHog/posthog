from parameterized import parameterized

from products.ai_observability.backend.eval_suggestions.profile import (
    StructuredOutput,
    find_structured_gaps,
    gap_holds,
    normalize_segment_value,
    parse_structured,
    short_string_fields,
)


def _outputs(lens: str, values: list[str], traces: int, field: str = "findings[].priority") -> list[StructuredOutput]:
    return [
        StructuredOutput(trace_id=f"{lens}-{index}", segments={"lens": lens}, fields={field: values})
        for index in range(traces)
    ]


class TestStructuredGaps:
    def test_finds_the_segment_that_overuses_severe_values(self) -> None:
        outputs = (
            _outputs("security", ["P0", "P1", "P2", "P3"], 20)
            + _outputs("performance", ["P2", "P3", "P3", "P2"], 15)
            + _outputs("correctness", ["P2", "P3", "P2", "P3"], 14)
            + _outputs("correctness", ["P1", "P2", "P3", "P3"], 1)
        )

        gaps = find_structured_gaps(outputs)

        assert [(g.segment_value, g.values, g.field) for g in gaps] == [
            ("security", ("P0", "P1"), "findings[].priority")
        ]
        assert gaps[0].segment_rate == 0.5
        assert (
            gap_holds(gaps[0], _outputs("security", ["P1", "P3"], 6) + _outputs("performance", ["P3", "P2"], 6)) is True
        )
        assert (
            gap_holds(gaps[0], _outputs("security", ["P3", "P3"], 6) + _outputs("performance", ["P1", "P2"], 6))
            is False
        )

    def test_tests_severe_values_as_one_set(self) -> None:
        # P1 alone is 2.5x its siblings, under the 3x gap ratio, but P0 and P1 together are 5x.
        outputs = _outputs("security", ["P0", "P1", "P2", "P3"], 20) + _outputs(
            "performance", ["P1", "P2", "P3", "P3", "P2", "P3", "P2", "P3", "P2", "P3"], 15
        )

        assert [g.values for g in find_structured_gaps(outputs)] == [("P0", "P1")]

    @parameterized.expand(
        [
            ("same_mix_everywhere", ["P1", "P2", "P3", "P3"], ["P1", "P2", "P3", "P3"], 20, "findings[].priority"),
            ("too_few_items", ["P0", "P1"], ["P2", "P3"], 10, "findings[].priority"),
            # 200 items on each side, but each from a single response, so nothing independent backs the gap.
            (
                "one_long_response_per_segment",
                ["P0", "P1", "P2", "P3"] * 50,
                ["P2", "P3"] * 100,
                1,
                "findings[].priority",
            ),
            ("identifier_field", ["api/auth.py", "api/keys.py"], ["ui/list.tsx", "ui/form.tsx"], 20, "findings[].file"),
            # The same split as a priority gap, on a field a card cannot name in plain words.
            (
                "field_without_a_plain_meaning",
                ["P0", "P1", "P2", "P3"],
                ["P2", "P3", "P3", "P2"],
                20,
                "findings[].grade",
            ),
        ]
    )
    def test_no_gap(self, _name: str, security: list[str], performance: list[str], traces: int, field: str) -> None:
        outputs = _outputs("security", security, traces, field) + _outputs("performance", performance, traces, field)
        assert find_structured_gaps(outputs) == []

    def test_flagged_items_from_a_single_trace_are_no_gap(self) -> None:
        outputs = (
            _outputs("security", ["P0", "P1"] * 20, 1)
            + _outputs("security", ["P2", "P3"], 19)
            + _outputs("performance", ["P2", "P3", "P3", "P2"], 20)
        )
        assert find_structured_gaps(outputs) == []

    def test_reads_enum_fields_from_fenced_json(self) -> None:
        parsed = parse_structured(
            '```json\n{"findings": [{"priority": "P1", "title": "A long sentence about a bug here"}]}\n```'
        )
        assert short_string_fields(parsed) == {"findings[].priority": ["P1"]}


@parameterized.expand([("security-2", "security"), ("lens_10", "lens"), ("performance", "performance")])
def test_segment_values_drop_numeric_suffixes(raw: str, expected: str) -> None:
    assert normalize_segment_value(raw) == expected
