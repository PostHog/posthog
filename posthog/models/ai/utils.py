import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from posthog.clickhouse.client.execute import sync_execute
from posthog.hogql_queries.ai.vector_search_query_runner import LATEST_ACTIONS_EMBEDDING_VERSION
from posthog.models.ai.pg_embeddings import PG_EMBEDDINGS_DATA_TABLE


class PgEmbeddingRow(BaseModel):
    domain: str
    team_id: int
    id: str
    vector: list[float]
    text: str
    properties: dict[str, Any] | None = Field(default=None)
    is_deleted: bool | None = Field(default=False)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


def bulk_create_pg_embeddings(
    vectors: list[PgEmbeddingRow], embedding_version: int | None = LATEST_ACTIONS_EMBEDDING_VERSION
):
    inserts: list[str] = []
    params = {}

    for idx, vector_row in enumerate(vectors):
        inserts.append(
            """
            (
                %(domain_{idx})s,
                %(team_id_{idx})s,
                %(id_{idx})s,
                %(vector_{idx})s,
                %(text_{idx})s,
                %(properties_{idx})s,
                %(is_deleted_{idx})s,
                %(timestamp_{idx})s
            )
            """.format(idx=idx)
        )

        props = vector_row.properties
        if props is None:
            props = {}
        else:
            props = props.copy()
        if embedding_version is not None:
            props["embedding_version"] = embedding_version

        params.update(
            {
                f"domain_{idx}": vector_row.domain,
                f"team_id_{idx}": vector_row.team_id,
                f"id_{idx}": vector_row.id,
                f"vector_{idx}": vector_row.vector,
                f"text_{idx}": vector_row.text,
                f"properties_{idx}": json.dumps(props),
                f"is_deleted_{idx}": vector_row.is_deleted,
                f"timestamp_{idx}": vector_row.timestamp,
            }
        )

    sync_execute(
        f"INSERT INTO {PG_EMBEDDINGS_DATA_TABLE()} "
        "(domain, team_id, id, vector, text, properties, is_deleted, timestamp) VALUES " + ", ".join(inserts),
        params,
        flush=False,
    )
