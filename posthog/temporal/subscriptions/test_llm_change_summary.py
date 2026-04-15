from unittest.mock import MagicMock, patch

from posthog.temporal.subscriptions.llm_change_summary import build_prompt_messages, generate_change_summary


def _make_state(
    insight_id: int, name: str, summary: str, query_def: dict | None = None, timestamp: str = "2025-04-14T10:00:00Z"
) -> dict:
    return {
        "insight_id": insight_id,
        "insight_name": name,
        "query_definition": query_def or {"kind": "TrendsQuery"},
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

    def test_includes_query_definition_changes(self):
        previous = [
            _make_state(
                1, "Pageviews", "avg 100/day", query_def={"kind": "TrendsQuery", "series": [{"event": "$pageview"}]}
            )
        ]
        current = [
            _make_state(
                1,
                "Pageviews",
                "avg 150/day",
                query_def={"kind": "TrendsQuery", "series": [{"event": "$pageview"}, {"event": "signup"}]},
                timestamp="2025-04-15T10:00:00Z",
            )
        ]

        messages = build_prompt_messages(previous, current)

        user_content = messages[1]["content"]
        assert "query definition" in user_content.lower() or "modified" in user_content.lower()

    def test_no_query_definition_change_note_when_unchanged(self):
        same_query = {"kind": "TrendsQuery", "series": []}
        previous = [_make_state(1, "Pageviews", "avg 100/day", query_def=same_query)]
        current = [_make_state(1, "Pageviews", "avg 150/day", query_def=same_query, timestamp="2025-04-15T10:00:00Z")]

        messages = build_prompt_messages(previous, current)

        user_content = messages[1]["content"]
        assert "modified" not in user_content.lower()

    def test_includes_subscription_title(self):
        previous = [_make_state(1, "Pageviews", "avg 100/day")]
        current = [_make_state(1, "Pageviews", "avg 150/day", timestamp="2025-04-15T10:00:00Z")]

        messages = build_prompt_messages(previous, current, subscription_title="Weekly team report")

        titles = [m["content"] for m in messages if "Weekly team report" in m["content"]]
        assert len(titles) == 1

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


class TestGenerateChangeSummary:
    @patch("posthog.temporal.subscriptions.llm_change_summary.openai")
    def test_returns_markdown(self, mock_openai):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "- Pageviews increased by 50%\n- Signups stable"
        mock_response.usage = MagicMock(prompt_tokens=100, completion_tokens=20)
        mock_openai.chat.completions.create.return_value = mock_response

        previous = [_make_state(1, "Pageviews", "avg 100/day")]
        current = [_make_state(1, "Pageviews", "avg 150/day", timestamp="2025-04-15T10:00:00Z")]

        result = generate_change_summary(previous, current, team_id=1)

        assert "Pageviews increased" in result
        mock_openai.chat.completions.create.assert_called_once()
        call_kwargs = mock_openai.chat.completions.create.call_args
        assert call_kwargs.kwargs["model"] == "gpt-4.1-mini"
        assert call_kwargs.kwargs["max_tokens"] == 500
        assert call_kwargs.kwargs["timeout"] == 30

    @patch("posthog.temporal.subscriptions.llm_change_summary.openai")
    def test_handles_empty_content(self, mock_openai):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = None
        mock_response.usage = None
        mock_openai.chat.completions.create.return_value = mock_response

        result = generate_change_summary(
            [_make_state(1, "X", "data")],
            [_make_state(1, "X", "data", timestamp="2025-04-15T10:00:00Z")],
        )

        assert result == ""
