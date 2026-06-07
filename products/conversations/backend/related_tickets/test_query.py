import json
from datetime import datetime, timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client import sync_execute

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel, Status
from products.conversations.backend.related_tickets.constants import (
    DOCUMENT_TYPE,
    EMBEDDING_MODEL,
    PRODUCT_CONVERSATIONS,
    RENDERING,
)
from products.conversations.backend.related_tickets.query import (
    RelatedTicket,
    _row_to_related_ticket,
    find_related_tickets,
)

_EMBEDDING_DIM = 1536
_TABLE = f"distributed_posthog_document_embeddings_{EMBEDDING_MODEL.replace('-', '_')}"


def _vector(*leading: float) -> list[float]:
    return list(leading) + [0.0] * (_EMBEDDING_DIM - len(leading))


_ANCHOR_VECTOR = _vector(1.0)
_NEAR_VECTOR = _vector(1.0, 0.1)
_MID_VECTOR = _vector(1.0, 1.0)
_FAR_VECTOR = _vector(0.1, 1.0)


class TestFindRelatedTicketsQuery(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.base_timestamp = timezone.now() - timedelta(days=2)
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self.anchor = self._make_ticket("Anchor: cannot log in")

    def _make_ticket(self, subject: str) -> Ticket:
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=f"session-{subject}",
            distinct_id="user-1",
            channel_source=Channel.WIDGET,
            email_subject=subject,
            status=Status.OPEN,
        )
        return ticket

    def _seed_row(
        self,
        *,
        document_id: str,
        embedding: list[float],
        product: str,
        metadata: dict,
        inserted_at: datetime | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        ts = timestamp or self.base_timestamp
        inserted = inserted_at or ts
        sync_execute(
            f"""
            INSERT INTO {_TABLE} (
                team_id, product, document_type, rendering, document_id,
                timestamp, inserted_at, content, metadata, embedding,
                _timestamp, _offset, _partition
            ) VALUES
            """,
            [
                (
                    self.team.pk,
                    product,
                    DOCUMENT_TYPE,
                    RENDERING,
                    document_id,
                    ts,
                    inserted,
                    "content",
                    json.dumps(metadata),
                    embedding,
                    inserted,
                    0,
                    0,
                )
            ],
            flush=False,
            team_id=self.team.pk,
        )

    def _truncate(self) -> None:
        sync_execute(
            f"TRUNCATE TABLE sharded_posthog_document_embeddings_{EMBEDDING_MODEL.replace('-', '_')}",
            flush=False,
            team_id=self.team.pk,
        )

    def _metadata(self, **overrides) -> dict:
        base = {
            "source": PRODUCT_CONVERSATIONS,
            "title": "A ticket",
            "status": "open",
            "ticket_number": 7,
            "ticket_id": "x",
            "last_activity": "2024-01-01T12:00:00+00:00",
        }
        base.update(overrides)
        return base

    def _seed_default_universe(self) -> None:
        self._truncate()
        self._seed_row(
            document_id=str(self.anchor.id),
            embedding=_ANCHOR_VECTOR,
            product=PRODUCT_CONVERSATIONS,
            metadata=self._metadata(title="Anchor", ticket_id=str(self.anchor.id)),
        )
        self._seed_row(
            document_id="near-id",
            embedding=_NEAR_VECTOR,
            product=PRODUCT_CONVERSATIONS,
            metadata=self._metadata(title="Near", ticket_number=11, ticket_id="near-id"),
        )
        self._seed_row(
            document_id="zendesk-id",
            embedding=_MID_VECTOR,
            product="zendesk",
            metadata=self._metadata(
                source="zendesk", title="Zendesk mid", ticket_number=None, url="https://z.example/2"
            ),
        )
        self._seed_row(
            document_id="far-id",
            embedding=_FAR_VECTOR,
            product=PRODUCT_CONVERSATIONS,
            metadata=self._metadata(title="Far", ticket_number=99, ticket_id="far-id"),
        )

    def _patched_embedding(self, vector: list[float]):
        response = MagicMock()
        response.embedding = vector
        return patch(
            "products.conversations.backend.related_tickets.query.generate_embedding",
            return_value=response,
        )

    def test_orders_by_distance_excludes_anchor_and_far_includes_cross_product(self):
        self._seed_default_universe()
        with self._patched_embedding(_ANCHOR_VECTOR):
            results = find_related_tickets(self.team, self.anchor)

        ids = [r.id for r in results]
        assert ids == ["near-id", "zendesk-id"]
        assert str(self.anchor.id) not in ids
        assert "far-id" not in ids
        sources = {r.source for r in results}
        assert "zendesk" in sources

    def test_max_distance_can_be_widened(self):
        self._seed_default_universe()
        with self._patched_embedding(_ANCHOR_VECTOR):
            results = find_related_tickets(self.team, self.anchor, max_distance=1.0)

        ids = [r.id for r in results]
        assert ids == ["near-id", "zendesk-id", "far-id"]

    def test_limit_is_respected(self):
        self._seed_default_universe()
        with self._patched_embedding(_ANCHOR_VECTOR):
            results = find_related_tickets(self.team, self.anchor, limit=1)

        assert [r.id for r in results] == ["near-id"]

    def test_dedup_keeps_latest_inserted_row(self):
        self._truncate()
        self._seed_row(
            document_id=str(self.anchor.id),
            embedding=_ANCHOR_VECTOR,
            product=PRODUCT_CONVERSATIONS,
            metadata=self._metadata(ticket_id=str(self.anchor.id)),
        )
        self._seed_row(
            document_id="dup-id",
            embedding=_FAR_VECTOR,
            product=PRODUCT_CONVERSATIONS,
            metadata=self._metadata(title="Stale", ticket_id="dup-id"),
            timestamp=self.base_timestamp - timedelta(days=40),
            inserted_at=self.base_timestamp - timedelta(days=40),
        )
        self._seed_row(
            document_id="dup-id",
            embedding=_NEAR_VECTOR,
            product=PRODUCT_CONVERSATIONS,
            metadata=self._metadata(title="Fresh", ticket_id="dup-id"),
            timestamp=self.base_timestamp,
            inserted_at=self.base_timestamp + timedelta(days=1),
        )

        with self._patched_embedding(_ANCHOR_VECTOR):
            results = find_related_tickets(self.team, self.anchor)

        assert [r.id for r in results] == ["dup-id"]
        assert results[0].title == "Fresh"

    @parameterized.expand(
        [
            ("consent_off", False, True),
            ("flag_off", True, False),
            ("both_off", False, False),
        ]
    )
    def test_endpoint_gating_returns_empty(self, _name: str, consent: bool, flag: bool):
        self.organization.is_ai_data_processing_approved = consent
        self.organization.save()
        self._seed_default_universe()

        with (
            patch("posthog.permissions.posthoganalytics.feature_enabled", return_value=True),
            patch("products.conversations.backend.api.tickets.posthoganalytics.feature_enabled", return_value=flag),
            self._patched_embedding(_ANCHOR_VECTOR),
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/{self.anchor.id}/related/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_endpoint_returns_related_tickets_when_enabled(self):
        self._seed_default_universe()

        with (
            patch("posthog.permissions.posthoganalytics.feature_enabled", return_value=True),
            patch("products.conversations.backend.api.tickets.posthoganalytics.feature_enabled", return_value=True),
            self._patched_embedding(_ANCHOR_VECTOR),
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/{self.anchor.id}/related/")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert [r["id"] for r in body] == ["near-id", "zendesk-id"]
        near = next(r for r in body if r["id"] == "near-id")
        zendesk = next(r for r in body if r["id"] == "zendesk-id")
        assert near["url"] is None
        assert near["source"] == PRODUCT_CONVERSATIONS
        assert zendesk["url"] == "https://z.example/2"
        assert zendesk["source"] == "zendesk"
        assert zendesk["ticket_number"] is None


class TestRowToRelatedTicketMapping(APIBaseTest):
    def test_conversations_row_has_no_url(self):
        row = (
            "doc-1",
            "conversations",
            json.dumps(
                {
                    "source": "conversations",
                    "title": "Login broken",
                    "status": "open",
                    "ticket_number": 12,
                    "last_activity": "2024-01-02T00:00:00+00:00",
                    "url": "https://should-be-ignored.example",
                }
            ),
            0.1,
        )
        result = _row_to_related_ticket(row)
        assert result == RelatedTicket(
            source="conversations",
            id="doc-1",
            title="Login broken",
            status="open",
            url=None,
            ticket_number=12,
            last_activity="2024-01-02T00:00:00+00:00",
        )

    def test_external_row_uses_metadata_url(self):
        row = (
            "doc-2",
            "zendesk",
            json.dumps({"source": "zendesk", "title": "Refund", "status": "solved", "url": "https://z/3"}),
            0.2,
        )
        result = _row_to_related_ticket(row)
        assert result is not None
        assert result.source == "zendesk"
        assert result.url == "https://z/3"
        assert result.ticket_number is None
        assert result.last_activity is None

    def test_source_falls_back_to_product_column(self):
        row = ("doc-3", "intercom", json.dumps({"title": "T", "status": "open"}), 0.3)
        result = _row_to_related_ticket(row)
        assert result is not None
        assert result.source == "intercom"
        assert result.url is None

    def test_malformed_metadata_is_tolerated(self):
        row = ("doc-4", "zendesk", "not-json", 0.4)
        result = _row_to_related_ticket(row)
        assert result is not None
        assert result.source == "zendesk"
        assert result.title == ""
        assert result.status == ""
