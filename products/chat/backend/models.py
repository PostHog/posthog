from functools import cached_property
from typing import TYPE_CHECKING

from django.db import models
from django.db.models import QuerySet

from posthog.models.utils import UUIDModel
from posthog.models.file_system.file_system_mixin import FileSystemSyncMixin
from posthog.models.file_system.file_system_representation import FileSystemRepresentation
from posthog.models.person.person import Person

if TYPE_CHECKING:
    from posthog.models.team import Team


class ChatConversation(FileSystemSyncMixin, UUIDModel):
    class Meta:
        db_table = "posthog_chat_conversation"
        # No need for the unique constraint since we removed conversation_id
        pass

    person_uuid = models.UUIDField(null=True, blank=True)

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="all_chat_conversations",
        related_query_name="all_chat_conversation",
    )

    title = models.CharField(max_length=400, blank=True, null=True)

    distinct_id = models.CharField(max_length=400)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Which page/url the conversation started on - can be any string now
    source_url = models.CharField(max_length=1000, blank=True, null=True)

    # Unread message count
    unread_count = models.PositiveIntegerField(default=0)
    unread_count_assistant = models.PositiveIntegerField(default=0)

    @cached_property
    def person(self) -> Person | None:
        try:
            return Person.objects.get(uuid=self.person_uuid)
        except Person.DoesNotExist:
            return None

    @classmethod
    def get_file_system_unfiled(cls, team: "Team") -> QuerySet["ChatConversation"]:
        base_qs = cls.objects.filter(team=team)
        return cls._filter_unfiled_queryset(base_qs, team, type="chat_conversation", ref_field="id")

    def get_file_system_representation(self) -> FileSystemRepresentation:
        # Try to get the person by UUID
        try:
            person = Person.objects.get(uuid=self.person_uuid, team_id=self.team_id)
            person_name = person.properties.get("name") or person.properties.get("email") or f"Person {person.uuid}"
        except Person.DoesNotExist:
            person_name = f"Person {self.person_uuid}"

        return FileSystemRepresentation(
            base_folder=self._create_in_folder or "Unfiled/Chats",
            type="chat_conversation",
            ref=str(self.pk),
            name=self.title or f"Chat with {person_name}",
            href=f"/chat/{self.pk}",
            meta={
                "created_at": str(self.created_at),
                "person_uuid": str(self.person_uuid),
            },
            should_delete=False,
        )


class ChatMessage(UUIDModel):
    conversation = models.ForeignKey(
        ChatConversation,
        on_delete=models.CASCADE,
        related_name="messages",
        related_query_name="message",
    )

    content = models.TextField()

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)

    # Message has been read by the other party
    read = models.BooleanField(default=False)

    is_assistant = models.BooleanField(default=False, db_column="is_assistant")

    class Meta:
        ordering = ["created_at"]
        db_table = "posthog_chat_message"
