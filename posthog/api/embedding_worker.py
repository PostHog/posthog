from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from django.utils.timezone import now

import requests
import structlog
from kafka.producer.kafka import FutureRecordMetadata

from posthog.kafka_client.client import KafkaProducer
from posthog.kafka_client.topics import KAFKA_DOCUMENT_EMBEDDINGS_INPUT_TOPIC
from posthog.models.team.team import Team
from posthog.settings.data_stores import EMBEDDING_API_URL

from products.error_tracking.backend.indexed_embedding import EMBEDDING_TABLES

logger = structlog.get_logger(__name__)


@dataclass
class EmbeddingRequest:
    team_id: int
    content: str
    model: str | None
    no_truncate: bool = False


@dataclass
class EmbeddingResponse:
    embedding: list[float]
    tokens_used: int
    did_truncate: bool


def generate_embedding(
    team: Team, content: str, model: str | None = None, no_truncate: bool = True
) -> EmbeddingResponse:
    logger.info(f"Generating ad-hoc embedding for team {team.pk}")

    # Validate model - it must be provided and must be in our configured tables
    if not model or model not in {table.model_name for table in EMBEDDING_TABLES}:
        valid_models = sorted({table.model_name for table in EMBEDDING_TABLES})
        raise ValueError(f"Invalid model name: {model}. Valid models are: {', '.join(valid_models)}")

    payload = {
        "team_id": team.pk,
        "content": content,
        "no_truncate": no_truncate,
    }
    payload["model"] = model

    response = requests.post(
        EMBEDDING_API_URL + f"/generate/ad_hoc",
        json=payload,
    )
    response.raise_for_status()
    data = response.json()
    return EmbeddingResponse(
        embedding=data["embedding"],
        tokens_used=data["tokens_used"],
        did_truncate=data["did_truncate"],
    )


def emit_embedding_request(
    content: str,
    *,
    team_id: int,
    product: str,
    document_type: str,
    rendering: str,
    document_id: str,
    models: list[str],
    timestamp: Optional[datetime] = None,
    metadata: Optional[dict] = None,
) -> FutureRecordMetadata:
    """
    Emit an embedding request to Kafka for processing by the embedding worker.
    The worker will generate embeddings and emit them to clickhouse_document_embeddings.

    Args:
        content: Text content to embed
        team_id: Team ID
        product: Product name (e.g., "session-replay", "error_tracking")
        document_type: Type of document (e.g., "video-segment", "error")
        rendering: Rendering type (e.g., "video-analysis", "full")
        document_id: Unique document identifier
        models: List of embedding model names to use
        timestamp: Optional timestamp (defaults to now)
        metadata: Optional metadata dict to include as structured JSON, not part of content
    """
    # Validate models against configured embedding tables
    if not models:
        raise ValueError("At least one model must be specified")
    valid_models = {table.model_name for table in EMBEDDING_TABLES}
    invalid_models = set(models) - valid_models
    if invalid_models:
        raise ValueError(
            f"Invalid model name(s): {', '.join(sorted(invalid_models))}. "
            f"Valid models are: {', '.join(sorted(valid_models))}"
        )

    if timestamp is None:
        timestamp = now()

    payload = {
        "team_id": team_id,
        "product": product,
        "document_type": document_type,
        "rendering": rendering,
        "document_id": document_id,
        "timestamp": timestamp.isoformat(),
        "content": content,
        "models": models,
    }
    if metadata:
        payload["metadata"] = metadata

    producer = KafkaProducer()
    return producer.produce(topic=KAFKA_DOCUMENT_EMBEDDINGS_INPUT_TOPIC, data=payload)
