from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.temporal.ai.slack_app.activities.classifiers import classify_message_is_agent_directed
from posthog.temporal.ai.slack_app.posthog_code_slack_mention import POSTHOG_CODE_SLACK_MENTION_TIMEOUT_SECONDS

TASK_TITLE = "Fix the checkout button not firing autocapture events"
THREAD = [
    {"user": "alice", "text": "@PostHog autocapture isn't picking up clicks on our checkout button", "ts": "1.0"},
    {"user": "posthog", "text": "Looking into it — checking how the button is rendered.", "ts": "2.0"},
]


class TestClassifyMessageIsAgentDirected:
    def test_emoji_only_is_dropped_without_paying_for_the_model(self):
        with patch("posthog.temporal.ai.slack_app.activities.classifiers.get_llm_client") as get_client:
            assert classify_message_is_agent_directed(":thumbsup: :tada:", TASK_TITLE, THREAD) is False
        get_client.assert_not_called()

    @parameterized.expand(
        [
            ("instruction", '{"agent_directed": true}', True),
            ("chatter", '{"agent_directed": false}', False),
            # Replies are not reliably unfenced through the gateway.
            ("fenced_json", '```json\n{"agent_directed": true}\n```', True),
            # Anything but the schema's boolean drops: a truthy string would invert the bias.
            ("stringified_bool", '{"agent_directed": "true"}', False),
            ("prose_instead_of_json", "The message looks like an instruction to me.", False),
            ("empty_reply", "", False),
        ]
    )
    def test_parses_the_reply(self, _name, content, expected):
        assert self._classify("also check the mobile breakpoint", content) is expected

    def test_llm_failure_drops_the_message(self):
        client = self._fake_client("")
        client.chat.completions.create.side_effect = RuntimeError("boom")
        with patch(
            "posthog.temporal.ai.slack_app.activities.classifiers.get_llm_client",
            return_value=client,
        ):
            assert classify_message_is_agent_directed("also check the breakpoint", TASK_TITLE, THREAD) is False

    def test_call_is_bounded_so_a_slow_gateway_falls_back(self):
        # Unbounded, the activity's deadline expires before the client's own 600s read, so
        # the reply is lost outright instead of taking the drop this is built around.
        client = self._fake_client('{"agent_directed": false}')
        with patch(
            "posthog.temporal.ai.slack_app.activities.classifiers.get_llm_client",
            return_value=client,
        ):
            classify_message_is_agent_directed("lunch in 5?", TASK_TITLE, THREAD)

        assert client.with_options.called, "the classifier must bound the gateway client"
        options = client.with_options.call_args.kwargs
        assert options["timeout"] < POSTHOG_CODE_SLACK_MENTION_TIMEOUT_SECONDS
        assert options["max_retries"] * options["timeout"] < POSTHOG_CODE_SLACK_MENTION_TIMEOUT_SECONDS

    def test_reply_is_pinned_to_a_single_boolean(self):
        # The schema, not the prompt, is what stops a reasoning model answering with its
        # reasoning — prose parses to nothing, which reads as a refused call.
        client = self._fake_client('{"agent_directed": false}')
        with patch(
            "posthog.temporal.ai.slack_app.activities.classifiers.get_llm_client",
            return_value=client,
        ):
            classify_message_is_agent_directed("lunch in 5?", TASK_TITLE, THREAD)

        schema = client.chat.completions.create.call_args.kwargs["response_format"]["json_schema"]
        assert schema["strict"] is True
        assert schema["schema"]["properties"]["agent_directed"]["type"] == "boolean"
        assert schema["schema"]["additionalProperties"] is False

    def test_prompt_snapshot_matches(self, snapshot):
        """The prompt is the whole classifier — where it draws the line between talking to
        the agent and talking about it. Pinning it means a reworded rule shows up as a
        reviewable diff rather than a silent behaviour change. Update with
        ``--snapshot-update`` after auditing the diff, then re-run
        ``hogli evals eval_followup_classifier`` before trusting it.
        """
        assert self._render_prompt("this whole thing would benefit from a Settings section") == snapshot

    def test_prompt_carries_the_thread_and_the_task(self):
        # Several eval cases are decidable only from what came before them, so a prompt
        # that rendered the reply alone would grade a different classifier.
        prompt = self._render_prompt("it only happens for logged-out users")
        assert TASK_TITLE in prompt
        assert THREAD[0]["text"] in prompt
        assert "it only happens for logged-out users" in prompt

    def _render_prompt(self, text: str) -> str:
        client = self._fake_client('{"agent_directed": false}')
        with patch(
            "posthog.temporal.ai.slack_app.activities.classifiers.get_llm_client",
            return_value=client,
        ):
            classify_message_is_agent_directed(text, TASK_TITLE, THREAD)
        return client.chat.completions.create.call_args.kwargs["messages"][0]["content"]

    def _classify(self, text: str, content: str) -> bool:
        with patch(
            "posthog.temporal.ai.slack_app.activities.classifiers.get_llm_client",
            return_value=self._fake_client(content),
        ):
            return classify_message_is_agent_directed(text, TASK_TITLE, THREAD)

    def _fake_client(self, content: str) -> MagicMock:
        response = MagicMock()
        response.choices = [MagicMock(message=MagicMock(content=content))]
        client = MagicMock()
        # `with_options` returns a configured copy, so the fake hands back itself to keep
        # one set of call records no matter how the call site bounds the client.
        client.with_options.return_value = client
        client.chat.completions.create.return_value = response
        return client
