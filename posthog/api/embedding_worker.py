from dataclasses import dataclass

import requests
import structlog

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
