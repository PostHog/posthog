from dataclasses import dataclass

import requests
import structlog

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
