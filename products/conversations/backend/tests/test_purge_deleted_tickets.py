from datetime import timedelta
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from posthog.models import ActivityLog, Comment
from posthog.models.data_deletion_request import DataDeletionRequest
from posthog.models.uploaded_media import UploadedMedia
from posthog.storage.object_storage import ObjectStorageError

from products.business_knowledge.backend.models import KnowledgeGapSuggestion, KnowledgeLearningRun
from products.conversations.backend.models import ConversationDelivery, ConversationInboundEvent
from products.conversations.backend.models.constants import Channel
from products.conversations.backend.models.delivery import ConversationDeliveryChannel
from products.conversations.backend.models.inbound_event import ConversationInboundEventSource
from products.conversations.backend.models.ticket import TICKET_HARD_DELETE_AFTER, Ticket
from products.conversations.backend.tasks.maintenance import purge_deleted_tickets


class TestPurgeDeletedTickets(BaseTest):
    @patch("products.conversations.backend.tasks.maintenance.object_storage.delete")
    @patch("products.signals.backend.facade.api.retract_source_signals", return_value=1)
    def test_purge_removes_ticket_data_past_the_window(self, retract: MagicMock, delete_object: MagicMock) -> None:
        fresh = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="fresh-session",
            distinct_id="person-2",
        )
        fresh.deleted_at = timezone.now()
        fresh.save(update_fields=["deleted_at"])
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="purge-session",
            distinct_id="person-1",
        )
        media = UploadedMedia.objects.create(
            team=self.team,
            file_name="shot.png",
            content_type="image/png",
            media_location="uploads/shot.png",
        )
        user_upload = UploadedMedia.objects.create(
            team=self.team,
            created_by=self.user,
            file_name="insight.png",
            media_location="uploads/insight.png",
        )
        shared = UploadedMedia.objects.create(
            team=self.team,
            file_name="shared.png",
            media_location="uploads/shared.png",
        )
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content=f"see /uploaded_media/{media.id} /uploaded_media/{user_upload.id} /uploaded_media/{shared.id}",
        )
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(fresh.id),
            content=f"also /uploaded_media/{shared.id}",
        )
        Comment.objects.create(
            team=self.team,
            scope="Ticket",
            item_id=str(ticket.id),
            content="internal",
        )
        ConversationDelivery.objects.for_team(self.team.id).create(
            team=self.team,
            channel=ConversationDeliveryChannel.SLACK,
            comment_id=uuid4(),
            ticket_id=ticket.id,
            provider_account_id="T123",
            payload={"text": "secret reply"},
        )
        ConversationInboundEvent.objects.for_team(self.team.id).create(
            team=self.team,
            source=ConversationInboundEventSource.SLACK_EVENTS,
            source_id="evt-1",
            provider_account_id="T123",
            ticket_id=ticket.id,
            payload={"text": "secret inbound"},
        )
        KnowledgeGapSuggestion.objects.for_team(self.team.id).create(
            team=self.team,
            ticket_id=ticket.id,
            topic="How do I export?",
            normalized_topic="how do i export",
        )
        KnowledgeLearningRun.objects.for_team(self.team.id).create(
            team=self.team,
            evidence_key=f"{ticket.id}:{uuid4()}",
            source_team_id=self.team.id,
            analysis_version="v1",
        )
        deleted_at = timezone.now() - TICKET_HARD_DELETE_AFTER - timedelta(days=1)
        Ticket.all_objects.filter(id=ticket.id).update(
            created_at=deleted_at - timedelta(days=1),
            deleted_at=deleted_at,
        )

        purge_deleted_tickets()

        retract.assert_called_once_with(
            team=self.team,
            source_product="conversations",
            source_type="ticket",
            source_id=str(ticket.id),
        )
        delete_object.assert_called_once_with("uploads/shot.png")
        self.assertFalse(Ticket.all_objects.filter(id=ticket.id).exists())
        self.assertTrue(Ticket.all_objects.filter(id=fresh.id).exists())
        self.assertFalse(Comment.objects.filter(item_id=str(ticket.id)).exists())
        self.assertFalse(UploadedMedia.objects.filter(id=media.id).exists())
        self.assertEqual(UploadedMedia.objects.filter(id__in=[user_upload.id, shared.id]).count(), 2)
        self.assertFalse(ConversationDelivery.objects.for_team(self.team.id).filter(ticket_id=ticket.id).exists())
        self.assertFalse(ConversationInboundEvent.objects.for_team(self.team.id).filter(ticket_id=ticket.id).exists())
        self.assertFalse(KnowledgeGapSuggestion.objects.for_team(self.team.id).filter(ticket_id=ticket.id).exists())
        self.assertFalse(
            KnowledgeLearningRun.objects.for_team(self.team.id)
            .filter(evidence_key__startswith=f"{ticket.id}:")
            .exists()
        )
        self.assertTrue(
            ActivityLog.objects.filter(
                team_id=self.team.id, scope="Ticket", item_id=str(ticket.id), activity="purged"
            ).exists()
        )
        request = DataDeletionRequest.objects.get(team_id=self.team.id, submission_id=ticket.id)
        self.assertEqual(request.requires_approval, False)
        self.assertIn(str(ticket.id), request.hogql_predicate)
        after = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="after-session",
            distinct_id="person-3",
        )
        self.assertEqual(after.ticket_number, ticket.ticket_number + 1)

    @patch(
        "products.conversations.backend.tasks.maintenance.object_storage.delete",
        side_effect=ObjectStorageError("delete failed"),
    )
    @patch("products.signals.backend.facade.api.retract_source_signals", return_value=0)
    def test_purge_keeps_ticket_when_media_delete_fails(self, _retract: MagicMock, _delete_object: MagicMock) -> None:
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="purge-session",
            distinct_id="person-1",
        )
        media = UploadedMedia.objects.create(
            team=self.team,
            file_name="shot.png",
            media_location="uploads/shot.png",
        )
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content=f"see /uploaded_media/{media.id}",
        )
        Ticket.all_objects.filter(id=ticket.id).update(
            deleted_at=timezone.now() - TICKET_HARD_DELETE_AFTER - timedelta(days=1)
        )

        purge_deleted_tickets()

        self.assertTrue(Ticket.all_objects.filter(id=ticket.id).exists())
        self.assertTrue(UploadedMedia.objects.filter(id=media.id).exists())
        self.assertTrue(Comment.objects.filter(item_id=str(ticket.id)).exists())

    @patch("products.signals.backend.facade.api.retract_source_signals", return_value=0)
    def test_purge_leaves_tickets_inside_the_window(self, retract: MagicMock) -> None:
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="recent-session",
            distinct_id="person-1",
        )
        ticket.deleted_at = timezone.now() - timedelta(days=1)
        ticket.save(update_fields=["deleted_at"])

        purge_deleted_tickets()

        retract.assert_not_called()
        self.assertTrue(Ticket.all_objects.filter(id=ticket.id).exists())
