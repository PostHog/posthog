import json

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from posthog.llm.gateway_client import team_distinct_id, team_trace_id
from posthog.llm.semantic_enrichment import (
    MAX_COLUMNS_PER_TABLE,
    MAX_ENRICHMENT_BATCHES,
    MAX_OUTPUT_TOKENS,
    MIN_OUTPUT_TOKENS,
    TruncatedCompletionError,
    _ChatClient,
    _Completion,
    _MessagesClient,
    bound_prompt_over_columns,
    build_enrichment_client,
    generate_json_completion,
    projected_output_tokens,
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
        # aig reads the capture identity from this header; the Messages `metadata.user_id` goes
        # upstream to the provider instead, so without it the spend lands on the shared credential.
        assert headers["X-PostHog-Distinct-Id"] == team_distinct_id(7)

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


def _chat_response(text: str | None, *, finish_reason: str = "stop") -> MagicMock:
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
        client.complete.assert_called_once_with(
            model="claude-haiku-4-5", prompt="p", temperature=0.2, team_id=7, max_output_tokens=MAX_OUTPUT_TOKENS
        )
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


def test_the_cap_is_reachable_above_the_floor():
    """The ceiling is sized per table now, so the old assertion that the cap covers the widest table
    at a flat per-column rate no longer describes anything. What still has to hold is that the clamp
    cannot invert: a floor above the cap would make `min(needed, cap)` return less than the floor the
    estimator promises."""
    assert MIN_OUTPUT_TOKENS < MAX_OUTPUT_TOKENS


def test_the_output_ceiling_stays_under_the_sdk_non_streaming_limit():
    """The other direction is the worse failure. The Anthropic SDK refuses a non-streaming call
    whose `max_tokens` implies a timeout past its ceiling, and raises before any request goes out,
    so overshooting takes the whole leg down rather than degrading to truncation. Raising
    `MAX_COLUMNS_PER_TABLE` far enough would walk the floor above this bound, so pin both ends."""
    assert MAX_OUTPUT_TOKENS <= 128_000 * 600 // 3600


class TestMessagesTextGuards:
    """The Messages leg is the one the cutover switches traffic onto, so its null defaults need the
    same pinning the chat leg's `content or ""` got."""

    def _completion(self, blocks: list[MagicMock]) -> _Completion:
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


def _wide_names(count: int) -> list[str]:
    """Distinct names at the 400-char annotation key limit, the width that outruns a flat ceiling."""
    return [f"{i:04d}" + "c" * 396 for i in range(count)]


class TestOutputCeilingSizing:
    """The reply echoes every column name as a JSON key, so the ceiling has to follow the names."""

    def _columns(self, names: list[str]) -> list[dict[str, str]]:
        return [{"name": name} for name in names]

    def test_long_names_need_more_than_short_ones_at_the_same_count(self):
        short = projected_output_tokens(["a"] * 50)
        long = projected_output_tokens(_wide_names(50))

        assert long > short, "a ceiling that ignores name length truncates wide-named tables"

    def test_a_full_width_table_of_long_names_outruns_the_cap(self):
        """The case a flat ceiling gets wrong: the ask alone cannot fit, so every attempt truncates."""
        assert projected_output_tokens(_wide_names(MAX_COLUMNS_PER_TABLE)) > MAX_OUTPUT_TOKENS

    def test_bounding_drops_columns_until_the_reply_can_fit(self):
        names = _wide_names(MAX_COLUMNS_PER_TABLE)
        columns = self._columns(names)
        asked: list[list[str]] = []

        def builder(shown_columns, needing):
            asked.append(needing)
            return "prompt"

        bounded = bound_prompt_over_columns(builder, columns, names)
        prompt, ceiling = bounded.prompt, bounded.max_output_tokens

        assert prompt == "prompt"
        assert ceiling <= MAX_OUTPUT_TOKENS
        assert len(asked[-1]) < MAX_COLUMNS_PER_TABLE, "the ask list has to shrink or the reply is cut off"
        assert projected_output_tokens(asked[-1]) <= MAX_OUTPUT_TOKENS

    def test_a_narrow_table_keeps_every_column_and_a_small_ceiling(self):
        names = ["id", "email", "created_at"]
        columns = self._columns(names)

        bounded = bound_prompt_over_columns(lambda shown, needing: "prompt", columns, names)
        prompt, ceiling = bounded.prompt, bounded.max_output_tokens

        assert prompt == "prompt"
        assert ceiling < MAX_OUTPUT_TOKENS, "a three-column table should not reserve the whole cap"

    def test_the_sized_ceiling_reaches_the_request(self):
        client = MagicMock()
        client.messages.create.return_value = _messages_response('{"columns": {}}')

        generate_json_completion(
            product="warehouse_semantic_enrichment",
            team_id=7,
            prompt="p",
            client=_MessagesClient(client),
            max_output_tokens=2048,
        )

        assert client.messages.create.call_args.kwargs["max_tokens"] == 2048


class TestDeferralContract:
    """`deferred` is what makes the drop safe: a caller whose idempotency covers the whole object
    reads it to decide whether it may record completion."""

    def test_nothing_deferred_when_everything_fits(self):
        names = ["id", "email", "created_at"]
        bounded = bound_prompt_over_columns(lambda shown, needing: "prompt", [{"name": n} for n in names], names)

        assert bounded.deferred == []
        assert bounded.requested == names

    def test_dropped_columns_are_reported_as_deferred(self):
        names = _wide_names(MAX_COLUMNS_PER_TABLE)
        bounded = bound_prompt_over_columns(lambda shown, needing: "prompt", [{"name": n} for n in names], names)

        assert bounded.deferred, "a full-width table of 400-char names cannot fit one reply"
        assert set(bounded.requested) | set(bounded.deferred) == set(names)
        assert set(bounded.requested).isdisjoint(bounded.deferred)
        # The ask list is what the ceiling was sized for, so the two must agree.
        assert bounded.max_output_tokens == min(projected_output_tokens(bounded.requested), MAX_OUTPUT_TOKENS)

    def test_deferred_preserves_the_callers_order(self):
        """Callers persist or re-ask these names, so a reordering would make the retry ask for a
        different set than the one that was dropped."""
        names = _wide_names(MAX_COLUMNS_PER_TABLE)
        bounded = bound_prompt_over_columns(lambda shown, needing: "prompt", [{"name": n} for n in names], names)

        assert bounded.deferred == [name for name in names if name in set(bounded.deferred)]

    def test_the_prompt_char_bound_also_reports_deferral(self):
        """Both bounds drop columns, so both owe the caller the same signal."""
        names = [f"col_{i}" for i in range(100)]
        bounded = bound_prompt_over_columns(
            lambda shown, needing: "x" * (len(shown) * 100),
            [{"name": n} for n in names],
            names,
            max_prompt_chars=1000,
        )

        assert bounded.deferred
        assert len(bounded.prompt) <= 1000


class TestBatchingConverges:
    """Batching only helps if each pass asks for something the last one could not fit. The ask list is
    the only input that changes between batches, so the bounding has to protect it from the drop."""

    def _columns(self, count: int) -> list[dict[str, str]]:
        return [{"name": f"col_{i:03d}"} for i in range(count)]

    def test_context_columns_are_dropped_before_asked_ones(self):
        columns = self._columns(100)
        names = [str(column["name"]) for column in columns]
        # Ask about the tail only, so a blind tail-drop would shed exactly the asked columns.
        asked = names[-10:]

        bounded = bound_prompt_over_columns(lambda shown, needing: "x" * (len(shown) * 3000), columns, asked)

        assert bounded.requested == asked, "the ask list must survive while context remains to drop"
        assert bounded.deferred == []

    def test_a_second_batch_asks_for_what_the_first_deferred(self):
        """The regression. Dropping the tail blind made every later batch rebuild the same prompt,
        shed the same names, and ask for nothing, so the deferred columns were never described."""
        columns = self._columns(200)
        names = [str(column["name"]) for column in columns]

        def builder(shown, needing):
            return "x" * (len(shown) * 3000)

        first = bound_prompt_over_columns(builder, columns, names)
        assert first.deferred, "this fixture must defer, or it is not testing batching"

        second = bound_prompt_over_columns(builder, columns, first.deferred)

        assert second.requested, "a batch that asks for nothing is a wasted call"
        assert set(second.requested) <= set(first.deferred)
        assert len(second.deferred) < len(first.deferred), "each batch must make progress"


class TestBatchBudgetCoversTheCaps:
    """The relationship that actually governs correctness after the ceiling became per-table: the
    batch budget has to finish the widest table the column cap allows at the longest name the
    annotation key permits. Nothing else pins the three constants against each other."""

    def test_the_budget_finishes_the_widest_table_the_caps_allow(self):
        names = _wide_names(MAX_COLUMNS_PER_TABLE)
        columns = [{"name": name} for name in names]

        remaining = names
        batches = 0
        while remaining and batches < MAX_ENRICHMENT_BATCHES:
            bounded = bound_prompt_over_columns(lambda shown, needing: "prompt", columns, remaining)
            assert bounded.requested, "a batch that asks for nothing spends a call for no answer"
            remaining = bounded.deferred
            batches += 1

        assert not remaining, (
            f"{len(remaining)} columns left after {MAX_ENRICHMENT_BATCHES} batches. "
            f"MAX_ENRICHMENT_BATCHES={MAX_ENRICHMENT_BATCHES} no longer covers "
            f"MAX_COLUMNS_PER_TABLE={MAX_COLUMNS_PER_TABLE} at the 400-char annotation key limit; "
            "raise the budget or lower the column cap."
        )

    def test_the_cap_bounds_the_ceiling_even_on_the_single_column_escape(self):
        """The loop gives up at one column. A name whose own reply cannot fit still has to declare a
        ceiling the provider will accept, so the cap has to survive that exit."""
        huge = "c" * 400_000
        bounded = bound_prompt_over_columns(lambda shown, needing: "prompt", [{"name": huge}], [huge])

        assert bounded.max_output_tokens == MAX_OUTPUT_TOKENS
        assert projected_output_tokens([huge]) > MAX_OUTPUT_TOKENS, "fixture must exceed the cap"
