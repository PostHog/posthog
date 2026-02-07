"""Tests for sentiment classification Temporal workflow and activity."""

import json

import pytest
from unittest.mock import patch

from parameterized import parameterized

from posthog.temporal.llm_analytics.sentiment.model import SentimentResult
from posthog.temporal.llm_analytics.sentiment.run_sentiment import (
    SentimentClassificationInput,
    classify_sentiment_activity,
)


def _make_event_data(
    ai_input=None,
    team_id=1,
    uuid="test-uuid",
    distinct_id="user-1",
    person_id=None,
    extra_properties=None,
):
    properties = {}
    if ai_input is not None:
        properties["$ai_input"] = ai_input
    properties["$ai_trace_id"] = "trace-123"
    if extra_properties:
        properties.update(extra_properties)
    return {
        "team_id": team_id,
        "uuid": uuid,
        "distinct_id": distinct_id,
        "person_id": person_id,
        "properties": properties,
    }


class TestSentimentClassificationInput:
    def test_properties_to_log(self):
        input = SentimentClassificationInput(event_data={"team_id": 1, "uuid": "abc"})
        assert input.properties_to_log == {"team_id": 1, "event_uuid": "abc"}

    def test_parse_inputs(self):
        from posthog.temporal.llm_analytics.sentiment.run_sentiment import RunSentimentClassificationWorkflow

        event_data = {"team_id": 1, "uuid": "abc"}
        result = RunSentimentClassificationWorkflow.parse_inputs([json.dumps(event_data)])
        assert result.event_data == event_data


class TestClassifySentimentActivity:
    @pytest.mark.asyncio
    @patch("posthog.temporal.llm_analytics.sentiment.run_sentiment.classify")
    @patch("posthog.temporal.llm_analytics.sentiment.run_sentiment.database_sync_to_async")
    async def test_skips_when_no_ai_input(self, mock_db_async, mock_classify):
        event_data = _make_event_data(ai_input=None)
        input = SentimentClassificationInput(event_data=event_data)

        result = await classify_sentiment_activity(input)

        assert result["skipped"] is True
        assert result["skip_reason"] == "no_ai_input"
        mock_classify.assert_not_called()

    @pytest.mark.asyncio
    @patch("posthog.temporal.llm_analytics.sentiment.run_sentiment.classify")
    @patch("posthog.temporal.llm_analytics.sentiment.run_sentiment.database_sync_to_async")
    async def test_skips_when_no_user_messages(self, mock_db_async, mock_classify):
        ai_input = [
            {"role": "system", "content": "You are helpful"},
            {"role": "assistant", "content": "Hello!"},
        ]
        event_data = _make_event_data(ai_input=ai_input)
        input = SentimentClassificationInput(event_data=event_data)

        result = await classify_sentiment_activity(input)

        assert result["skipped"] is True
        assert result["skip_reason"] == "no_user_messages"
        mock_classify.assert_not_called()

    @pytest.mark.asyncio
    @patch("posthog.temporal.llm_analytics.sentiment.run_sentiment.database_sync_to_async")
    @patch("posthog.temporal.llm_analytics.sentiment.run_sentiment.classify")
    async def test_classifies_user_messages(self, mock_classify, mock_db_async):
        mock_classify.return_value = SentimentResult(
            label="negative",
            score=0.87,
            scores={"positive": 0.03, "neutral": 0.10, "negative": 0.87},
        )

        # Make database_sync_to_async return a coroutine that resolves
        async def fake_emit():
            pass

        mock_db_async.return_value = lambda: fake_emit()

        ai_input = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "I need help"},
            {"role": "assistant", "content": "How can I help?"},
            {"role": "user", "content": "I'm frustrated"},
        ]
        event_data = _make_event_data(ai_input=ai_input)
        input = SentimentClassificationInput(event_data=event_data)

        result = await classify_sentiment_activity(input)

        assert result["skipped"] is False
        assert result["label"] == "negative"
        assert result["score"] == 0.87
        assert result["scores"]["negative"] == 0.87
        mock_classify.assert_called_once()

    @pytest.mark.asyncio
    @patch("posthog.temporal.llm_analytics.sentiment.run_sentiment.classify")
    @patch("posthog.temporal.llm_analytics.sentiment.run_sentiment.database_sync_to_async")
    async def test_handles_string_properties(self, mock_db_async, mock_classify):
        """Test that JSON string properties are parsed correctly."""
        event_data = {
            "team_id": 1,
            "uuid": "test-uuid",
            "distinct_id": "user-1",
            "person_id": None,
            "properties": json.dumps({"$ai_trace_id": "trace-1"}),
        }
        input = SentimentClassificationInput(event_data=event_data)

        result = await classify_sentiment_activity(input)

        assert result["skipped"] is True
        assert result["skip_reason"] == "no_ai_input"

    @parameterized.expand(
        [
            ("generation_id", {"$ai_generation_id": "gen-abc"}, None, "gen-abc"),
            ("span_id", {}, "span-xyz", "span-xyz"),
            ("generation_id_over_span_id", {"$ai_generation_id": "gen-abc"}, "span-xyz", "gen-abc"),
            ("fallback_to_event_uuid", {}, None, "test-uuid"),
        ]
    )
    @pytest.mark.asyncio
    @patch("posthog.temporal.llm_analytics.sentiment.run_sentiment.create_event")
    @patch("posthog.temporal.llm_analytics.sentiment.run_sentiment.Team")
    @patch("posthog.temporal.llm_analytics.sentiment.run_sentiment.classify")
    async def test_parent_id_resolution(
        self, _name, extra_props, span_id, expected_parent_id, mock_classify, mock_team_cls, mock_create_event
    ):
        mock_classify.return_value = SentimentResult(
            label="neutral", score=0.9, scores={"positive": 0.05, "neutral": 0.9, "negative": 0.05}
        )
        mock_team_cls.objects.get.return_value = mock_team_cls

        props = (
            {"$ai_generation_id": extra_props.get("$ai_generation_id")} if "$ai_generation_id" in extra_props else {}
        )
        if span_id:
            props["$ai_span_id"] = span_id

        ai_input = [{"role": "user", "content": "hello"}]
        event_data = _make_event_data(ai_input=ai_input, extra_properties=props)
        input = SentimentClassificationInput(event_data=event_data)

        result = await classify_sentiment_activity(input)

        assert result["skipped"] is False
        mock_create_event.assert_called_once()
        call_kwargs = mock_create_event.call_args
        sentiment_properties = call_kwargs.kwargs.get("properties") or call_kwargs[1].get("properties")
        assert sentiment_properties["$ai_parent_id"] == expected_parent_id
