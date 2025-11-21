from dataclasses import dataclass

import requests
import structlog

from posthog.kafka_client.client import KafkaProducer
from posthog.kafka_client.topics import KAFKA_DOCUMENT_EMBEDDINGS_INPUT_TOPIC
from posthog.models.team.team import Team
from posthog.settings.data_stores import EMBEDDING_API_URL

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
    payload = {
        "team_id": team.pk,
        "content": content,
        "no_truncate": no_truncate,
    }
    if model:
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


@dataclass
class EmbeddingKafkaRequest:
    team_id: int
    product: str
    document_type: str
    rendering: str
    document_id: str
    timestamp: str
    contents: str
    models: list[str]
    metadata: dict | None = None


# Sends a new embedding request message to the embedding worker.
def insert_embeddings(requests: list[EmbeddingKafkaRequest]):
    for req in requests:
        payload = {
            "team_id": req.team_id,
            "product": req.product,
            "document_type": req.document_type,
            "rendering": req.rendering,
            "document_id": req.document_id,
            "timestamp": req.timestamp,
            "content": req.contents,
            "models": req.models,
        }
        if req.metadata:
            payload["metadata"] = req.metadata
        KafkaProducer().produce(topic=KAFKA_DOCUMENT_EMBEDDINGS_INPUT_TOPIC, data=payload)

    KafkaProducer().flush()
