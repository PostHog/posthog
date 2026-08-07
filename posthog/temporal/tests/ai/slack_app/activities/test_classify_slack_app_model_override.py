from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.temporal.ai.slack_app.activities.classifiers import classify_slack_app_model_override
from posthog.temporal.ai.slack_app.posthog_code_slack_mention import POSTHOG_CODE_SLACK_MENTION_TIMEOUT_SECONDS

from products.slack_app.backend.services.model_catalogue import ModelChoice

CHOICES = (
    ModelChoice("claude", "claude-opus-5", "Claude Opus 5", ("low", "medium", "high", "max")),
    ModelChoice("claude", "claude-fable-5", "Claude Fable 5", ("low", "medium", "high")),
    ModelChoice("codex", "gpt-5.6-sol", "gpt-5.6-sol", ("low", "medium", "high", "max")),
)


class TestClassifySlackAppModelOverride:
    @parameterized.expand(
        [
            (
                "model_and_effort",
                '{"model": "claude-fable-5", "reasoning_effort": "high"}',
                "claude-fable-5",
                "high",
            ),
            (
                "model_only",
                '{"model": "claude-fable-5", "reasoning_effort": null}',
                "claude-fable-5",
                None,
            ),
            # An effort can be asked for without naming a model; the model the run
            # already had stays, and the merge happens at the point of use.
            ("effort_only", '{"model": null, "reasoning_effort": "max"}', None, "max"),
            # Haiku replies are not reliably unfenced through the gateway.
            (
                "fenced_json",
                '```json\n{"model": "claude-fable-5", "reasoning_effort": null}\n```',
                "claude-fable-5",
                None,
            ),
            ("case_insensitive_id", '{"model": "Claude-Fable-5"}', "claude-fable-5", None),
            # An effort the chosen model can't do is dropped where the run's preferences
            # are resolved, not here, so it survives the classifier untouched.
            (
                "model_with_unsupported_effort",
                '{"model": "claude-fable-5", "reasoning_effort": "turbo"}',
                "claude-fable-5",
                "turbo",
            ),
        ]
    )
    def test_returns_requested_choice(self, _name, content, expected_model, expected_effort):
        override = self._classify("use fable for this", content)
        assert override is not None
        assert override.model == expected_model
        assert override.reasoning_effort == expected_effort

    @parameterized.expand(
        [
            # The common case: a mention that merely names a model is not an instruction,
            # and nulls are how the classifier says so.
            ("both_null", '{"model": null, "reasoning_effort": null}'),
            ("fields_missing", "{}"),
            # A model we can't drive is a hallucination or an unsupported ask; either
            # way the run must fall back to the resolved preferences.
            ("unknown_model", '{"model": "gemini-3-pro", "reasoning_effort": null}'),
            ("empty_reply", ""),
            ("prose_reply", "I think they want fable."),
            ("wrong_types", '{"model": 5, "reasoning_effort": []}'),
        ]
    )
    def test_returns_none(self, _name, content):
        assert self._classify("use fable for this", content) is None

    def test_llm_failure_falls_back_to_no_override(self):
        with patch(
            "posthog.temporal.ai.slack_app.activities.classifiers.get_llm_client",
            side_effect=RuntimeError("boom"),
        ):
            assert classify_slack_app_model_override("use fable for this", CHOICES) is None

    def test_reply_is_pinned_to_the_live_catalogue(self):
        """The schema, not the prompt, is what stops the classifier naming a model this
        workspace can't drive. Asking for it in prose was the old guarantee and it only
        held as far as the model chose to cooperate; if the request stops carrying the
        enum, `find_model_choice` silently becomes the only thing standing between a
        hallucinated id and a dropped override.
        """
        fake_client = self._fake_client('{"model": null, "reasoning_effort": null}')
        with patch(
            "posthog.temporal.ai.slack_app.activities.classifiers.get_llm_client",
            return_value=fake_client,
        ):
            classify_slack_app_model_override("use fable for this", CHOICES)

        kwargs = fake_client.chat.completions.create.call_args.kwargs
        schema = kwargs["response_format"]["json_schema"]
        assert schema["strict"] is True
        assert schema["schema"]["properties"]["model"]["enum"] == [
            "claude-opus-5",
            "claude-fable-5",
            "gpt-5.6-sol",
            None,
        ]
        # Which efforts a model supports depends on the model the run lands on, so the
        # effort is deliberately left open here and settled where preferences resolve.
        assert "enum" not in schema["schema"]["properties"]["reasoning_effort"]

    def test_call_is_bounded_so_a_slow_gateway_falls_back(self):
        # The gateway client's own defaults are a 600s read and two retries. Unbounded,
        # the activity's 600s deadline expires first, so the mention fails outright
        # instead of taking the fallback this classifier is built around.
        fake_client = self._fake_client('{"model": null, "reasoning_effort": null}')
        with patch(
            "posthog.temporal.ai.slack_app.activities.classifiers.get_llm_client",
            return_value=fake_client,
        ):
            classify_slack_app_model_override("use fable for this", CHOICES)

        assert fake_client.with_options.called, "the classifier must bound the gateway client"
        options = fake_client.with_options.call_args.kwargs
        assert options["timeout"] < POSTHOG_CODE_SLACK_MENTION_TIMEOUT_SECONDS
        assert options["max_retries"] * options["timeout"] < POSTHOG_CODE_SLACK_MENTION_TIMEOUT_SECONDS

    def test_prompt_snapshot_matches(self, snapshot):
        """The prompt is the whole classifier — the catalogue it offers, the
        instruction-vs-subject-matter examples, and the reply contract. Pinning it means
        a reworded rule shows up as a reviewable diff in the ``.ambr`` snapshot rather
        than as a silent behaviour change. Update intentionally by re-running with
        ``--snapshot-update`` after auditing the diff.
        """
        assert self._render_prompt("use fable for this one and fix the checkout test") == snapshot

    def _render_prompt(self, text: str) -> str:
        fake_client = self._fake_client('{"model": null, "reasoning_effort": null}')
        with patch(
            "posthog.temporal.ai.slack_app.activities.classifiers.get_llm_client",
            return_value=fake_client,
        ):
            classify_slack_app_model_override(text, CHOICES)
        return fake_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]

    def _fake_client(self, content: str) -> MagicMock:
        response = MagicMock()
        response.choices = [MagicMock(message=MagicMock(content=content))]
        client = MagicMock()
        # `with_options` returns a configured copy, so the fake hands back itself to keep
        # one set of call records no matter how the call site bounds the client.
        client.with_options.return_value = client
        client.chat.completions.create.return_value = response
        return client

    def _classify(self, text: str, content: str):
        with patch(
            "posthog.temporal.ai.slack_app.activities.classifiers.get_llm_client",
            return_value=self._fake_client(content),
        ):
            return classify_slack_app_model_override(text, CHOICES)
