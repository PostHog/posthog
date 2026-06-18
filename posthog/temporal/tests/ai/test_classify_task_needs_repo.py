from parameterized import parameterized

from posthog.temporal.ai.slack_app.activities.classifiers import classify_task_needs_repo


class TestClassifyTaskNeedsRepo:
    @parameterized.expand(
        [
            (
                "product_debug_automation",
                "debug why the automation that sends PostHog AI Feedback always gives a thumbs down",
                False,
            ),
            (
                "product_debug_destination",
                "investigate the slack destination configuration for this automation",
                False,
            ),
            (
                "product_debug_report_not_repo",
                "debug why this dashboard report always shows a thumbs down",
                False,
            ),
            (
                "explicit_repo_request",
                "open a PR in posthog/posthog to fix this serializer",
                True,
            ),
        ]
    )
    def test_heuristic_classification(self, _name, text, expected):
        result = classify_task_needs_repo(text, [{"user": "Alessandro", "text": text}])
        assert result is expected
