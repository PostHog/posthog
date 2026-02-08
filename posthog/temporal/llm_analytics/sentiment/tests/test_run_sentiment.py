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

pytestmark = pytest.mark.usefixtures("_mock_heartbeat")


@pytest.fixture(autouse=True)
def _mock_heartbeat():
    with patch("temporalio.activity.heartbeat"):
        yield


def _make_event_data(
    ai_input=None,
    team_id=1,
    uuid="test-uuid",
    distinct_id="user-1",
    person_id=None,
    timestamp="2024-06-15 12:00:00.000000",
    extra_properties=None,
):
    properties = {}
    if ai_input is not None:
        properties["$ai_input"] = ai_input
    properties["$ai_trace_id"] = "trace-123"
    if extra_properties:
        properties.update(extra_properties)
    data = {
        "team_id": team_id,
        "uuid": uuid,
        "distinct_id": distinct_id,
        "person_id": person_id,
        "properties": properties,
    }
    if timestamp is not None:
        data["timestamp"] = timestamp
    return data


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
        mock_classify.side_effect = [
            SentimentResult(label="neutral", score=0.70, scores={"positive": 0.10, "neutral": 0.70, "negative": 0.20}),
            SentimentResult(label="negative", score=0.87, scores={"positive": 0.03, "neutral": 0.10, "negative": 0.87}),
        ]

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
        # Overall = average of scores: positive=(0.10+0.03)/2=0.065, neutral=(0.70+0.10)/2=0.40, negative=(0.20+0.87)/2=0.535
        assert result["label"] == "negative"
        assert result["score"] == pytest.approx(0.535)
        assert result["scores"]["negative"] == pytest.approx(0.535)
        assert result["scores"]["neutral"] == pytest.approx(0.40)
        assert result["scores"]["positive"] == pytest.approx(0.065)
        # Per-message results
        assert len(result["per_message"]) == 2
        assert result["per_message"][0]["label"] == "neutral"
        assert result["per_message"][1]["label"] == "negative"
        # Called once per user message
        assert mock_classify.call_count == 2

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

    @pytest.mark.asyncio
    @patch("posthog.temporal.llm_analytics.sentiment.run_sentiment.create_event")
    @patch("posthog.temporal.llm_analytics.sentiment.run_sentiment.Team")
    @patch("posthog.temporal.llm_analytics.sentiment.run_sentiment.classify")
    async def test_emits_per_message_sentiments(self, mock_classify, mock_team_cls, mock_create_event):
        mock_classify.side_effect = [
            SentimentResult(label="positive", score=0.95, scores={"positive": 0.95, "neutral": 0.03, "negative": 0.02}),
            SentimentResult(label="negative", score=0.80, scores={"positive": 0.05, "neutral": 0.15, "negative": 0.80}),
        ]
        mock_team_cls.objects.get.return_value = mock_team_cls

        ai_input = [
            {"role": "user", "content": "Great work!"},
            {"role": "user", "content": "This is broken"},
        ]
        event_data = _make_event_data(ai_input=ai_input)
        input = SentimentClassificationInput(event_data=event_data)

        result = await classify_sentiment_activity(input)

        # Overall = average: positive=(0.95+0.05)/2=0.50, neutral=(0.03+0.15)/2=0.09, negative=(0.02+0.80)/2=0.41
        assert result["label"] == "positive"
        mock_create_event.assert_called_once()
        call_kwargs = mock_create_event.call_args
        props = call_kwargs.kwargs.get("properties") or call_kwargs[1].get("properties")
        assert props["$ai_sentiment_label"] == "positive"
        # Per-message array present
        assert len(props["$ai_sentiment_messages"]) == 2
        assert props["$ai_sentiment_messages"][0]["label"] == "positive"
        assert props["$ai_sentiment_messages"][1]["label"] == "negative"
        # Uses generation event timestamp, not now()
        assert call_kwargs.kwargs.get("timestamp") or call_kwargs[1].get("timestamp") == "2024-06-15 12:00:00.000000"

    @pytest.mark.asyncio
    @patch("posthog.temporal.llm_analytics.sentiment.run_sentiment.database_sync_to_async")
    @patch("posthog.temporal.llm_analytics.sentiment.run_sentiment.classify")
    async def test_single_message_overall_matches(self, mock_classify, mock_db_async):
        mock_classify.return_value = SentimentResult(
            label="positive", score=0.92, scores={"positive": 0.92, "neutral": 0.05, "negative": 0.03}
        )

        async def fake_emit():
            pass

        mock_db_async.return_value = lambda: fake_emit()

        ai_input = [{"role": "user", "content": "I love this!"}]
        event_data = _make_event_data(ai_input=ai_input)
        input = SentimentClassificationInput(event_data=event_data)

        result = await classify_sentiment_activity(input)

        assert result["label"] == "positive"
        assert result["score"] == 0.92
        assert len(result["per_message"]) == 1
        assert result["per_message"][0]["label"] == "positive"

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

    @parameterized.expand(
        [
            ("uses_event_timestamp", "2024-06-15 12:00:00.000000", "2024-06-15 12:00:00.000000"),
            ("fallback_to_now_when_missing", None, None),
        ]
    )
    @pytest.mark.asyncio
    @patch("posthog.temporal.llm_analytics.sentiment.run_sentiment.create_event")
    @patch("posthog.temporal.llm_analytics.sentiment.run_sentiment.Team")
    @patch("posthog.temporal.llm_analytics.sentiment.run_sentiment.classify")
    async def test_timestamp_passthrough(
        self, _name, event_timestamp, expected_timestamp, mock_classify, mock_team_cls, mock_create_event
    ):
        mock_classify.return_value = SentimentResult(
            label="neutral", score=0.9, scores={"positive": 0.05, "neutral": 0.9, "negative": 0.05}
        )
        mock_team_cls.objects.get.return_value = mock_team_cls

        ai_input = [{"role": "user", "content": "hello"}]
        event_data = _make_event_data(ai_input=ai_input, timestamp=event_timestamp)
        input = SentimentClassificationInput(event_data=event_data)

        await classify_sentiment_activity(input)

        mock_create_event.assert_called_once()
        call_kwargs = mock_create_event.call_args
        actual_timestamp = call_kwargs.kwargs.get("timestamp") or call_kwargs[1].get("timestamp")
        if expected_timestamp is not None:
            assert actual_timestamp == expected_timestamp
        else:
            # Falls back to datetime.now(UTC) — just check it's a datetime, not a string
            from datetime import datetime

            assert isinstance(actual_timestamp, datetime)
