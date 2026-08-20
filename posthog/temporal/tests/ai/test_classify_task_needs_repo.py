from unittest.mock import MagicMock, patch

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
            # Analytics / data asks — the common no-GitHub case from the
            # 2026-06-17 UPchieve report. None of these should wall a user
            # behind the Connect-GitHub gate.
            ("analytics_dau", "what was our DAU yesterday?", False),
            ("analytics_event_count", "how many pageview events did we get last week", False),
            ("analytics_trend", "show me the trend of signups over the last 30 days", False),
            ("analytics_funnel", "build a funnel from landing page to signup", False),
            ("analytics_retention", "what's our 7-day retention for new users", False),
            ("analytics_breakdown", "break down events by browser", False),
            ("analytics_persons", "find persons who triggered checkout last week", False),
            ("analytics_cohort", "create a cohort of power users", False),
            ("analytics_hogql", "write a hogql query to count signups by country", False),
            ("flag_search", "find the feature flag for the new onboarding", False),
            ("replay_question", "show me session replays of failed checkouts", False),
        ]
    )
    def test_heuristic_classification(self, _name, text, expected):
        result = classify_task_needs_repo(text, [{"user": "Alessandro", "text": text}])
        assert result is expected

    @parameterized.expand(
        [
            # Each ask carries a product noun that short-circuits the heuristic to
            # no-repo unless the CI vocabulary vetoes it first.
            ("flaky_test_named_after_a_feature", "the experiment insight test is flaky"),
            ("merge_queue", "the merge queue keeps failing on the experiment insight tests"),
        ]
    )
    def test_ci_vocabulary_leaves_the_call_to_the_llm(self, _name, text):
        assert self._run_with_llm_content(text, '{"needs_repo": true}') is True

    @parameterized.expand(
        [
            # Both halves of a CI ask, split across a thread the way people actually talk.
            # A vocabulary that pairs any subject word with any failure word reads these as
            # CI and spends a discovery-agent sandbox run on an analytics question.
            (
                "tests_and_errors_in_an_analytics_thread",
                [
                    {"user": "amy", "text": "we ran some tests on the signup funnel yesterday"},
                    {"user": "bo", "text": "the numbers look off, error rate is way up in the dashboard"},
                ],
                "why did conversion drop?",
            ),
            (
                "master_chatter_beside_a_product_bug",
                [
                    {"user": "amy", "text": "just merged that to master"},
                    {"user": "bo", "text": "the survey widget throws an error on mobile"},
                ],
                "what does the data say?",
            ),
        ]
    )
    def test_product_ask_short_circuits_before_the_llm(self, _name, thread_messages, event_text):
        assert self._run_with_llm_content(event_text, '{"needs_repo": true}', thread_messages) is False

    def test_llm_path_returns_true_when_model_says_needs_repo(self):
        """Ask with no heuristic signal — classifier must defer to the LLM."""
        text = "open a PR in posthog/posthog to fix this serializer"
        result = self._run_with_llm_content(text, '{"needs_repo": true}')
        assert result is True

    @parameterized.expand(
        [
            # JSON booleans round-trip to Python bools as expected.
            ("json_bool_true", '{"needs_repo": true}', True),
            ("json_bool_false", '{"needs_repo": false}', False),
            # Haiku occasionally stringifies the bool — bool("false") would be
            # True and silently flip the defensive bias. Parse strings instead.
            ("stringified_true", '{"needs_repo": "true"}', True),
            ("stringified_false", '{"needs_repo": "false"}', False),
            ("stringified_true_upper", '{"needs_repo": "TRUE"}', True),
            ("stringified_padded", '{"needs_repo": " true "}', True),
            # Garbage values default to False (no-repo) per the defensive bias.
            ("unexpected_int", '{"needs_repo": 1}', False),
            ("unexpected_null", '{"needs_repo": null}', False),
            ("missing_key", "{}", False),
        ]
    )
    def test_llm_response_shapes(self, _name, content, expected):
        text = "ambiguous ask the heuristic does not catch"
        result = self._run_with_llm_content(text, content)
        assert result is expected

    def _run_with_llm_content(
        self, text: str, content: str, thread_messages: list[dict[str, str]] | None = None
    ) -> bool:
        fake_response = MagicMock()
        fake_response.choices = [MagicMock(message=MagicMock(content=content))]
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = fake_response
        with patch(
            "posthog.temporal.ai.slack_app.activities.classifiers.get_llm_client",
            return_value=fake_client,
        ):
            return classify_task_needs_repo(text, thread_messages or [{"user": "Alessandro", "text": text}])

    def test_llm_failure_defaults_to_false(self):
        """A flaky LLM call must not wall users behind the Connect-GitHub gate."""
        text = "something the heuristic can't classify on its own"
        with patch(
            "posthog.temporal.ai.slack_app.activities.classifiers.get_llm_client",
            side_effect=RuntimeError("boom"),
        ):
            result = classify_task_needs_repo(text, [{"user": "Alessandro", "text": text}])
        assert result is False
