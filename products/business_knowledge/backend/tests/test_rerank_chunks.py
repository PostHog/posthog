from uuid import UUID, uuid4

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from anthropic.types import Message, TextBlock, Usage
from parameterized import parameterized

from products.business_knowledge.backend.constants import BK_RERANK_TIMEOUT
from products.business_knowledge.backend.llm_telemetry import RetrievalTrace
from products.business_knowledge.backend.logic import KnowledgeSearchResult, rerank_chunks


def _model_reply(text: str) -> Message:
    return Message(
        id="msg_test",
        type="message",
        role="assistant",
        model="claude-test",
        content=[TextBlock(type="text", text=text)],
        stop_reason="end_turn",
        stop_sequence=None,
        usage=Usage(input_tokens=1, output_tokens=1),
    )


def _gateway_client(reply: Message) -> MagicMock:
    client = MagicMock()
    client.with_options.return_value.__enter__.return_value.messages.create.return_value = reply
    return client


_BUILD_CLIENT = "products.business_knowledge.backend.logic.build_ai_gateway_anthropic_client"


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
        client = _gateway_client(_model_reply("\n".join(str(chunk_id) for chunk_id in reordered_ids)))

        with patch(_BUILD_CLIENT, return_value=client):
            reranked = rerank_chunks(self.team, "query", results, top_k=2, trace=RetrievalTrace(surface="api"))

        assert len(reranked) == 2
        assert [result.chunk_id for result in reranked] == reordered_ids[:2]

    @parameterized.expand(
        [
            ("parse_failure", 3, "invalid_response"),
            ("gateway_not_configured", 2, "init_error"),
        ]
    )
    def test_rrf_fallback_on_llm_failure(self, _name: str, num_results: int, failure_mode: str) -> None:
        results = [self._make_result(f"content {index}") for index in range(num_results)]
        top_k = 2

        if failure_mode == "invalid_response":
            patch_kwargs: dict = {"return_value": _gateway_client(_model_reply("not valid uuids here"))}
        else:
            patch_kwargs = {"side_effect": ValueError("AI_GATEWAY_URL is not set")}

        with patch(_BUILD_CLIENT, **patch_kwargs):
            reranked = rerank_chunks(self.team, "query", results, top_k=top_k, trace=RetrievalTrace(surface="api"))

        assert [result.chunk_id for result in reranked] == [result.chunk_id for result in results[:top_k]]

    def test_ranking_order(self) -> None:
        first = self._make_result("refund policy details")
        second = self._make_result("pricing tiers")
        third = self._make_result("deployment guide")
        results = [first, second, third]
        client = _gateway_client(_model_reply(f"{third.chunk_id}\n{first.chunk_id}\n{second.chunk_id}"))
        trace = RetrievalTrace(surface="support")

        with patch(_BUILD_CLIENT, return_value=client) as build_client:
            reranked = rerank_chunks(self.team, "how do refunds work", results, top_k=3, trace=trace)

        assert [result.chunk_id for result in reranked] == [third.chunk_id, first.chunk_id, second.chunk_id]
        assert build_client.call_args.kwargs["trace_id"] == trace.trace_id
        assert build_client.call_args.kwargs["ai_product"] == "business_knowledge"
        assert build_client.call_args.kwargs["team_id"] == self.team.id
        assert build_client.call_args.kwargs["properties"] == {
            "ai_feature": "bk_retrieval_rerank",
            "surface": "support",
        }
        assert client.with_options.call_args.kwargs == {"timeout": BK_RERANK_TIMEOUT, "max_retries": 3}
        assert client.with_options.return_value.__enter__.return_value.messages.create.call_args.kwargs[
            "extra_headers"
        ] == {
            "X-PostHog-Billable": "false",
            "X-PostHog-Privacy-Mode": "true",
        }
