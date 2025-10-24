import httpx
import structlog
from ee.hogai.llm_traces_summaries.tools.embeddings import get_embeddings
from posthog.models.team.team import Team
from posthog.schema import DateRange, EmbeddingModelName

logger = structlog.get_logger(__name__)


class LLMTracesSummarizerFinder:
    def __init__(
        self, team: Team, embedding_model_name: EmbeddingModelName = EmbeddingModelName.TEXT_EMBEDDING_3_LARGE_3072
    ):
        self._team = team
        self._embedding_model_name = embedding_model_name

    async def find_top_similar_traces_for_query(
        self, query: str, top: int, date_range: DateRange
    ) -> list[dict[str, str]]:
        """Search all summarized traces for the query and return the top similar traces."""
        query_embedding = await self._get_query_embedding(query=query)

    async def _get_query_embedding(self, query: str) -> list[float]:
        """Get the embedding for the query."""
        with httpx.AsyncClient() as client:
            # Using direct call instead of Kafka product as there's no need to store the embeddings for the search query
            embeddings = await get_embeddings(
                client=client,
                embeddings_input=[query],
                embedding_model_name=self._embedding_model_name,
                label="top_similar_traces_search_query",
            )
        if not embeddings:
            logger.exception("No embeddings generated for query when finding top similar traces")
            return []
        query_embedding = embeddings[0]  # We sent one text, so we expect one embedding
        return query_embedding

    async def _get_similar_traces(self, query_embedding: list[float]) -> list[dict[str, str]]:
        """Get the similar traces for the query embedding."""
        pass
