import json
from typing import Any

from pydantic import BaseModel, Field

from posthog.clickhouse.client.execute import sync_execute
from posthog.models.ai.pg_embeddings import INSERT_BULK_PG_EMBEDDINGS_SQL


class PgEmbeddingRow(BaseModel):
    domain: str
    team_id: int
    id: str
    vector: list[float]
    text: str
    properties: dict[str, Any] | None = Field(default=None)
    is_deleted: bool | None = Field(default=False)


def bulk_create_pg_embeddings(vectors: list[PgEmbeddingRow]):
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
                %(is_deleted_{idx})s
            )
            """.format(idx=idx)
        )
        params.update(
            {
                f"domain_{idx}": vector_row.domain,
                f"team_id_{idx}": vector_row.team_id,
                f"id_{idx}": vector_row.id,
                f"vector_{idx}": vector_row.vector,
                f"text_{idx}": vector_row.text,
                f"properties_{idx}": json.dumps(vector_row.properties) if vector_row.properties else None,
                f"is_deleted_{idx}": vector_row.is_deleted,
            }
        )

    sync_execute(INSERT_BULK_PG_EMBEDDINGS_SQL + ", ".join(inserts), params, flush=False)
