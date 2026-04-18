from unittest.mock import patch

from posthog.temporal.subscriptions.llm_change_summary import (
    build_initial_prompt_messages,
    build_prompt_messages,
    generate_change_summary,
)


def _make_state(
    insight_id: int,
    name: str,
    summary: str,
    query_kind: str = "TrendsQuery",
    timestamp: str = "2025-04-14T10:00:00Z",
    description: str = "",
) -> dict:
    return {
        "insight_id": insight_id,
        "insight_name": name,
        "insight_description": description,
        "query_kind": query_kind,
        "results_summary": summary,
        "timestamp": timestamp,
    }


class TestBuildPromptMessages:
    def test_single_insight(self):
        previous = [_make_state(1, "Pageviews", "avg 100/day", timestamp="2025-04-14T10:00:00Z")]
        current = [_make_state(1, "Pageviews", "avg 150/day", timestamp="2025-04-15T10:00:00Z")]

        messages = build_prompt_messages(previous, current)

        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert "Pageviews" in messages[1]["content"]
        assert "avg 100/day" in messages[1]["content"]
        assert "avg 150/day" in messages[1]["content"]
        assert "2025-04-14" in messages[1]["content"]
        assert "2025-04-15" in messages[1]["content"]

    def test_multiple_insights(self):
        previous = [
            _make_state(1, "Pageviews", "avg 100/day"),
            _make_state(2, "Signups", "avg 10/day"),
        ]
        current = [
            _make_state(1, "Pageviews", "avg 150/day", timestamp="2025-04-15T10:00:00Z"),
            _make_state(2, "Signups", "avg 15/day", timestamp="2025-04-15T10:00:00Z"),
        ]

        messages = build_prompt_messages(previous, current)

        user_content = messages[1]["content"]
        assert "Pageviews" in user_content
        assert "Signups" in user_content

    def test_includes_query_specific_instructions(self):
        previous = [_make_state(1, "Retention", "week 0: 100%", query_kind="RetentionQuery")]
        current = [
            _make_state(1, "Retention", "week 0: 95%", query_kind="RetentionQuery", timestamp="2025-04-15T10:00:00Z")
        ]

        messages = build_prompt_messages(previous, current)

        user_content = messages[1]["content"]
        assert "retention curve" in user_content.lower()

    def test_includes_subscription_title(self):
        previous = [_make_state(1, "Pageviews", "avg 100/day")]
        current = [_make_state(1, "Pageviews", "avg 150/day", timestamp="2025-04-15T10:00:00Z")]

        messages = build_prompt_messages(previous, current, subscription_title="Weekly team report")

        assert len(messages) == 2
        assert "Weekly team report" in messages[1]["content"]

    def test_includes_prompt_guide(self):
        previous = [_make_state(1, "Revenue", "total $10k")]
        current = [_make_state(1, "Revenue", "total $8k", timestamp="2025-04-15T10:00:00Z")]

        messages = build_prompt_messages(previous, current, prompt_guide="Focus on revenue drop-off")

        user_content = messages[-1]["content"]
        assert "Focus on revenue drop-off" in user_content
        assert "<user_context>" in user_content

    def test_omits_guide_section_when_empty(self):
        previous = [_make_state(1, "Revenue", "total $10k")]
        current = [_make_state(1, "Revenue", "total $8k", timestamp="2025-04-15T10:00:00Z")]

        messages = build_prompt_messages(previous, current, prompt_guide="")

        user_content = messages[-1]["content"]
        assert "<user_context>" not in user_content

    def test_includes_insight_description_in_section(self):
        previous = [_make_state(1, "p95", "- p95: latest=2.0", description="Daily p95 response time in seconds")]
        current = [
            _make_state(
                1,
                "p95",
                "- p95: latest=3.5",
                timestamp="2025-04-15T10:00:00Z",
                description="Daily p95 response time in seconds",
            )
        ]

        messages = build_prompt_messages(previous, current)

        user_content = messages[-1]["content"]
        assert "Description: Daily p95 response time in seconds" in user_content

    def test_omits_description_line_when_empty(self):
        previous = [_make_state(1, "p95", "- p95: latest=2.0")]
        current = [_make_state(1, "p95", "- p95: latest=3.5", timestamp="2025-04-15T10:00:00Z")]

        messages = build_prompt_messages(previous, current)

        user_content = messages[-1]["content"]
        assert "Description:" not in user_content


class TestBuildInitialPromptMessages:
    def test_single_insight(self):
        current = [_make_state(1, "Pageviews", "avg 150/day", timestamp="2025-04-15T10:00:00Z")]

        messages = build_initial_prompt_messages(current)

        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert "Pageviews" in messages[1]["content"]
        assert "avg 150/day" in messages[1]["content"]
        assert "2025-04-15" in messages[1]["content"]
        assert "Previous" not in messages[1]["content"]

    def test_multiple_insights(self):
        current = [
            _make_state(1, "Pageviews", "avg 150/day", timestamp="2025-04-15T10:00:00Z"),
            _make_state(2, "Signups", "avg 15/day", timestamp="2025-04-15T10:00:00Z"),
        ]

        messages = build_initial_prompt_messages(current)

        user_content = messages[1]["content"]
        assert "Pageviews" in user_content
        assert "Signups" in user_content

    def test_includes_query_specific_instructions(self):
        current = [
            _make_state(
                1, "Funnel", "step 1: 100, step 2: 50", query_kind="FunnelsQuery", timestamp="2025-04-15T10:00:00Z"
            )
        ]

        messages = build_initial_prompt_messages(current)

        user_content = messages[1]["content"]
        assert "conversion" in user_content.lower()

    def test_includes_subscription_title(self):
        current = [_make_state(1, "Pageviews", "avg 150/day", timestamp="2025-04-15T10:00:00Z")]

        messages = build_initial_prompt_messages(current, subscription_title="Weekly team report")

        assert len(messages) == 2
        assert "Weekly team report" in messages[1]["content"]

    def test_includes_prompt_guide(self):
        current = [_make_state(1, "Revenue", "total $10k", timestamp="2025-04-15T10:00:00Z")]

        messages = build_initial_prompt_messages(current, prompt_guide="Focus on revenue")

        user_content = messages[-1]["content"]
        assert "Focus on revenue" in user_content
        assert "<user_context>" in user_content

    def test_omits_guide_section_when_empty(self):
        current = [_make_state(1, "Revenue", "total $10k", timestamp="2025-04-15T10:00:00Z")]

        messages = build_initial_prompt_messages(current, prompt_guide="")

        user_content = messages[-1]["content"]
        assert "<user_context>" not in user_content


def _mock_openai_response(content: str = "", prompt_tokens: int = 0, completion_tokens: int = 0):
    from unittest.mock import MagicMock

    choice = MagicMock()
    choice.message.content = content

    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens

    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


class TestGenerateChangeSummary:
    @patch("posthog.temporal.subscriptions.llm_change_summary.get_llm_client")
    def test_returns_content_with_correct_params(self, mock_get_client):
        mock_client = mock_get_client.return_value
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            "- Pageviews increased by 50%\n- Signups stable", 100, 20
        )

        previous = [_make_state(1, "Pageviews", "avg 100/day")]
        current = [_make_state(1, "Pageviews", "avg 150/day", timestamp="2025-04-15T10:00:00Z")]

        result = generate_change_summary(previous, current, team=None)

        assert "Pageviews increased" in result
        mock_client.chat.completions.create.assert_called_once()
        call_kwargs = mock_client.chat.completions.create.call_args
        assert call_kwargs.kwargs["temperature"] == 0.3
        assert call_kwargs.kwargs["max_tokens"] == 500

    @patch("posthog.temporal.subscriptions.llm_change_summary.get_llm_client")
    def test_uses_initial_prompt_when_no_previous_states(self, mock_get_client):
        mock_client = mock_get_client.return_value
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            "- Pageviews averaging 150/day", 80, 15
        )

        current = [_make_state(1, "Pageviews", "avg 150/day", timestamp="2025-04-15T10:00:00Z")]

        result = generate_change_summary(None, current, team=None)

        assert "Pageviews" in result
        call_kwargs = mock_client.chat.completions.create.call_args
        messages = call_kwargs.kwargs["messages"]
        system_content = messages[0]["content"]
        assert "current state" in system_content

    @patch("posthog.temporal.subscriptions.llm_change_summary.get_llm_client")
    def test_handles_empty_content(self, mock_get_client):
        mock_client = mock_get_client.return_value
        mock_client.chat.completions.create.return_value = _mock_openai_response("", 0, 0)

        result = generate_change_summary(
            [_make_state(1, "X", "data")],
            [_make_state(1, "X", "data", timestamp="2025-04-15T10:00:00Z")],
        )

        assert result == ""

    @patch("posthog.temporal.subscriptions.llm_change_summary.get_llm_client")
    def test_attaches_insight_images_as_multimodal_parts(self, mock_get_client):
        mock_client = mock_get_client.return_value
        mock_client.chat.completions.create.return_value = _mock_openai_response("- Data shown")

        current = [
            _make_state(1, "Pageviews", "avg 100/day", timestamp="2025-04-15T10:00:00Z"),
            _make_state(2, "Signups", "avg 10/day", timestamp="2025-04-15T10:00:00Z"),
        ]
        images = {1: b"png-for-1", 2: b"png-for-2"}

        generate_change_summary(None, current, team=None, insight_images=images)

        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        user_content = messages[-1]["content"]
        assert isinstance(user_content, list)
        assert user_content[0]["type"] == "text"
        image_parts = [p for p in user_content if p.get("type") == "image_url"]
        assert len(image_parts) == 2
        assert image_parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
        assert image_parts[0]["image_url"]["detail"] == "auto"

    @patch("posthog.temporal.subscriptions.llm_change_summary.get_llm_client")
    def test_prepends_label_text_part_before_each_image(self, mock_get_client):
        mock_client = mock_get_client.return_value
        mock_client.chat.completions.create.return_value = _mock_openai_response("- ok")

        current = [
            _make_state(1, "Pageviews", "avg 100/day", timestamp="2025-04-15T10:00:00Z"),
            _make_state(2, "Signups", "avg 10/day", timestamp="2025-04-15T10:00:00Z"),
        ]
        images = {1: b"pv", 2: b"su"}

        generate_change_summary(None, current, team=None, insight_images=images)

        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        user_content = messages[-1]["content"]
        label_texts = [p["text"] for p in user_content if p.get("type") == "text"]
        assert "Chart for: Pageviews" in label_texts
        assert "Chart for: Signups" in label_texts

    @patch("posthog.temporal.subscriptions.llm_change_summary.get_llm_client")
    def test_preserves_state_order_when_attaching_images(self, mock_get_client):
        import base64

        mock_client = mock_get_client.return_value
        mock_client.chat.completions.create.return_value = _mock_openai_response("- ok")

        current = [
            _make_state(2, "Signups", "...", timestamp="2025-04-15T10:00:00Z"),
            _make_state(1, "Pageviews", "...", timestamp="2025-04-15T10:00:00Z"),
        ]
        images = {1: b"pv", 2: b"su"}

        generate_change_summary(None, current, team=None, insight_images=images)

        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        user_content = messages[-1]["content"]
        image_parts = [p for p in user_content if p.get("type") == "image_url"]
        assert len(image_parts) == 2
        expected_first = f"data:image/png;base64,{base64.b64encode(b'su').decode()}"
        assert image_parts[0]["image_url"]["url"] == expected_first

    @patch("posthog.temporal.subscriptions.llm_change_summary.get_llm_client")
    def test_leaves_user_message_as_string_when_no_images(self, mock_get_client):
        mock_client = mock_get_client.return_value
        mock_client.chat.completions.create.return_value = _mock_openai_response("- ok")

        current = [_make_state(1, "Pageviews", "...", timestamp="2025-04-15T10:00:00Z")]

        generate_change_summary(None, current, team=None)

        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        assert isinstance(messages[-1]["content"], str)

    @patch("posthog.temporal.subscriptions.llm_change_summary.get_llm_client")
    def test_skips_images_for_insights_not_in_current_states(self, mock_get_client):
        mock_client = mock_get_client.return_value
        mock_client.chat.completions.create.return_value = _mock_openai_response("- ok")

        current = [_make_state(1, "Pageviews", "...", timestamp="2025-04-15T10:00:00Z")]
        images = {1: b"pv", 99: b"stale-insight"}

        generate_change_summary(None, current, team=None, insight_images=images)

        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        image_parts = [p for p in messages[-1]["content"] if p.get("type") == "image_url"]
        assert len(image_parts) == 1

    @patch("posthog.temporal.subscriptions.llm_change_summary.get_llm_client")
    def test_user_tag_includes_delivery_id_when_provided(self, mock_get_client):
        mock_client = mock_get_client.return_value
        mock_client.chat.completions.create.return_value = _mock_openai_response("- ok")

        current = [_make_state(1, "Pageviews", "...", timestamp="2025-04-15T10:00:00Z")]

        generate_change_summary(None, current, team=None, delivery_id="abc-123")

        user_tag = mock_client.chat.completions.create.call_args.kwargs["user"]
        assert user_tag.endswith("-delivery-abc-123")
