import pytest
from unittest.mock import MagicMock, patch

from posthog.temporal.llm_analytics.sentiment.activities import classify_sentiment_activity
from posthog.temporal.llm_analytics.sentiment.schema import ClassifySentimentInput, SentimentResult


def _make_row(uuid: str, messages: list[dict]) -> tuple:
    return (uuid, messages)


def _make_sentiment_result(label: str = "positive", score: float = 0.9) -> SentimentResult:
    scores = {"positive": 0.05, "neutral": 0.05, "negative": 0.05}
    scores[label] = score
    return SentimentResult(label=label, score=score, scores=scores)


def _mock_hogql_result(rows: list[tuple]) -> MagicMock:
    result = MagicMock()
    result.results = rows
    return result


def _gen_input(generation_id: str = "gen-1", **kwargs) -> ClassifySentimentInput:
    return ClassifySentimentInput(team_id=1, ids=[generation_id], analysis_level="generation", **kwargs)


_PATCH_HOGQL = "posthog.hogql.query.execute_hogql_query"
_PATCH_TEAM = "posthog.models.team.Team.objects"
_PATCH_CLASSIFY = "posthog.temporal.llm_analytics.sentiment.model.classify"


@pytest.fixture(autouse=True)
def _mock_team():
    with patch(_PATCH_TEAM) as mock_objects:
        mock_objects.get.return_value = MagicMock(id=1)
        yield


class TestGenerationLevelSingle:
    @pytest.mark.asyncio
    @patch(_PATCH_HOGQL)
    async def test_empty_query_returns_neutral(self, mock_hogql: MagicMock):
        mock_hogql.return_value = _mock_hogql_result([])

        result = await classify_sentiment_activity(_gen_input())

        assert result["gen-1"]["label"] == "neutral"
        assert result["gen-1"]["messages"] == {}

    @pytest.mark.asyncio
    @patch(_PATCH_CLASSIFY)
    @patch(_PATCH_HOGQL)
    async def test_single_generation_single_message(self, mock_hogql: MagicMock, mock_classify: MagicMock):
        mock_hogql.return_value = _mock_hogql_result(
            [
                _make_row("gen-1", [{"role": "user", "content": "I love this product"}]),
            ]
        )
        mock_classify.return_value = [_make_sentiment_result("positive", 0.9)]

        result = await classify_sentiment_activity(_gen_input())

        mock_classify.assert_called_once_with(["I love this product"])
        assert result["gen-1"]["label"] == "positive"
        assert "0" in result["gen-1"]["messages"]
        # message dict keys must be strings for orjson serialization
        assert all(isinstance(k, str) for k in result["gen-1"]["messages"].keys())

    @pytest.mark.asyncio
    @patch(_PATCH_CLASSIFY)
    @patch(_PATCH_HOGQL)
    async def test_single_generation_multiple_messages(self, mock_hogql: MagicMock, mock_classify: MagicMock):
        mock_hogql.return_value = _mock_hogql_result(
            [
                _make_row(
                    "gen-1",
                    [
                        {"role": "user", "content": "msg-a"},
                        {"role": "assistant", "content": "reply"},
                        {"role": "user", "content": "msg-b"},
                    ],
                ),
            ]
        )
        mock_classify.return_value = [
            _make_sentiment_result("positive", 0.9),
            _make_sentiment_result("negative", 0.8),
        ]

        result = await classify_sentiment_activity(_gen_input())

        mock_classify.assert_called_once_with(["msg-a", "msg-b"])
        assert len(result["gen-1"]["messages"]) == 2

    @pytest.mark.asyncio
    @patch(_PATCH_CLASSIFY)
    @patch(_PATCH_HOGQL)
    async def test_skips_generations_without_user_messages(self, mock_hogql: MagicMock, mock_classify: MagicMock):
        mock_hogql.return_value = _mock_hogql_result(
            [
                _make_row("gen-1", [{"role": "assistant", "content": "no user msgs"}]),
            ]
        )

        result = await classify_sentiment_activity(_gen_input())

        mock_classify.assert_not_called()
        assert result["gen-1"]["label"] == "neutral"
        assert result["gen-1"]["messages"] == {}


class TestGenerationLevelBatch:
    @pytest.mark.asyncio
    @patch(_PATCH_HOGQL)
    async def test_empty_query_returns_neutral_for_all(self, mock_hogql: MagicMock):
        mock_hogql.return_value = _mock_hogql_result([])

        result = await classify_sentiment_activity(
            ClassifySentimentInput(team_id=1, ids=["gen-1", "gen-2"], analysis_level="generation")
        )

        assert result["gen-1"]["label"] == "neutral"
        assert result["gen-2"]["label"] == "neutral"

    @pytest.mark.asyncio
    @patch(_PATCH_CLASSIFY)
    @patch(_PATCH_HOGQL)
    async def test_multiple_generations_single_query(self, mock_hogql: MagicMock, mock_classify: MagicMock):
        mock_hogql.return_value = _mock_hogql_result(
            [
                _make_row("gen-1", [{"role": "user", "content": "hello from gen-1"}]),
                _make_row("gen-2", [{"role": "user", "content": "hello from gen-2"}]),
            ]
        )
        mock_classify.return_value = [
            _make_sentiment_result("positive", 0.9),
            _make_sentiment_result("negative", 0.8),
        ]

        result = await classify_sentiment_activity(
            ClassifySentimentInput(team_id=1, ids=["gen-1", "gen-2"], analysis_level="generation")
        )

        mock_classify.assert_called_once_with(["hello from gen-1", "hello from gen-2"])
        mock_hogql.assert_called_once()

        assert result["gen-1"]["label"] == "positive"
        assert result["gen-2"]["label"] == "negative"

    @pytest.mark.asyncio
    @patch(_PATCH_CLASSIFY)
    @patch(_PATCH_HOGQL)
    async def test_generation_with_no_rows_gets_neutral(self, mock_hogql: MagicMock, mock_classify: MagicMock):
        mock_hogql.return_value = _mock_hogql_result(
            [
                _make_row("gen-1", [{"role": "user", "content": "msg"}]),
            ]
        )
        mock_classify.return_value = [_make_sentiment_result("positive", 0.9)]

        result = await classify_sentiment_activity(
            ClassifySentimentInput(team_id=1, ids=["gen-1", "gen-2"], analysis_level="generation")
        )

        assert result["gen-1"]["label"] == "positive"
        assert result["gen-2"]["label"] == "neutral"
        assert result["gen-2"]["messages"] == {}

    @pytest.mark.asyncio
    @patch(_PATCH_CLASSIFY)
    @patch(_PATCH_HOGQL)
    async def test_passes_date_range_to_query(self, mock_hogql: MagicMock, mock_classify: MagicMock):
        mock_hogql.return_value = _mock_hogql_result(
            [
                _make_row("gen-1", [{"role": "user", "content": "hello"}]),
            ]
        )
        mock_classify.return_value = [_make_sentiment_result("positive", 0.9)]

        await classify_sentiment_activity(_gen_input(date_from="2025-01-01", date_to="2025-01-31"))

        call_kwargs = mock_hogql.call_args.kwargs
        placeholders = call_kwargs["placeholders"]
        assert placeholders["date_from"].value == "2025-01-01 00:00:00"
        assert placeholders["date_to"].value == "2025-01-31 00:00:00"


class TestDualWriteInTraceActivity:
    @pytest.mark.asyncio
    @patch(_PATCH_CLASSIFY)
    @patch(_PATCH_HOGQL)
    async def test_trace_activity_dual_writes_generation_cache(self, mock_hogql: MagicMock, mock_classify: MagicMock):
        mock_hogql.return_value = _mock_hogql_result(
            [
                ("gen-1", [{"role": "user", "content": "hello"}], "trace-1"),
            ]
        )
        mock_classify.return_value = [_make_sentiment_result("positive", 0.9)]

        with patch("django.core.cache.cache") as mock_cache:
            mock_cache.set_many = MagicMock()

            await classify_sentiment_activity(ClassifySentimentInput(team_id=1, ids=["trace-1"]))

            mock_cache.set_many.assert_called_once()
            cache_keys = mock_cache.set_many.call_args[0][0]
            # Trace-level and generation-level keys should both be in the single set_many call
            assert "llma_sentiment:trace:1:trace-1" in cache_keys
            assert "llma_sentiment:generation:1:gen-1" in cache_keys
            # Generation cache entry has the unified shape
            gen_cached = cache_keys["llma_sentiment:generation:1:gen-1"]
            assert gen_cached["label"] == "positive"
            assert "messages" in gen_cached
            assert "message_count" in gen_cached
