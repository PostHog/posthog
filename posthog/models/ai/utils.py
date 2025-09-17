import json
from typing import Any

from pydantic import BaseModel, Field

from posthog.clickhouse.client.execute import sync_execute
from posthog.hogql_queries.ai.vector_search_query_runner import LATEST_ACTIONS_EMBEDDING_VERSION
from posthog.models.ai.pg_embeddings import INSERT_BULK_PG_EMBEDDINGS_SQL


class PgEmbeddingRow(BaseModel):
    domain: str
    team_id: int
    id: str
    vector: list[float]
    text: str
    properties: dict[str, Any] | None = Field(default=None)
    is_deleted: bool | None = Field(default=False)


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
                %(is_deleted_{idx})s
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
            }
        )

    sync_execute(INSERT_BULK_PG_EMBEDDINGS_SQL + ", ".join(inserts), params, flush=False)
