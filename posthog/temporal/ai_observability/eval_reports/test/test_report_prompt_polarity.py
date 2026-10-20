from django.test import SimpleTestCase


class TestReportPromptPolarity(SimpleTestCase):
    def _prompt(self, *, true_is_failure: bool) -> str:
        from posthog.temporal.ai_observability.eval_reports.report_agent.prompts import build_eval_report_system_prompt

        return build_eval_report_system_prompt(
            evaluation_name="Struggle detector",
            evaluation_description="",
            evaluation_prompt="",
            evaluation_type="llm_judge",
            output_type="boolean",
            period_start="2026-04-08T14:00:00+00:00",
            period_end="2026-04-08T15:00:00+00:00",
            true_is_failure=true_is_failure,
        )

    def test_detector_prompt_says_a_true_result_is_reported_as_a_fail(self):
        prompt = self._prompt(true_is_failure=True)
        self.assertIn("reported as a fail", prompt)

    def test_default_prompt_keeps_the_pass_on_true_story(self):
        prompt = self._prompt(true_is_failure=False)
        self.assertIn("satisfied the configured criteria", prompt)
        self.assertNotIn("reported as a fail", prompt)
