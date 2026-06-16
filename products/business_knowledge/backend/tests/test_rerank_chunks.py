from uuid import UUID, uuid4

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage

from products.business_knowledge.backend.logic import KnowledgeSearchResult, rerank_chunks


class TestRerankChunks(BaseTest):
    def _make_result(self, content: str, *, chunk_id: UUID | None = None) -> KnowledgeSearchResult:
        return KnowledgeSearchResult(
            chunk_id=chunk_id or uuid4(),
            source_id=uuid4(),
            source_name="Docs",
            source_type="text",
            document_id=uuid4(),
            document_title="Title",
            heading_path="",
            ordinal=0,
            content=content,
        )

    def test_empty_candidates_no_op(self) -> None:
        assert rerank_chunks(self.team, "refund policy", [], top_k=5) == []

    def test_respects_top_k(self) -> None:
        results = [self._make_result(f"content {index}") for index in range(5)]
        reordered_ids = [results[2].chunk_id, results[0].chunk_id, results[4].chunk_id]
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content="\n".join(str(chunk_id) for chunk_id in reordered_ids))

        with patch("products.business_knowledge.backend.logic.MaxChatAnthropic", return_value=mock_llm):
            reranked = rerank_chunks(self.team, "query", results, top_k=2)

        assert len(reranked) == 2
        assert [result.chunk_id for result in reranked] == reordered_ids[:2]

    def test_rrf_fallback_on_parse_failure(self) -> None:
        results = [self._make_result(f"content {index}") for index in range(3)]
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content="not valid uuids here")

        with patch("products.business_knowledge.backend.logic.MaxChatAnthropic", return_value=mock_llm):
            reranked = rerank_chunks(self.team, "query", results, top_k=2)

        assert [result.chunk_id for result in reranked] == [result.chunk_id for result in results[:2]]

    def test_rrf_fallback_on_model_failure(self) -> None:
        results = [self._make_result("alpha"), self._make_result("beta")]

        with patch(
            "products.business_knowledge.backend.logic.MaxChatAnthropic", side_effect=RuntimeError("llm unavailable")
        ):
            reranked = rerank_chunks(self.team, "query", results, top_k=2)

        assert [result.chunk_id for result in reranked] == [result.chunk_id for result in results]

    def test_ranking_order(self) -> None:
        first = self._make_result("refund policy details")
        second = self._make_result("pricing tiers")
        third = self._make_result("deployment guide")
        results = [first, second, third]
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content=f"{third.chunk_id}\n{first.chunk_id}\n{second.chunk_id}")

        with patch("products.business_knowledge.backend.logic.MaxChatAnthropic", return_value=mock_llm):
            reranked = rerank_chunks(self.team, "how do refunds work", results, top_k=3)

        assert [result.chunk_id for result in reranked] == [third.chunk_id, first.chunk_id, second.chunk_id]
