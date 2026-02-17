import json

import pytest
from unittest.mock import MagicMock, patch

from posthog.temporal.llm_analytics.sentiment.classify import (
    ClassifySentimentBatchInput,
    ClassifySentimentInput,
    classify_sentiment_activity,
    classify_sentiment_batch_activity,
)
from posthog.temporal.llm_analytics.sentiment.model import SentimentResult


def _make_generation_row(uuid: str, messages: list[dict], trace_id: str = "trace-1") -> tuple:
    return (uuid, json.dumps({"$ai_input": messages, "$ai_trace_id": trace_id}))


def _make_batch_row(uuid: str, messages: list[dict], trace_id: str) -> tuple:
    return (uuid, json.dumps({"$ai_input": messages, "$ai_trace_id": trace_id}), trace_id)


def _make_sentiment_result(label: str = "positive", score: float = 0.9) -> SentimentResult:
    scores = {"positive": 0.05, "neutral": 0.05, "negative": 0.05}
    scores[label] = score
    return SentimentResult(label=label, score=score, scores=scores)


def _mock_hogql_result(rows: list[tuple]) -> MagicMock:
    result = MagicMock()
    result.results = rows
    return result


_PATCH_HOGQL = "posthog.hogql.query.execute_hogql_query"
_PATCH_TEAM = "posthog.models.team.Team.objects"
_PATCH_CLASSIFY = "posthog.temporal.llm_analytics.sentiment.model.classify_batch"
_PATCH_CAP = "posthog.temporal.llm_analytics.sentiment.constants.MAX_TOTAL_CLASSIFICATIONS"


@pytest.fixture(autouse=True)
def _mock_team():
    with patch(_PATCH_TEAM) as mock_objects:
        mock_objects.get.return_value = MagicMock(id=1)
        yield


class TestClassifySentimentOnDemandActivity:
    @pytest.mark.asyncio
    @patch(_PATCH_HOGQL)
    async def test_empty_query_returns_neutral(self, mock_hogql: MagicMock):
        mock_hogql.return_value = _mock_hogql_result([])

        result = await classify_sentiment_activity(ClassifySentimentInput(team_id=1, trace_id="trace-1"))

        assert result["label"] == "neutral"
        assert result["generation_count"] == 0
        assert result["message_count"] == 0

    @pytest.mark.asyncio
    @patch(_PATCH_CLASSIFY)
    @patch(_PATCH_HOGQL)
    async def test_single_generation_single_message(self, mock_hogql: MagicMock, mock_classify: MagicMock):
        mock_hogql.return_value = _mock_hogql_result(
            [
                _make_generation_row("gen-1", [{"role": "user", "content": "I love this product"}]),
            ]
        )
        mock_classify.return_value = [_make_sentiment_result("positive", 0.9)]

        result = await classify_sentiment_activity(ClassifySentimentInput(team_id=1, trace_id="trace-1"))

        mock_classify.assert_called_once_with(["I love this product"])
        assert result["generation_count"] == 1
        assert result["message_count"] == 1
        assert result["label"] == "positive"

    @pytest.mark.asyncio
    @patch(_PATCH_CLASSIFY)
    @patch(_PATCH_HOGQL)
    async def test_multiple_generations_batched(self, mock_hogql: MagicMock, mock_classify: MagicMock):
        mock_hogql.return_value = _mock_hogql_result(
            [
                _make_generation_row("gen-1", [{"role": "user", "content": "msg-a"}]),
                _make_generation_row(
                    "gen-2",
                    [
                        {"role": "user", "content": "msg-b"},
                        {"role": "user", "content": "msg-c"},
                    ],
                ),
            ]
        )
        mock_classify.return_value = [
            _make_sentiment_result("positive", 0.9),
            _make_sentiment_result("negative", 0.8),
            _make_sentiment_result("neutral", 0.7),
        ]

        result = await classify_sentiment_activity(ClassifySentimentInput(team_id=1, trace_id="trace-1"))

        mock_classify.assert_called_once_with(["msg-a", "msg-b", "msg-c"])
        assert result["generation_count"] == 2
        assert result["message_count"] == 3
        assert "gen-1" in result["generations"]
        assert "gen-2" in result["generations"]
        assert len(result["generations"]["gen-2"]["messages"]) == 2

    @pytest.mark.asyncio
    @patch(_PATCH_CAP, 3)
    @patch(_PATCH_CLASSIFY)
    @patch(_PATCH_HOGQL)
    async def test_cap_limits_total_classifications(self, mock_hogql: MagicMock, mock_classify: MagicMock):
        mock_hogql.return_value = _mock_hogql_result(
            [
                _make_generation_row("gen-1", [{"role": "user", "content": f"msg-{i}"} for i in range(5)]),
                _make_generation_row(
                    "gen-2",
                    [
                        {"role": "user", "content": "should-not-reach"},
                    ],
                ),
            ]
        )
        mock_classify.return_value = [
            _make_sentiment_result("positive", 0.9),
            _make_sentiment_result("neutral", 0.5),
            _make_sentiment_result("negative", 0.8),
        ]

        result = await classify_sentiment_activity(ClassifySentimentInput(team_id=1, trace_id="trace-1"))

        texts_classified = mock_classify.call_args[0][0]
        assert len(texts_classified) == 3
        assert result["message_count"] == 3
        assert "gen-2" not in result["generations"]

    @pytest.mark.asyncio
    @patch(_PATCH_CLASSIFY)
    @patch(_PATCH_HOGQL)
    async def test_skips_generations_without_user_messages(self, mock_hogql: MagicMock, mock_classify: MagicMock):
        mock_hogql.return_value = _mock_hogql_result(
            [
                _make_generation_row("gen-1", [{"role": "assistant", "content": "no user msgs"}]),
                _make_generation_row("gen-2", [{"role": "user", "content": "a real message"}]),
            ]
        )
        mock_classify.return_value = [_make_sentiment_result("positive", 0.9)]

        result = await classify_sentiment_activity(ClassifySentimentInput(team_id=1, trace_id="trace-1"))

        mock_classify.assert_called_once_with(["a real message"])
        assert result["generation_count"] == 1
        assert "gen-1" not in result["generations"]
        assert "gen-2" in result["generations"]

    @pytest.mark.asyncio
    @patch(_PATCH_CLASSIFY)
    @patch(_PATCH_HOGQL)
    async def test_passes_absolute_date_range_to_query(self, mock_hogql: MagicMock, mock_classify: MagicMock):
        mock_hogql.return_value = _mock_hogql_result(
            [
                _make_generation_row("gen-1", [{"role": "user", "content": "hello"}]),
            ]
        )
        mock_classify.return_value = [_make_sentiment_result("positive", 0.9)]

        await classify_sentiment_activity(
            ClassifySentimentInput(
                team_id=1,
                trace_id="trace-1",
                date_from="2025-01-01",
                date_to="2025-01-31",
            )
        )

        call_kwargs = mock_hogql.call_args.kwargs
        placeholders = call_kwargs["placeholders"]
        assert placeholders["date_from"].value == "2025-01-01 00:00:00"
        assert placeholders["date_to"].value == "2025-01-31 00:00:00"

    @pytest.mark.asyncio
    @patch(_PATCH_CLASSIFY)
    @patch(_PATCH_HOGQL)
    async def test_resolves_relative_date_range(self, mock_hogql: MagicMock, mock_classify: MagicMock):
        mock_hogql.return_value = _mock_hogql_result(
            [
                _make_generation_row("gen-1", [{"role": "user", "content": "hello"}]),
            ]
        )
        mock_classify.return_value = [_make_sentiment_result("positive", 0.9)]

        await classify_sentiment_activity(
            ClassifySentimentInput(
                team_id=1,
                trace_id="trace-1",
                date_from="-1h",
                date_to=None,
            )
        )

        call_kwargs = mock_hogql.call_args.kwargs
        placeholders = call_kwargs["placeholders"]
        # relative date should be resolved to an absolute timestamp
        assert "20" in placeholders["date_from"].value  # starts with year
        assert ":" in placeholders["date_from"].value  # has time component
        assert placeholders["date_from"].value != "-1h"  # not the raw relative string


class TestClassifySentimentBatchActivity:
    @pytest.mark.asyncio
    @patch(_PATCH_HOGQL)
    async def test_empty_query_returns_neutral_for_all(self, mock_hogql: MagicMock):
        mock_hogql.return_value = _mock_hogql_result([])

        result = await classify_sentiment_batch_activity(ClassifySentimentBatchInput(team_id=1, trace_ids=["t1", "t2"]))

        assert result["t1"]["label"] == "neutral"
        assert result["t2"]["label"] == "neutral"

    @pytest.mark.asyncio
    @patch(_PATCH_CLASSIFY)
    @patch(_PATCH_HOGQL)
    async def test_multiple_traces_single_query(self, mock_hogql: MagicMock, mock_classify: MagicMock):
        mock_hogql.return_value = _mock_hogql_result(
            [
                _make_batch_row("gen-1", [{"role": "user", "content": "hello from t1"}], "t1"),
                _make_batch_row("gen-2", [{"role": "user", "content": "hello from t2"}], "t2"),
            ]
        )
        mock_classify.return_value = [
            _make_sentiment_result("positive", 0.9),
            _make_sentiment_result("negative", 0.8),
        ]

        result = await classify_sentiment_batch_activity(ClassifySentimentBatchInput(team_id=1, trace_ids=["t1", "t2"]))

        # One classify_batch call with all texts
        mock_classify.assert_called_once_with(["hello from t1", "hello from t2"])
        # One execute_hogql_query call (single ClickHouse query)
        mock_hogql.assert_called_once()

        assert result["t1"]["label"] == "positive"
        assert result["t1"]["generation_count"] == 1
        assert result["t2"]["label"] == "negative"
        assert result["t2"]["generation_count"] == 1

    @pytest.mark.asyncio
    @patch(_PATCH_CLASSIFY)
    @patch(_PATCH_HOGQL)
    async def test_trace_with_no_rows_gets_neutral(self, mock_hogql: MagicMock, mock_classify: MagicMock):
        mock_hogql.return_value = _mock_hogql_result(
            [
                _make_batch_row("gen-1", [{"role": "user", "content": "msg"}], "t1"),
            ]
        )
        mock_classify.return_value = [_make_sentiment_result("positive", 0.9)]

        result = await classify_sentiment_batch_activity(ClassifySentimentBatchInput(team_id=1, trace_ids=["t1", "t2"]))

        assert result["t1"]["label"] == "positive"
        assert result["t2"]["label"] == "neutral"
        assert result["t2"]["message_count"] == 0
