from django.utils import timezone

from posthog.schema import EmbeddingModelName

from posthog.kafka_client.client import KafkaProducer
from posthog.models.team.team import Team

DOCUMENT_EMBEDDINGS_TOPIC = "document_embeddings_input"
SUMMARY_PRODUCT = "llm-analytics"
SUMMARY_DOCUMENT_TYPE = "trace-summary"
SUMMARY_RENDERING = "issues-search"


class LLMTracesSummarizerEmbedder:
    def __init__(
        self, team: Team, embedding_model_name: EmbeddingModelName = EmbeddingModelName.TEXT_EMBEDDING_3_LARGE_3072
    ):
        self._team = team
        self._producer = KafkaProducer()
        self._embedding_model_name = embedding_model_name

    def embed_summaries(self, summarized_traces: dict[str, str]):
        # Add all the summaries to the Kafka producer to be stored in ClickHouse
        for trace_id, summary in summarized_traces.items():
            self._embed_summary(summary=summary, trace_id=trace_id)

    def _embed_summary(self, summary: str, trace_id: str):
        timestamp_clickhouse = timezone.now().isoformat()
        payload = {
            "team_id": self._team.id,
            "product": SUMMARY_PRODUCT,
            "document_type": SUMMARY_DOCUMENT_TYPE,
            "rendering": SUMMARY_RENDERING,
            "document_id": trace_id,
            "timestamp": timestamp_clickhouse,
            "content": summary,
            "models": [self.embedding_model_name.value],
        }
        self._producer.produce(topic=DOCUMENT_EMBEDDINGS_TOPIC, data=payload)
