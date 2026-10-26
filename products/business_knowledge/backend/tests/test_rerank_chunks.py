from uuid import UUID, uuid4

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage
from parameterized import parameterized

from products.business_knowledge.backend.llm_telemetry import RetrievalTrace
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
        assert rerank_chunks(self.team, "refund policy", [], top_k=5, trace=RetrievalTrace(surface="api")) == []

    def test_respects_top_k(self) -> None:
        results = [self._make_result(f"content {index}") for index in range(5)]
        reordered_ids = [results[2].chunk_id, results[0].chunk_id, results[4].chunk_id]
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content="\n".join(str(chunk_id) for chunk_id in reordered_ids))

        with patch("products.business_knowledge.backend.logic.MaxChatAnthropic", return_value=mock_llm):
            reranked = rerank_chunks(self.team, "query", results, top_k=2, trace=RetrievalTrace(surface="api"))

        assert len(reranked) == 2
        assert [result.chunk_id for result in reranked] == reordered_ids[:2]

    @parameterized.expand(
        [
            ("parse_failure", 3, "invalid_response"),
            ("model_failure", 2, "init_error"),
        ]
    )
    def test_rrf_fallback_on_llm_failure(self, _name: str, num_results: int, failure_mode: str) -> None:
        results = [self._make_result(f"content {index}") for index in range(num_results)]
        top_k = 2

        if failure_mode == "invalid_response":
            mock_llm = MagicMock()
            mock_llm.invoke.return_value = AIMessage(content="not valid uuids here")
            patch_kwargs: dict = {"return_value": mock_llm}
        else:
            patch_kwargs = {"side_effect": RuntimeError("llm unavailable")}

        with patch("products.business_knowledge.backend.logic.MaxChatAnthropic", **patch_kwargs):
            reranked = rerank_chunks(self.team, "query", results, top_k=top_k, trace=RetrievalTrace(surface="api"))

        assert [result.chunk_id for result in reranked] == [result.chunk_id for result in results[:top_k]]

    def test_ranking_order(self) -> None:
        first = self._make_result("refund policy details")
        second = self._make_result("pricing tiers")
        third = self._make_result("deployment guide")
        results = [first, second, third]
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content=f"{third.chunk_id}\n{first.chunk_id}\n{second.chunk_id}")
        trace = RetrievalTrace(surface="support")

        with (
            patch("products.business_knowledge.backend.logic.MaxChatAnthropic", return_value=mock_llm),
            patch(
                "products.business_knowledge.backend.llm_telemetry.posthoganalytics",
                MagicMock(default_client=MagicMock(), disabled=False),
            ),
        ):
            reranked = rerank_chunks(self.team, "how do refunds work", results, top_k=3, trace=trace)

        assert [result.chunk_id for result in reranked] == [third.chunk_id, first.chunk_id, second.chunk_id]
        callback = mock_llm.invoke.call_args.kwargs["config"]["callbacks"][0]
        assert callback._trace_id == trace.trace_id
        assert callback._privacy_mode is True
        assert callback._properties == {
            "ai_product": "business_knowledge",
            "ai_feature": "bk_retrieval_rerank",
            "team_id": self.team.id,
            "surface": "support",
        }
