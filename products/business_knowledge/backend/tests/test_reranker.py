import uuid

import pytest
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized

from products.business_knowledge.backend.logic import (
    KnowledgeSearchResult,
    _build_rerank_user_prompt,
    _parse_rerank_response,
    async_rerank_chunks,
    rerank_chunks,
)


def _make_result(chunk_id: uuid.UUID | None = None, content: str = "test content") -> KnowledgeSearchResult:
    return KnowledgeSearchResult(
        chunk_id=chunk_id or uuid.uuid4(),
        source_id=uuid.uuid4(),
        source_name="Test Source",
        source_type="text",
        document_id=uuid.uuid4(),
        document_title="Test Document",
        heading_path="Section 1",
        ordinal=0,
        content=content,
    )


class TestParseRerankResponse(unittest.TestCase):
    def test_valid_json_parses_correctly(self) -> None:
        id1 = uuid.uuid4()
        id2 = uuid.uuid4()
        candidate_ids = {id1, id2}

        response = f'[{{"id": "{id1}", "score": 0.95}}, {{"id": "{id2}", "score": 0.72}}]'
        result = _parse_rerank_response(response, candidate_ids)

        assert result is not None
        assert len(result) == 2
        assert result[0].chunk_id == id1
        assert result[0].score == 0.95
        assert result[1].chunk_id == id2
        assert result[1].score == 0.72

    @parameterized.expand(
        [
            ("invalid_json", "not valid json"),
            ("non_list_json", '{"id": "abc", "score": 0.5}'),
            ("empty_list", "[]"),
        ]
    )
    def test_malformed_response_returns_none(self, _name: str, response: str) -> None:
        result = _parse_rerank_response(response, {uuid.uuid4()})
        assert result is None

    def test_unknown_ids_are_filtered(self) -> None:
        known_id = uuid.uuid4()
        unknown_id = uuid.uuid4()
        candidate_ids = {known_id}

        response = f'[{{"id": "{unknown_id}", "score": 0.95}}, {{"id": "{known_id}", "score": 0.72}}]'
        result = _parse_rerank_response(response, candidate_ids)

        assert result is not None
        assert len(result) == 1
        assert result[0].chunk_id == known_id

    def test_duplicate_ids_are_deduped(self) -> None:
        id1 = uuid.uuid4()
        candidate_ids = {id1}

        response = f'[{{"id": "{id1}", "score": 0.95}}, {{"id": "{id1}", "score": 0.72}}]'
        result = _parse_rerank_response(response, candidate_ids)

        assert result is not None
        assert len(result) == 1
        assert result[0].score == 0.95

    def test_missing_fields_are_skipped(self) -> None:
        id1 = uuid.uuid4()
        candidate_ids = {id1}

        response = f'[{{"id": "{id1}"}}, {{"score": 0.5}}, {{"id": "{id1}", "score": 0.72}}]'
        result = _parse_rerank_response(response, candidate_ids)

        assert result is not None
        assert len(result) == 1
        assert result[0].chunk_id == id1
        assert result[0].score == 0.72

    @parameterized.expand(
        [
            (
                "invalid_uuid",
                lambda id1, id2: f'[{{"id": "not-a-uuid", "score": 0.95}}, {{"id": "{id1}", "score": 0.72}}]',
            ),
            (
                "invalid_score",
                lambda id1, id2: f'[{{"id": "{id1}", "score": "not-a-number"}}, {{"id": "{id2}", "score": 0.72}}]',
            ),
        ]
    )
    def test_invalid_fields_are_skipped(self, _name: str, make_response) -> None:  # noqa: ANN001
        id1 = uuid.uuid4()
        id2 = uuid.uuid4()
        candidate_ids = {id1, id2}

        response = make_response(id1, id2)
        result = _parse_rerank_response(response, candidate_ids)

        assert result is not None
        assert len(result) == 1

    def test_whitespace_around_json_is_handled(self) -> None:
        id1 = uuid.uuid4()
        candidate_ids = {id1}

        response = f'  \n[{{"id": "{id1}", "score": 0.95}}]\n  '
        result = _parse_rerank_response(response, candidate_ids)

        assert result is not None
        assert len(result) == 1


class TestBuildRerankUserPrompt(unittest.TestCase):
    @parameterized.expand(
        [
            ("contains_query", "test query", lambda p, r: "Query: test query" in p),
            ("contains_chunk_id", "query", lambda p, r: f"ID: {r.chunk_id}" in p),
            ("contains_heading", "query", lambda p, r: "Heading: Section 1" in p),
        ]
    )
    def test_prompt_contains_expected_content(self, _name: str, query: str, check) -> None:  # noqa: ANN001
        result = _make_result()
        prompt = _build_rerank_user_prompt(query, [result])
        assert check(prompt, result)

    def test_prompt_truncates_long_content(self) -> None:
        long_content = "x" * 1000
        result = _make_result(content=long_content)
        prompt = _build_rerank_user_prompt("query", [result])

        assert "..." in prompt
        assert len(prompt) < len(long_content) + 500


class TestRerankChunksSync(unittest.TestCase):
    team_id = 12345

    @parameterized.expand(
        [
            ("empty_results", [], 5, 0),
            ("fewer_than_top_k", 3, 5, 3),
        ]
    )
    def test_no_llm_call_needed(self, _name: str, num_results: int | list, top_k: int, expected_len: int) -> None:
        results = [] if num_results == [] else [_make_result() for _ in range(num_results)]
        result = rerank_chunks(self.team_id, "query", results, top_k=top_k)
        assert len(result) == expected_len
        if results:
            assert result == results

    @patch("posthog.llm.gateway_client.get_llm_client")
    def test_successful_rerank_reorders(self, mock_get_client: MagicMock) -> None:
        r1 = _make_result()
        r2 = _make_result()
        r3 = _make_result()
        results = [r1, r2, r3]

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content=f'[{{"id": "{r3.chunk_id}", "score": 0.9}}, {{"id": "{r1.chunk_id}", "score": 0.8}}]'
                )
            )
        ]
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        result = rerank_chunks(self.team_id, "query", results, top_k=2)

        assert len(result) == 2
        assert result[0].chunk_id == r3.chunk_id
        assert result[1].chunk_id == r1.chunk_id

    @parameterized.expand(
        [
            ("parse_failure", "invalid json", None),
            ("llm_exception", None, Exception("LLM error")),
        ]
    )
    @patch("posthog.llm.gateway_client.get_llm_client")
    def test_fallback_to_original_order(
        self, _name: str, response_content: str | None, side_effect: Exception | None, mock_get_client: MagicMock
    ) -> None:
        results = [_make_result() for _ in range(5)]

        mock_client = MagicMock()
        if side_effect:
            mock_client.chat.completions.create.side_effect = side_effect
        else:
            mock_response = MagicMock()
            mock_response.choices = [MagicMock(message=MagicMock(content=response_content))]
            mock_client.chat.completions.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        result = rerank_chunks(self.team_id, "query", results, top_k=3)

        assert len(result) == 3
        assert result == results[:3]

    @patch("posthog.llm.gateway_client.get_llm_client")
    def test_respects_top_k(self, mock_get_client: MagicMock) -> None:
        results = [_make_result() for _ in range(10)]

        mock_response = MagicMock()
        response_json = (
            "[" + ", ".join(f'{{"id": "{r.chunk_id}", "score": {0.9 - i * 0.1}}}' for i, r in enumerate(results)) + "]"
        )
        mock_response.choices = [MagicMock(message=MagicMock(content=response_json))]
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        result = rerank_chunks(self.team_id, "query", results, top_k=3)

        assert len(result) == 3

    @patch("posthog.llm.gateway_client.get_llm_client")
    def test_partial_ranking_returns_what_llm_provided(self, mock_get_client: MagicMock) -> None:
        results = [_make_result() for _ in range(10)]

        mock_response = MagicMock()
        response_json = (
            f'[{{"id": "{results[5].chunk_id}", "score": 0.9}}, {{"id": "{results[2].chunk_id}", "score": 0.7}}]'
        )
        mock_response.choices = [MagicMock(message=MagicMock(content=response_json))]
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        result = rerank_chunks(self.team_id, "query", results, top_k=5)

        assert len(result) == 2
        assert result[0].chunk_id == results[5].chunk_id
        assert result[1].chunk_id == results[2].chunk_id


TEAM_ID = 12345


@pytest.mark.asyncio
async def test_async_rerank_empty_results_returns_empty() -> None:
    result = await async_rerank_chunks(TEAM_ID, "query", [])
    assert result == []


@pytest.mark.asyncio
async def test_async_rerank_fewer_than_top_k_returns_all() -> None:
    results = [_make_result() for _ in range(3)]
    result = await async_rerank_chunks(TEAM_ID, "query", results, top_k=5)
    assert len(result) == 3
    assert result == results


@pytest.mark.asyncio
@patch("posthog.llm.gateway_client.get_async_llm_client")
async def test_async_rerank_successful_reorders(mock_get_client: MagicMock) -> None:
    r1 = _make_result()
    r2 = _make_result()
    r3 = _make_result()
    results = [r1, r2, r3]

    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(
                content=f'[{{"id": "{r3.chunk_id}", "score": 0.9}}, {{"id": "{r1.chunk_id}", "score": 0.8}}]'
            )
        )
    ]
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    mock_get_client.return_value = mock_client

    result = await async_rerank_chunks(TEAM_ID, "query", results, top_k=2)

    assert len(result) == 2
    assert result[0].chunk_id == r3.chunk_id
    assert result[1].chunk_id == r1.chunk_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response_content,side_effect",
    [
        ("invalid json", None),
        (None, Exception("LLM error")),
        (None, TimeoutError()),
    ],
    ids=["parse_failure", "llm_exception", "timeout"],
)
@patch("posthog.llm.gateway_client.get_async_llm_client")
async def test_async_rerank_fallback_to_original_order(
    mock_get_client: MagicMock, response_content: str | None, side_effect: Exception | None
) -> None:
    results = [_make_result() for _ in range(5)]

    mock_client = MagicMock()
    if side_effect:
        mock_client.chat.completions.create = AsyncMock(side_effect=side_effect)
    else:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content=response_content))]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    mock_get_client.return_value = mock_client

    result = await async_rerank_chunks(TEAM_ID, "query", results, top_k=3)

    assert len(result) == 3
    assert result == results[:3]
