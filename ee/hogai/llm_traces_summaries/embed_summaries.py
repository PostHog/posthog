from django.utils import timezone

from posthog.schema import EmbeddingModelName

from posthog.kafka_client.client import KafkaProducer
from posthog.models.team.team import Team

DOCUMENT_EMBEDDINGS_TOPIC = "document_embeddings_input"


class LLMTracesSummarizerEmbedder:
    def __init__(
        self, team: Team, trace_summary_model: EmbeddingModelName = EmbeddingModelName.TEXT_EMBEDDING_3_LARGE_3072
    ):
        self._team = team
        self._producer = KafkaProducer()
        self._trace_summary_model = trace_summary_model

    def embed_summaries(self, summarized_traces: dict[str, str]):
        # Add all the summaries to the Kafka producer to be stored in ClickHouse
        for trace_id, summary in summarized_traces.items():
            self._embed_summary(summary=summary, trace_id=trace_id)

    def _embed_summary(self, summary: str, trace_id: str):
        timestamp_clickhouse = timezone.now().isoformat()
        payload = {
            "team_id": self._team.id,
            "product": "llm-analytics",
            "document_type": "trace-summary",
            "rendering": "issues-search",
            "document_id": trace_id,
            "timestamp": timestamp_clickhouse,
            "content": summary,
            "models": [self._trace_summary_model.value],
        }
        self._producer.produce(topic=DOCUMENT_EMBEDDINGS_TOPIC, data=payload)
