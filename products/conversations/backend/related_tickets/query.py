import json
from dataclasses import dataclass
from typing import Any

import structlog

from posthog.schema import HogQLQueryResponse

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.api.embedding_worker import generate_embedding
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team

from products.conversations.backend.models import Ticket
from products.conversations.backend.related_tickets.constants import (
    DOCUMENT_TYPE,
    EMBEDDING_MODEL,
    LOOKBACK_DAYS_DEFAULT,
    MAX_DISTANCE_DEFAULT,
    PRODUCT_CONVERSATIONS,
    RENDERING,
    RESULT_LIMIT,
)
from products.conversations.backend.related_tickets.content import compose_ticket_text

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class RelatedTicket:
    """A ticket found to be semantically similar to an anchor ticket."""

    source: str
    id: str
    title: str
    status: str
    url: str | None
    ticket_number: int | None
    last_activity: str | None


_RELATED_TICKETS_QUERY = """
    SELECT
        document_id,
        product,
        metadata,
        cosineDistance({anchor_embedding}, embedding) AS distance
    FROM (
        SELECT
            document_id,
            argMax(product, inserted_at) AS product,
            argMax(metadata, inserted_at) AS metadata,
            argMax(embedding, inserted_at) AS embedding
        FROM document_embeddings
        WHERE team_id = {team_id}
          AND document_type = {document_type}
          AND model_name = {model_name}
          AND rendering = {rendering}
          AND document_id != {anchor_id}
          AND timestamp >= now() - toIntervalDay({lookback_days})
        GROUP BY document_id
    )
    WHERE distance <= {max_distance}
    ORDER BY distance ASC
    LIMIT {limit}
"""


def _row_to_related_ticket(row: tuple[Any, ...]) -> RelatedTicket | None:
    document_id, product, metadata_str, _distance = row
    try:
        metadata: dict[str, Any] = json.loads(metadata_str) if metadata_str else {}
    except (json.JSONDecodeError, TypeError):
        metadata = {}

    source = metadata.get("source") or product
    url = None if source == PRODUCT_CONVERSATIONS else metadata.get("url")

    return RelatedTicket(
        source=source,
        id=str(document_id),
        title=metadata.get("title") or "",
        status=metadata.get("status") or "",
        url=url,
        ticket_number=metadata.get("ticket_number"),
        last_activity=metadata.get("last_activity"),
    )


def find_related_tickets(
    team: Team,
    ticket: Ticket,
    *,
    limit: int = RESULT_LIMIT,
    max_distance: float = MAX_DISTANCE_DEFAULT,
    lookback_days: int = LOOKBACK_DAYS_DEFAULT,
) -> list[RelatedTicket]:
    """Find tickets semantically similar to ``ticket`` via a kNN search over document_embeddings."""
    if not team.organization.is_ai_data_processing_approved:
        return []

    composed = compose_ticket_text(team.id, str(ticket.id))
    if composed is None:
        return []
    content, _metadata, _last_activity = composed

    try:
        anchor_embedding = generate_embedding(team, content, EMBEDDING_MODEL).embedding
        if not anchor_embedding:
            return []

        tag_queries(product=Product.CONVERSATIONS, feature=Feature.QUERY)
        result: HogQLQueryResponse = execute_hogql_query(
            parse_select(
                _RELATED_TICKETS_QUERY,
                placeholders={
                    "anchor_embedding": ast.Constant(value=anchor_embedding),
                    "team_id": ast.Constant(value=team.id),
                    "document_type": ast.Constant(value=DOCUMENT_TYPE),
                    "model_name": ast.Constant(value=EMBEDDING_MODEL),
                    "rendering": ast.Constant(value=RENDERING),
                    "anchor_id": ast.Constant(value=str(ticket.id)),
                    "max_distance": ast.Constant(value=max_distance),
                    "limit": ast.Constant(value=limit),
                    "lookback_days": ast.Constant(value=lookback_days),
                },
            ),
            team=team,
            query_type="ConversationsRelatedTickets",
        )
    except Exception as e:
        capture_exception(e, {"team_id": team.id, "ticket_id": str(ticket.id)})
        return []

    related: list[RelatedTicket] = []
    for row in result.results or []:
        mapped = _row_to_related_ticket(row)
        if mapped is not None:
            related.append(mapped)
    return related
