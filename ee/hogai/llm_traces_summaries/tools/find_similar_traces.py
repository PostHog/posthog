import structlog

from posthog.schema import (
    CachedDocumentSimilarityQueryResponse,
    DateRange,
    DistanceFunc,
    DocumentSimilarityQuery,
    EmbeddedDocument,
    EmbeddingDistance,
    EmbeddingModelName,
    OrderBy,
    OrderDirection,
)

from posthog.hogql_queries.document_embeddings_query_runner import DocumentEmbeddingsQueryRunner
from posthog.models.team.team import Team

from ee.hogai.llm_traces_summaries.constants import (
    LLM_TRACES_SUMMARIES_DOCUMENT_TYPE,
    LLM_TRACES_SUMMARIES_PRODUCT,
    LLM_TRACES_SUMMARIES_SEARCH_QUERY_DOCUMENT_TYPE,
)
from ee.hogai.llm_traces_summaries.tools.embed_summaries import LLMTracesSummarizerEmbedder
from ee.models.llm_traces_summaries import LLMTraceSummary

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
    ) -> dict[str, tuple[EmbeddingDistance, LLMTraceSummary]]:
        """Search all summarized traces for the query and return the top similar traces."""
        embedder = LLMTracesSummarizerEmbedder(team=self._team, embedding_model_name=self._embedding_model_name)
        # Embed the search query and add to the document embeddings table to be able to search for similar summaries
        embedding_timestamp = embedder.embed_summaries_search_query_with_timestamp(
            query=query, request_id=request_id, summary_type=summary_type
        )
        similarity_query = DocumentSimilarityQuery(
            dateRange=date_range,
            distance_func=DistanceFunc.COSINE_DISTANCE,
            document_types=[LLM_TRACES_SUMMARIES_DOCUMENT_TYPE],  # Searching for summaries
            products=[LLM_TRACES_SUMMARIES_PRODUCT],
            # Searching for summaries with the explicit type of summary (like issues search)
            renderings=[summary_type.value],
            limit=top,
            model=self._embedding_model_name.value,
            order_by=OrderBy.DISTANCE,
            order_direction=OrderDirection.ASC,  # Best matches first
            origin=EmbeddedDocument(
                document_id=request_id,
                document_type=LLM_TRACES_SUMMARIES_SEARCH_QUERY_DOCUMENT_TYPE,  # Searching with a query
                product=LLM_TRACES_SUMMARIES_PRODUCT,
                timestamp=embedding_timestamp,
            ),
        )
        runner = DocumentEmbeddingsQueryRunner(query=similarity_query, team=self._team)
        response = runner.run()
        if not isinstance(response, CachedDocumentSimilarityQueryResponse):
            raise ValueError(
                f'Failed to get similarity results for query "{query}" ({request_id}) '
                "from team {self._team.id} when searching for summarized LLM traces"
            )
        distances: list[EmbeddingDistance] = response.results
        # Get relevant summaries for the document_id + team + summary type, newest first
        summaries = LLMTraceSummary.objects.filter(
            team=self._team,
            trace_id__in=[distance.result.document_id for distance in distances],
            trace_summary_type=summary_type,
        ).order_by("-created_at")
        if len(summaries) != len(distances):
            # Raise warning, but don't fail, as some results still be returned
            logger.warning(
                f"Number of summaries ({len(summaries)}) does not match number of distances ({len(distances)}) for que"
                f"query {query} ({request_id}) for team {self._team.id} when searching for summarized LLM traces"
            )
        # Combine distances with summaries
        results: dict[str, tuple[EmbeddingDistance, LLMTraceSummary]] = {}
        for distance in distances:
            summaries_for_trace = [x for x in summaries if x.trace_id == distance.result.document_id]
            if not summaries_for_trace:
                logger.warning(
                    f"No summary found for trace {distance.result.document_id} for query {query} ({request_id}) for team {self._team.id} when searching for summarized LLM traces"
                )
                continue
            results[distance.result.document_id] = (distance, summaries_for_trace[0])
        return results
