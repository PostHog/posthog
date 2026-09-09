import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.repo_routing_rule import RepoRoutingRule
from posthog.temporal.ai.slack_app.activities.classifiers import (
    classify_posthog_code_task_needs_repo_activity,
    classify_task_needs_repo,
)
from posthog.temporal.ai.slack_app.types import PostHogCodeSlackMentionWorkflowInputs

from products.slack_app.backend.services.slack_messages import SlackThreadMessage


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
        result = classify_task_needs_repo(text, [SlackThreadMessage(user="Alessandro", text=text)])
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
                    SlackThreadMessage(user="amy", text="we ran some tests on the signup funnel yesterday"),
                    SlackThreadMessage(user="bo", text="the numbers look off, error rate is way up in the dashboard"),
                ],
                "why did conversion drop?",
            ),
            (
                "master_chatter_beside_a_product_bug",
                [
                    SlackThreadMessage(user="amy", text="just merged that to master"),
                    SlackThreadMessage(user="bo", text="the survey widget throws an error on mobile"),
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

    def test_routing_rules_bypass_heuristic_and_reach_the_prompt(self):
        text = "the internal metrics dashboard shows a blank page, can you fix it"
        rule = "- The internal metrics dashboard → acme/internal-tools"

        # 'dashboard' short-circuits to no-repo when the team has no rules, so the fix
        # under test is that a configured rule carries the ask through to the LLM.
        assert self._run_with_llm_content(text, '{"needs_repo": true}') is False

        result = self._run_with_llm_content(text, '{"needs_repo": true}', routing_rules=[rule])
        assert result is True
        assert rule in self._last_llm_prompt

    def _run_with_llm_content(
        self,
        text: str,
        content: str,
        thread_messages: list[SlackThreadMessage] | None = None,
        routing_rules: list[str] | None = None,
    ) -> bool:
        fake_response = MagicMock()
        fake_response.choices = [MagicMock(message=MagicMock(content=content))]
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = fake_response
        with patch(
            "posthog.temporal.ai.slack_app.activities.classifiers.get_llm_client",
            return_value=fake_client,
        ):
            result = classify_task_needs_repo(
                text,
                thread_messages or [SlackThreadMessage(user="Alessandro", text=text)],
                routing_rules=routing_rules,
            )
        create_call = fake_client.chat.completions.create.call_args
        self._last_llm_prompt = create_call.kwargs["messages"][0]["content"] if create_call else ""
        return result

    def test_llm_failure_defaults_to_false(self):
        """A flaky LLM call must not wall users behind the Connect-GitHub gate."""
        text = "something the heuristic can't classify on its own"
        with patch(
            "posthog.temporal.ai.slack_app.activities.classifiers.get_llm_client",
            side_effect=RuntimeError("boom"),
        ):
            result = classify_task_needs_repo(text, [SlackThreadMessage(user="Alessandro", text=text)])
        assert result is False


@pytest.mark.django_db
def test_needs_repo_activity_feeds_team_rules_to_the_classifier(team):
    integration = Integration.objects.create(
        team=team, kind="slack", integration_id="T123", sensitive_config={"access_token": "xoxb-test"}
    )
    RepoRoutingRule.objects.create(
        team=team, rule_text="The internal metrics dashboard", repository="acme/internal-tools", priority=0
    )
    text = "the internal metrics dashboard shows a blank page, can you fix it"
    inputs = PostHogCodeSlackMentionWorkflowInputs(
        event={"text": text}, integration_id=integration.id, slack_team_id="T123", user_id=1
    )

    fake_response = MagicMock()
    fake_response.choices = [MagicMock(message=MagicMock(content='{"needs_repo": true}'))]
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_response
    with patch(
        "posthog.temporal.ai.slack_app.activities.classifiers.get_llm_client",
        return_value=fake_client,
    ):
        result = classify_posthog_code_task_needs_repo_activity(
            inputs, text, [SlackThreadMessage(user="Alessandro", text=text)]
        )

    # Without the team's rules the product-term heuristic answers no-repo before the LLM.
    assert result is True
    prompt = fake_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
    assert "The internal metrics dashboard → acme/internal-tools" in prompt
