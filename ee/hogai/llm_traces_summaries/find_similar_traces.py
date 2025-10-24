import structlog
from ee.hogai.llm_traces_summaries.embed_summaries import (
    LLM_TRACES_SUMMARIES_DOCUMENT_TYPE_PREFIX,
    LLM_TRACES_SUMMARIES_PRODUCT,
    LLM_TRACES_SUMMARIES_SEARCH_QUERY_DOCUMENT_TYPE_PREFIX,
    LLMTracesSummarizerEmbedder,
)
from ee.models.llm_traces_summaries import LLMTraceSummary
from posthog.hogql_queries.document_embeddings_query_runner import DocumentEmbeddingsQueryRunner
from posthog.models.team.team import Team
from posthog.schema import (
    CachedDocumentSimilarityQueryResponse,
    DateRange,
    DistanceFunc,
    DocumentSimilarityQuery,
    EmbeddedDocument,
    EmbeddingModelName,
    OrderBy,
    OrderDirection,
)

logger = structlog.get_logger(__name__)


class LLMTracesSummarizerFinder:
    def __init__(
        self, team: Team, embedding_model_name: EmbeddingModelName = EmbeddingModelName.TEXT_EMBEDDING_3_LARGE_3072
    ):
        self._team = team
        self._embedding_model_name = embedding_model_name

    def find_top_similar_traces_for_query(
        self,
        query: str,
        request_id: str,
        top: int,
        date_range: DateRange,
        summary_type: LLMTraceSummary.LLMTraceSummaryType,
    ) -> list[dict[str, str]]:
        """Search all summarized traces for the query and return the top similar traces."""
        embedder = LLMTracesSummarizerEmbedder(team=self._team, embedding_model_name=self._embedding_model_name)
        # Embed the search query and add to the document embeddings table to be able to search for similar summaries
        embedding_timestamp = embedder.embed_summaries_search_query_with_timestamp(
            query=query, request_id=request_id, summary_type=summary_type
        )
        # Prepare types for origin (query, what to compare) and documents (summaries, what to compare with)
        summary_document_type = embedder.generate_document_type(
            prefix=LLM_TRACES_SUMMARIES_DOCUMENT_TYPE_PREFIX, summary_type=summary_type
        )
        summary_search_query_document_type = embedder.generate_document_type(
            prefix=LLM_TRACES_SUMMARIES_SEARCH_QUERY_DOCUMENT_TYPE_PREFIX, summary_type=summary_type
        )
        query = DocumentSimilarityQuery(
            dateRange=date_range,
            distance_func=DistanceFunc.COSINE_DISTANCE,
            document_types=[summary_document_type],
            limit=top,
            model=self._embedding_model_name.value,
            order_by=OrderBy.DISTANCE,
            order_direction=OrderDirection.DESC,
            origin=EmbeddedDocument(
                document_id=request_id,
                document_type=summary_search_query_document_type,
                product=LLM_TRACES_SUMMARIES_PRODUCT,
                timestamp=embedding_timestamp,
            ),
            products=[LLM_TRACES_SUMMARIES_PRODUCT],
            renderings=["backend"],
        )
        runner = DocumentEmbeddingsQueryRunner(query=query, team=self._team)
        response = runner.run()
        if not isinstance(response, CachedDocumentSimilarityQueryResponse):
            raise ValueError(
                f'Failed to get similarity results for query "{query}" ({request_id}) '
                "from team {self._team.id} when searching for summarized LLM traces"
            )
        return response
