from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import serializers

from products.ai_observability.backend.facade.contracts import EvaluationPreviewSettle
from products.ai_observability.backend.hog import compile_ai_observability_hog, hog_compile_error_message
from products.ai_observability.backend.logic.evaluations.preview_outcomes import preview_grader
from products.ai_observability.backend.logic.evaluations.preview_queries import generation_io_preview
from products.ai_observability.backend.logic.evaluations.preview_units import (
    preview_unit_count,
    session_quiet_period_seconds,
    trace_window_seconds,
)

DAY = 24 * 60 * 60


class TestPreviewRules(SimpleTestCase):
    @parameterized.expand(
        [
            ("inactivity_waits_its_quiet_period", {"strategy": "inactivity", "quiet_period_seconds": 600}, 600),
            ("inactivity_default", {"strategy": "inactivity"}, 60 * 60),
            ("no_strategy_reads_the_quiet_period", {"quiet_period_seconds": 300}, 300),
            ("fixed_window_waits_its_window", {"strategy": "fixed_window", "window_seconds": 900}, 900),
            ("fixed_window_default", {"strategy": "fixed_window"}, 30 * 60),
            ("fixed_window_ignores_a_quiet_period", {"strategy": "fixed_window", "quiet_period_seconds": 60}, 30 * 60),
            ("a_week_long_window_stops_at_a_day", {"strategy": "fixed_window", "window_seconds": 7 * DAY}, DAY),
        ]
    )
    def test_session_preview_waits_as_long_as_the_evaluation_would(
        self, _name: str, settle: dict[str, Any], expected: int
    ) -> None:
        self.assertEqual(session_quiet_period_seconds(EvaluationPreviewSettle(**settle)), expected)

    @parameterized.expand([({}, 30 * 60), ({"window_seconds": 60}, 60), ({"window_seconds": DAY}, 2 * 60 * 60)])
    def test_trace_preview_window(self, settle: dict[str, Any], expected: int) -> None:
        self.assertEqual(trace_window_seconds(EvaluationPreviewSettle(**settle)), expected)

    @parameterized.expand(
        [
            ("generation", None, 5),
            ("trace", 10, 10),
            # A session test covers three sessions, so listing more would leave rows that never get a result.
            ("session", None, 3),
            ("session", 10, 3),
        ]
    )
    def test_preview_lists_no_more_units_than_a_test_covers(
        self, target: Any, requested: int | None, expected: int
    ) -> None:
        self.assertEqual(preview_unit_count(target, requested), expected)

    @parameterized.expand(
        [
            (
                "openai_image_url",
                [{"type": "text", "text": "Describe this photo"}, {"type": "image_url", "image_url": {"url": "u"}}],
                "Describe this photo [image]",
            ),
            (
                "anthropic_base64_image",
                [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "aGVsbG8="}},
                    {"type": "text", "text": "Describe this photo"},
                ],
                "[image] Describe this photo",
            ),
            (
                "vercel_file_part",
                [
                    {"type": "file", "data": "https://example.com/cat.png", "mediaType": "image/png"},
                    {"type": "text", "text": "Describe this photo"},
                ],
                "[image] Describe this photo",
            ),
        ]
    )
    def test_generation_preview_marks_media_instead_of_printing_it(
        self, _name: str, content: list[dict[str, Any]], expected: str
    ) -> None:
        preview = generation_io_preview(
            {
                "event": "$ai_generation",
                "properties": {
                    "$ai_input": [{"role": "user", "content": content}],
                    "$ai_output_choices": [{"role": "assistant", "content": "A cat"}],
                },
            }
        )

        self.assertEqual((preview.input, preview.output), (expected, "A cat"))

    @parameterized.expand(
        [
            ("boolean_pass", "boolean", {}, True, None, None, "pass"),
            ("boolean_fail", "boolean", {}, False, None, None, "fail"),
            ("detector_inverts", "boolean", {"true_is_failure": True}, True, None, None, "fail"),
            ("not_applicable", "boolean", {"allows_na": True}, None, None, None, "na"),
            ("error_wins_over_a_result", "boolean", {}, True, None, "boom", "error"),
            ("numeric_rule", "numeric", {"passing_rule": {"operator": "gte", "threshold": 4}}, None, 3.0, None, "fail"),
            ("numeric_without_a_rule_is_ungraded", "numeric", {}, None, 3.0, None, None),
        ]
    )
    def test_preview_row_outcome(
        self,
        _name: str,
        output_type: str,
        output_config: dict[str, Any],
        result: bool | None,
        score: float | None,
        error: str | None,
        expected: str | None,
    ) -> None:
        grader = preview_grader(output_type, output_config)

        self.assertEqual(grader.outcome(error=error, result=result, score=score, categories=None), expected)

    @parameterized.expand(
        [
            ("syntax_error_names_its_line", "let ok := true\nreturn ok +", "Compilation error on line 2: "),
            ("hyphenated_property", "return event.properties.$ai-foo", "Compilation error: Hyphens are not supported"),
        ]
    )
    def test_hog_compile_error_reads_as_a_sentence(self, _name: str, source: str, expected_start: str) -> None:
        with self.assertRaises(serializers.ValidationError) as raised:
            compile_ai_observability_hog(source, "destination")

        message = hog_compile_error_message(source, raised.exception)
        self.assertTrue(message.startswith(expected_start), message)
        self.assertNotIn("ErrorDetail", message)
