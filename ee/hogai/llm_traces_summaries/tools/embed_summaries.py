import time
from datetime import datetime

from django.utils import timezone

from posthog.schema import EmbeddingModelName

from posthog.clickhouse.client import sync_execute
from posthog.kafka_client.client import KafkaProducer
from posthog.models.team.team import Team

from ee.hogai.llm_traces_summaries.constants import (
    DOCUMENT_EMBEDDINGS_TOPIC,
    LLM_TRACES_SUMMARIES_DOCUMENT_TYPE,
    LLM_TRACES_SUMMARIES_PRODUCT,
    LLM_TRACES_SUMMARIES_SEARCH_QUERY_DOCUMENT_TYPE,
    LLM_TRACES_SUMMARIES_SEARCH_QUERY_MAX_ATTEMPTS,
    LLM_TRACES_SUMMARIES_SEARCH_QUERY_POLL_INTERVAL_SECONDS,
)
from ee.models.llm_traces_summaries import LLMTraceSummary


class LLMTracesSummarizerEmbedder:
    def __init__(
        self, team: Team, embedding_model_name: EmbeddingModelName = EmbeddingModelName.TEXT_EMBEDDING_3_LARGE_3072
    ):
        self._team = team
        self._producer = KafkaProducer()
        self._embedding_model_name = embedding_model_name

    def embed_summaries(self, summarized_traces: dict[str, str], summary_type: LLMTraceSummary.LLMTraceSummaryType):
        """Generated embeddings for all summaries of stringified traces."""
        # Add all the summaries to the Kafka producer to be stored in ClickHouse
        for trace_id, summary in summarized_traces.items():
            self._embed_document(
                content=summary,
                document_id=trace_id,
                document_type=LLM_TRACES_SUMMARIES_DOCUMENT_TYPE,
                product=LLM_TRACES_SUMMARIES_PRODUCT,
                rendering=summary_type.value,
            )
        # No immediate results needed, so return nothing
        return None

    def embed_summaries_search_query_with_timestamp(
        self, query: str, request_id: str, summary_type: LLMTraceSummary.LLMTraceSummaryType
    ) -> datetime:
        """
        Generate and return embeddings for the search query to get the most similar summaries.
        We expect query to come either from conversation or from a search request.
        """
        # Embed the search query and store the timestamp it was generated at
        timestamp = self._embed_document(
            content=query,
            document_id=request_id,
            document_type=LLM_TRACES_SUMMARIES_SEARCH_QUERY_DOCUMENT_TYPE,
            product=LLM_TRACES_SUMMARIES_PRODUCT,
            rendering=summary_type.value,
        )
        # Check if the embeddings are ready
        # TODO: Understand a better, more predictable way to check if the embeddings are ready
        embeddings_ready = False
        attempts = 0
        while attempts < LLM_TRACES_SUMMARIES_SEARCH_QUERY_MAX_ATTEMPTS:
            embeddings_ready = self._check_embedding_exists(
                document_id=request_id, document_type=LLM_TRACES_SUMMARIES_SEARCH_QUERY_DOCUMENT_TYPE
            )
            if embeddings_ready:
                break
            attempts += 1
            time.sleep(LLM_TRACES_SUMMARIES_SEARCH_QUERY_POLL_INTERVAL_SECONDS)
        if not embeddings_ready:
            raise ValueError(
                f"Embeddings not ready after {LLM_TRACES_SUMMARIES_SEARCH_QUERY_MAX_ATTEMPTS} attempts when embedding search query for traces summaries"
            )
        return timestamp

    def _check_embedding_exists(self, document_id: str, document_type: str) -> bool:
        """Check if embedding exists in ClickHouse for given document_id"""
        query = """
          SELECT count()
          FROM posthog_document_embeddings
          WHERE team_id = %(team_id)s
            AND product = %(product)s
            AND document_type = %(document_type)s
            AND document_id = %(document_id)s
        """
        result = sync_execute(
            query,
            {
                "team_id": self._team.id,
                "product": LLM_TRACES_SUMMARIES_PRODUCT,
                "document_type": document_type,
                "document_id": document_id,
            },
        )
        return result[0][0] > 0

    def _embed_document(
        self, content: str, document_id: str, document_type: str, rendering: str, product: str
    ) -> datetime:
        timestamp = timezone.now()
        payload = {
            "team_id": self._team.id,
            "product": product,
            "document_type": document_type,
            "rendering": rendering,
            "document_id": document_id,
            "timestamp": timestamp.isoformat(),
            "content": content,
            "models": [self._embedding_model_name.value],
        }
        self._producer.produce(topic=DOCUMENT_EMBEDDINGS_TOPIC, data=payload)
        return timestamp
