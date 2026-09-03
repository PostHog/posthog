import json

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from posthog.llm.gateway_client import team_trace_id
from posthog.llm.semantic_enrichment import (
    MAX_COLUMNS_PER_TABLE,
    MAX_OUTPUT_TOKENS,
    TruncatedCompletionError,
    _ChatClient,
    _MessagesClient,
    build_enrichment_client,
    generate_json_completion,
)

AI_GATEWAY_URL = "https://ai-gateway.example/v1"
AI_GATEWAY_KEY = "phs_project_secret"


class TestBuildEnrichmentClient:
    @override_settings(AI_GATEWAY_URL=AI_GATEWAY_URL, AI_GATEWAY_API_KEY=AI_GATEWAY_KEY)
    @patch("posthog.llm.gateway_client.httpx.Client")
    @patch("posthog.llm.gateway_client.Anthropic")
    def test_gateway_mode_uses_native_messages_with_product_and_team(self, mock_anthropic, mock_httpx):
        result = build_enrichment_client("warehouse_semantic_enrichment", 7)

        assert isinstance(result, _MessagesClient)
        mock_httpx.assert_called_once_with(trust_env=False)
        kwargs = mock_anthropic.call_args.kwargs
        assert kwargs["api_key"] == AI_GATEWAY_KEY
        assert kwargs["base_url"] == "https://ai-gateway.example"
        headers = kwargs["default_headers"]
        assert json.loads(headers["X-PostHog-Properties"]) == {
            "ai_product": "warehouse_semantic_enrichment",
            "team_id": "7",
        }
        assert headers["X-PostHog-Product"] == "warehouse_semantic_enrichment"
        assert headers["X-PostHog-Trace-Id"] == team_trace_id(7)

    @override_settings(AI_GATEWAY_URL="", AI_GATEWAY_API_KEY="")
    @patch("posthog.llm.semantic_enrichment.get_llm_client")
    def test_fallback_keeps_the_chat_completions_shape(self, mock_get_llm_client):
        """Clearing the env must restore the pre-cutover wire behaviour, not a new route."""
        result = build_enrichment_client("warehouse_semantic_enrichment", 7)

        assert isinstance(result, _ChatClient)
        mock_get_llm_client.assert_called_once_with(product="warehouse_semantic_enrichment", team_id=7)

    @override_settings(AI_GATEWAY_URL=AI_GATEWAY_URL, AI_GATEWAY_API_KEY="")
    @patch("posthog.llm.semantic_enrichment.get_llm_client")
    def test_half_applied_env_falls_back_to_chat(self, mock_get_llm_client):
        assert isinstance(build_enrichment_client("warehouse_semantic_enrichment", 7), _ChatClient)
        mock_get_llm_client.assert_called_once()


def _messages_response(text: str, *, stop_reason: str = "end_turn", usage: MagicMock | None = None) -> MagicMock:
    response = MagicMock()
    response.content = [MagicMock(type="text", text=text)]
    response.usage = MagicMock(input_tokens=10, output_tokens=2) if usage is None else usage
    response.stop_reason = stop_reason
    return response


def _chat_response(text: str, *, finish_reason: str = "stop") -> MagicMock:
    response = MagicMock()
    choice = MagicMock(finish_reason=finish_reason)
    choice.message.content = text
    response.choices = [choice]
    response.usage = MagicMock(prompt_tokens=10, completion_tokens=2)
    return response


class TestMessagesClient:
    def _sdk(self, response: MagicMock) -> MagicMock:
        sdk = MagicMock()
        sdk.messages.create.return_value = response
        return sdk

    def test_sends_a_bounded_request_and_normalises_usage(self):
        sdk = self._sdk(_messages_response('{"columns": {"a": "desc"}}'))

        completion = _MessagesClient(sdk).complete(model="m", prompt="p", temperature=0.2, team_id=7)

        kwargs = sdk.messages.create.call_args.kwargs
        assert kwargs["model"] == "m"
        # Against the literal, not the constant, so lowering the ceiling goes red.
        assert kwargs["max_tokens"] == 16384
        assert MAX_OUTPUT_TOKENS == 16384
        assert kwargs["messages"] == [{"role": "user", "content": "p"}]
        assert kwargs["temperature"] == 0.2
        assert kwargs["metadata"] == {"user_id": "team-7"}
        assert completion.truncated is False
        assert completion.max_output_tokens == 16384
        assert completion.usage == {"model": "m", "prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}

    def test_reports_a_max_tokens_stop_as_truncated(self):
        sdk = self._sdk(_messages_response('{"columns": ', stop_reason="max_tokens"))

        assert _MessagesClient(sdk).complete(model="m", prompt="p", temperature=0.2, team_id=7).truncated is True

    def test_joins_text_blocks_and_skips_other_block_types(self):
        response = _messages_response("")
        response.content = [
            MagicMock(type="thinking"),
            MagicMock(type="text", text='{"columns": '),
            MagicMock(type="text", text='{"a": "desc"}}'),
        ]

        completion = _MessagesClient(self._sdk(response)).complete(model="m", prompt="p", temperature=0.2, team_id=7)

        assert completion.text == '{"columns": {"a": "desc"}}'

    def test_absent_token_counts_leave_the_total_unset(self):
        response = _messages_response("{}", usage=MagicMock(input_tokens=None, output_tokens=None))

        completion = _MessagesClient(self._sdk(response)).complete(model="m", prompt="p", temperature=0.2, team_id=7)

        assert completion.usage["total_tokens"] is None


class TestChatClient:
    def _sdk(self, response: MagicMock) -> MagicMock:
        sdk = MagicMock()
        sdk.chat.completions.create.return_value = response
        return sdk

    def test_sends_the_pre_cutover_request_shape(self):
        sdk = self._sdk(_chat_response('{"columns": {"a": "desc"}}'))

        completion = _ChatClient(sdk).complete(model="m", prompt="p", temperature=0.2, team_id=7)

        kwargs = sdk.chat.completions.create.call_args.kwargs
        assert kwargs["model"] == "m"
        assert kwargs["messages"] == [{"role": "user", "content": "p"}]
        assert kwargs["temperature"] == 0.2
        assert kwargs["response_format"] == {"type": "json_object"}
        assert kwargs["user"] == "team-7"
        assert "max_tokens" not in kwargs
        # This leg sends no ceiling of ours, so the truncation message must not claim one.
        assert completion.max_output_tokens is None
        assert completion.truncated is False
        assert completion.usage == {"model": "m", "prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}

    def test_reports_a_length_finish_as_truncated(self):
        sdk = self._sdk(_chat_response('{"columns": ', finish_reason="length"))

        assert _ChatClient(sdk).complete(model="m", prompt="p", temperature=0.2, team_id=7).truncated is True


class TestGenerateJsonCompletion:
    def _client(self, text: str, *, truncated: bool = False) -> MagicMock:
        client = MagicMock()
        client.complete.return_value = MagicMock(
            text=text,
            usage={"model": "claude-haiku-4-5", "prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            truncated=truncated,
        )
        return client

    def test_resolves_a_client_and_passes_the_call_through(self):
        client = self._client('{"columns": {"a": "desc"}}')
        with patch("posthog.llm.semantic_enrichment.build_enrichment_client", return_value=client) as mock_build:
            parsed, usage = generate_json_completion(product="warehouse_semantic_enrichment", team_id=7, prompt="p")

        mock_build.assert_called_once_with("warehouse_semantic_enrichment", 7)
        client.complete.assert_called_once_with(model="claude-haiku-4-5", prompt="p", temperature=0.2, team_id=7)
        assert parsed == {"columns": {"a": "desc"}}
        assert usage["total_tokens"] == 12

    def test_truncated_reply_raises_its_own_error(self):
        """A too-small ceiling must not read as a model that cannot format JSON."""
        client = self._client('{"columns": ', truncated=True)

        with pytest.raises(TruncatedCompletionError):
            generate_json_completion(product="warehouse_semantic_enrichment", team_id=7, prompt="p", client=client)

    def test_unparseable_reply_that_was_not_truncated_raises_plain_value_error(self):
        client = self._client("sorry, no")

        with pytest.raises(ValueError) as excinfo:
            generate_json_completion(product="warehouse_semantic_enrichment", team_id=7, prompt="p", client=client)

        assert not isinstance(excinfo.value, TruncatedCompletionError)

    def test_injected_client_is_used_as_is(self):
        client = self._client("{}")
        with patch("posthog.llm.semantic_enrichment.build_enrichment_client") as mock_build:
            generate_json_completion(product="warehouse_semantic_enrichment", team_id=7, prompt="p", client=client)

        mock_build.assert_not_called()


class TestRoundTripThroughGenerateJsonCompletion:
    """Drives the real client classes through the real consumer.

    The class-level tests build a `_Completion` by hand, so they cannot see how the two halves fit
    together: whether the truncation guard runs before the parse, or what the chat leg does with a
    null content field.
    """

    def _messages_client(self, text: str, *, stop_reason: str) -> _MessagesClient:
        sdk = MagicMock()
        sdk.messages.create.return_value = _messages_response(text, stop_reason=stop_reason)
        return _MessagesClient(sdk)

    def _chat_client(self, content: str | None, *, finish_reason: str = "stop") -> _ChatClient:
        sdk = MagicMock()
        sdk.chat.completions.create.return_value = _chat_response(content, finish_reason=finish_reason)
        return _ChatClient(sdk)

    def test_truncated_reply_that_still_parses_is_rejected(self):
        """The guard has to run before the parse: a cut-off reply whose fragment happens to close is
        a subset of the columns asked for, and the view consumer latches its hash on any success."""
        client = self._messages_client('{"columns": {"a": "desc"}}', stop_reason="max_tokens")

        with pytest.raises(TruncatedCompletionError) as excinfo:
            generate_json_completion(product="warehouse_semantic_enrichment", team_id=7, prompt="p", client=client)

        # The message names the ceiling this leg actually sent, not a constant the other leg uses.
        assert "16384" in str(excinfo.value)

    def test_untruncated_reply_parses_normally(self):
        client = self._messages_client('{"columns": {"a": "desc"}}', stop_reason="end_turn")

        parsed, usage = generate_json_completion(
            product="warehouse_semantic_enrichment", team_id=7, prompt="p", client=client
        )

        assert parsed == {"columns": {"a": "desc"}}
        assert usage["total_tokens"] == 12

    def test_chat_leg_null_content_raises_value_error_not_attribute_error(self):
        """OpenAI sends content: null on a refusal or a tool call, and this leg carries all the
        traffic until the worker env lands."""
        client = self._chat_client(None)

        # An AttributeError would propagate out of pytest.raises(ValueError) as a test error, so
        # the raises() is what pins this; dropping `or ""` fails here with exactly that.
        with pytest.raises(ValueError):
            generate_json_completion(product="warehouse_semantic_enrichment", team_id=7, prompt="p", client=client)

    def test_chat_leg_truncation_names_the_provider_default(self):
        """This leg sends no ceiling of ours, so the message must not name one."""
        client = self._chat_client('{"columns": ', finish_reason="length")

        with pytest.raises(TruncatedCompletionError) as excinfo:
            generate_json_completion(product="warehouse_semantic_enrichment", team_id=7, prompt="p", client=client)

        assert "provider-default" in str(excinfo.value)
        assert "16384" not in str(excinfo.value)


class TestUsageNormalisation:
    def test_one_absent_token_count_is_enough_to_leave_the_total_unset(self):
        """Each conjunct has to be the sole reason for the outcome, or `or` weakens to `and`."""
        sdk = MagicMock()
        sdk.chat.completions.create.return_value = _chat_response("{}")
        sdk.chat.completions.create.return_value.usage = MagicMock(prompt_tokens=10, completion_tokens=None)

        completion = _ChatClient(sdk).complete(model="m", prompt="p", temperature=0.2, team_id=7)

        assert completion.usage["total_tokens"] is None

    def test_the_other_absent_count_also_leaves_it_unset(self):
        sdk = MagicMock()
        sdk.chat.completions.create.return_value = _chat_response("{}")
        sdk.chat.completions.create.return_value.usage = MagicMock(prompt_tokens=None, completion_tokens=2)

        completion = _ChatClient(sdk).complete(model="m", prompt="p", temperature=0.2, team_id=7)

        assert completion.usage["total_tokens"] is None


def test_the_output_ceiling_covers_the_widest_table_the_prompt_allows():
    """Binds the ceiling to the column cap it was derived from, so raising one without the other
    goes red here rather than as truncation errors in production."""
    assert MAX_OUTPUT_TOKENS >= MAX_COLUMNS_PER_TABLE * 30 * 2


def test_the_output_ceiling_stays_under_the_sdk_non_streaming_limit():
    """The other direction is the worse failure. The Anthropic SDK refuses a non-streaming call
    whose `max_tokens` implies a timeout past its ceiling, and raises before any request goes out,
    so overshooting takes the whole leg down rather than degrading to truncation. Raising
    `MAX_COLUMNS_PER_TABLE` far enough would walk the floor above this bound, so pin both ends."""
    assert MAX_OUTPUT_TOKENS <= 128_000 * 600 // 3600


class TestMessagesTextGuards:
    """The Messages leg is the one the cutover switches traffic onto, so its null defaults need the
    same pinning the chat leg's `content or ""` got."""

    def _completion(self, blocks) -> object:
        sdk = MagicMock()
        response = _messages_response("")
        response.content = blocks
        sdk.messages.create.return_value = response
        return _MessagesClient(sdk).complete(model="m", prompt="p", temperature=0.2, team_id=7)

    def test_a_text_block_with_no_text_contributes_nothing(self):
        completion = self._completion([MagicMock(type="text", text=None), MagicMock(type="text", text="{}")])

        assert completion.text == "{}"

    def test_an_absent_content_array_yields_empty_text(self):
        sdk = MagicMock()
        response = _messages_response("")
        response.content = None
        sdk.messages.create.return_value = response

        completion = _MessagesClient(sdk).complete(model="m", prompt="p", temperature=0.2, team_id=7)

        assert completion.text == ""

    def test_an_empty_content_array_surfaces_as_a_parse_failure(self):
        sdk = MagicMock()
        response = _messages_response("")
        response.content = []
        sdk.messages.create.return_value = response

        with pytest.raises(ValueError):
            generate_json_completion(
                product="warehouse_semantic_enrichment", team_id=7, prompt="p", client=_MessagesClient(sdk)
            )
