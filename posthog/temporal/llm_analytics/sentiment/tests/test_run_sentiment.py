"""Tests for sentiment classification Temporal workflow and activity."""

import json

import pytest
from unittest.mock import patch

from parameterized import parameterized

from posthog.temporal.llm_analytics.sentiment.model import SentimentResult
from posthog.temporal.llm_analytics.sentiment.run_sentiment import (
    SentimentClassificationInput,
    _classify_single_event,
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
        inp = SentimentClassificationInput(events=[{"uuid": "abc"}, {"uuid": "def"}])
        assert inp.properties_to_log == {"event_count": 2, "event_uuids": ["abc", "def"]}

    def test_parse_inputs(self):
        from posthog.temporal.llm_analytics.sentiment.run_sentiment import RunSentimentClassificationWorkflow

        events = [{"team_id": 1, "uuid": "abc"}, {"team_id": 1, "uuid": "def"}]
        result = RunSentimentClassificationWorkflow.parse_inputs([json.dumps(events)])
        assert result.events == events


class TestClassifySingleEvent:
    @pytest.mark.asyncio
    @patch("posthog.temporal.llm_analytics.sentiment.run_sentiment.classify")
    @patch("posthog.temporal.llm_analytics.sentiment.run_sentiment.database_sync_to_async")
    async def test_skips_when_no_ai_input(self, mock_db_async, mock_classify):
        event_data = _make_event_data(ai_input=None)
        result = await _classify_single_event(event_data)

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
        result = await _classify_single_event(event_data)

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
        result = await _classify_single_event(event_data)

        assert result["skipped"] is False
        assert result["label"] == "negative"
        assert result["score"] == pytest.approx(0.535)
        assert result["scores"]["negative"] == pytest.approx(0.535)
        assert result["scores"]["neutral"] == pytest.approx(0.40)
        assert result["scores"]["positive"] == pytest.approx(0.065)
        assert len(result["per_message"]) == 2
        assert result["per_message"][0]["label"] == "neutral"
        assert result["per_message"][1]["label"] == "negative"
        assert mock_classify.call_count == 2

    @pytest.mark.asyncio
    @patch("posthog.temporal.llm_analytics.sentiment.run_sentiment.classify")
    @patch("posthog.temporal.llm_analytics.sentiment.run_sentiment.database_sync_to_async")
    async def test_handles_string_properties(self, mock_db_async, mock_classify):
        event_data = {
            "team_id": 1,
            "uuid": "test-uuid",
            "distinct_id": "user-1",
            "person_id": None,
            "properties": json.dumps({"$ai_trace_id": "trace-1"}),
        }
        result = await _classify_single_event(event_data)

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
        result = await _classify_single_event(event_data)

        assert result["label"] == "positive"
        mock_create_event.assert_called_once()
        call_kwargs = mock_create_event.call_args
        props = call_kwargs.kwargs.get("properties") or call_kwargs[1].get("properties")
        assert props["$ai_sentiment_label"] == "positive"
        assert props["$ai_sentiment_positive_max_score"] == pytest.approx(0.95)
        assert props["$ai_sentiment_negative_max_score"] == pytest.approx(0.80)
        assert len(props["$ai_sentiment_messages"]) == 2
        assert props["$ai_sentiment_messages"][0]["label"] == "positive"
        assert props["$ai_sentiment_messages"][1]["label"] == "negative"
        assert (call_kwargs.kwargs.get("timestamp") or call_kwargs[1].get("timestamp")) == "2024-06-15 12:00:00.000000"

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
        result = await _classify_single_event(event_data)

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
        result = await _classify_single_event(event_data)

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

        await _classify_single_event(event_data)

        mock_create_event.assert_called_once()
        call_kwargs = mock_create_event.call_args
        actual_timestamp = call_kwargs.kwargs.get("timestamp") or call_kwargs[1].get("timestamp")
        if expected_timestamp is not None:
            assert actual_timestamp == expected_timestamp
        else:
            from datetime import datetime

            assert isinstance(actual_timestamp, datetime)


class TestClassifySentimentActivity:
    @pytest.mark.asyncio
    @patch("posthog.temporal.llm_analytics.sentiment.run_sentiment.database_sync_to_async")
    @patch("posthog.temporal.llm_analytics.sentiment.run_sentiment.classify")
    async def test_batch_multiple_events_all_succeed(self, mock_classify, mock_db_async):
        mock_classify.return_value = SentimentResult(
            label="positive", score=0.90, scores={"positive": 0.90, "neutral": 0.07, "negative": 0.03}
        )

        async def fake_emit():
            pass

        mock_db_async.return_value = lambda: fake_emit()

        events = [
            _make_event_data(ai_input=[{"role": "user", "content": "Great!"}], uuid="evt-1"),
            _make_event_data(ai_input=[{"role": "user", "content": "Awesome!"}], uuid="evt-2"),
            _make_event_data(ai_input=[{"role": "user", "content": "Love it!"}], uuid="evt-3"),
        ]
        inp = SentimentClassificationInput(events=events)
        result = await classify_sentiment_activity(inp)

        assert result["processed"] == 3
        assert result["skipped"] == 0
        assert result["failed"] == 0
        assert len(result["results"]) == 3
        assert all(r["label"] == "positive" for r in result["results"])

    @pytest.mark.asyncio
    @patch("posthog.temporal.llm_analytics.sentiment.run_sentiment.database_sync_to_async")
    @patch("posthog.temporal.llm_analytics.sentiment.run_sentiment.classify")
    async def test_batch_partial_failure(self, mock_classify, mock_db_async):
        call_count = 0

        def classify_side_effect(text):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("ONNX inference failed")
            return SentimentResult(
                label="neutral", score=0.80, scores={"positive": 0.10, "neutral": 0.80, "negative": 0.10}
            )

        mock_classify.side_effect = classify_side_effect

        async def fake_emit():
            pass

        mock_db_async.return_value = lambda: fake_emit()

        events = [
            _make_event_data(ai_input=[{"role": "user", "content": "Hello"}], uuid="evt-1"),
            _make_event_data(ai_input=[{"role": "user", "content": "World"}], uuid="evt-2"),
            _make_event_data(ai_input=[{"role": "user", "content": "Bye"}], uuid="evt-3"),
        ]
        inp = SentimentClassificationInput(events=events)
        result = await classify_sentiment_activity(inp)

        assert result["processed"] == 2
        assert result["failed"] == 1
        assert result["skipped"] == 0
        assert len(result["results"]) == 3

    @pytest.mark.asyncio
    @patch("posthog.temporal.llm_analytics.sentiment.run_sentiment.classify")
    @patch("posthog.temporal.llm_analytics.sentiment.run_sentiment.database_sync_to_async")
    async def test_batch_all_skipped_no_user_messages(self, mock_db_async, mock_classify):
        events = [
            _make_event_data(
                ai_input=[{"role": "system", "content": "System msg"}],
                uuid="evt-1",
            ),
            _make_event_data(ai_input=None, uuid="evt-2"),
        ]
        inp = SentimentClassificationInput(events=events)
        result = await classify_sentiment_activity(inp)

        assert result["processed"] == 0
        assert result["skipped"] == 2
        assert result["failed"] == 0
        mock_classify.assert_not_called()

    @pytest.mark.asyncio
    @patch("posthog.temporal.llm_analytics.sentiment.run_sentiment.database_sync_to_async")
    @patch("posthog.temporal.llm_analytics.sentiment.run_sentiment.classify")
    async def test_batch_single_event_matches_previous_behavior(self, mock_classify, mock_db_async):
        mock_classify.return_value = SentimentResult(
            label="positive", score=0.92, scores={"positive": 0.92, "neutral": 0.05, "negative": 0.03}
        )

        async def fake_emit():
            pass

        mock_db_async.return_value = lambda: fake_emit()

        events = [_make_event_data(ai_input=[{"role": "user", "content": "I love this!"}])]
        inp = SentimentClassificationInput(events=events)
        result = await classify_sentiment_activity(inp)

        assert result["processed"] == 1
        assert result["skipped"] == 0
        assert result["failed"] == 0
        assert result["results"][0]["label"] == "positive"
        assert result["results"][0]["score"] == 0.92
