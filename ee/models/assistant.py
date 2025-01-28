from collections.abc import Iterable
from datetime import timedelta

from django.db import models
from django.utils import timezone
from langgraph.checkpoint.serde.types import TASKS

from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import UUIDModel


class Conversation(UUIDModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)


class ConversationCheckpoint(UUIDModel):
    thread = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="checkpoints")
    checkpoint_ns = models.TextField(
        default="",
        help_text='Checkpoint namespace. Denotes the path to the subgraph node the checkpoint originates from, separated by `|` character, e.g. `"child|grandchild"`. Defaults to "" (root graph).',
    )
    parent_checkpoint = models.ForeignKey(
        "self", null=True, on_delete=models.CASCADE, related_name="children", help_text="Parent checkpoint ID."
    )
    checkpoint = models.JSONField(null=True, help_text="Serialized checkpoint data.")
    metadata = models.JSONField(null=True, help_text="Serialized checkpoint metadata.")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["id", "checkpoint_ns", "thread"],
                name="unique_checkpoint",
            )
        ]

    @property
    def pending_sends(self) -> Iterable["ConversationCheckpointWrite"]:
        if self.parent_checkpoint is None:
            return []
        return self.parent_checkpoint.writes.filter(channel=TASKS).order_by("task_id", "idx")

    @property
    def pending_writes(self) -> Iterable["ConversationCheckpointWrite"]:
        return self.writes.order_by("idx", "task_id")


class ConversationCheckpointBlob(UUIDModel):
    checkpoint = models.ForeignKey(ConversationCheckpoint, on_delete=models.CASCADE, related_name="blobs")
    """
    The checkpoint that created the blob. Do not use this field to query blobs.
    """
    thread = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="blobs", null=True)
    checkpoint_ns = models.TextField(
        default="",
        help_text='Checkpoint namespace. Denotes the path to the subgraph node the checkpoint originates from, separated by `|` character, e.g. `"child|grandchild"`. Defaults to "" (root graph).',
    )
    channel = models.TextField(
        help_text="An arbitrary string defining the channel name. For example, it can be a node name or a reserved LangGraph's enum."
    )
    version = models.TextField(help_text="Monotonically increasing version of the channel.")
    type = models.TextField(null=True, help_text="Type of the serialized blob. For example, `json`.")
    blob = models.BinaryField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["thread_id", "checkpoint_ns", "channel", "version"],
                name="unique_checkpoint_blob",
            )
        ]


class ConversationCheckpointWrite(UUIDModel):
    checkpoint = models.ForeignKey(ConversationCheckpoint, on_delete=models.CASCADE, related_name="writes")
    task_id = models.UUIDField(help_text="Identifier for the task creating the checkpoint write.")
    idx = models.IntegerField(
        help_text="Index of the checkpoint write. It is an integer value where negative numbers are reserved for special cases, such as node interruption."
    )
    channel = models.TextField(
        help_text="An arbitrary string defining the channel name. For example, it can be a node name or a reserved LangGraph's enum."
    )
    type = models.TextField(null=True, help_text="Type of the serialized blob. For example, `json`.")
    blob = models.BinaryField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["checkpoint_id", "task_id", "idx"],
                name="unique_checkpoint_write",
            )
        ]


class CoreMemory(UUIDModel):
    class ScrapingStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        SKIPPED = "skipped", "Skipped"

    team = models.OneToOneField(Team, on_delete=models.CASCADE)
    text = models.TextField(default="", help_text="Dumped core memory where facts are separated by newlines.")
    initial_text = models.TextField(default="", help_text="Scraped memory about the business.")
    scraping_status = models.CharField(max_length=20, choices=ScrapingStatus.choices, blank=True, null=True)
    scraping_started_at = models.DateTimeField(null=True)

    def change_status_to_pending(self):
        self.scraping_started_at = timezone.now()
        self.scraping_status = CoreMemory.ScrapingStatus.PENDING
        self.save()

    def change_status_to_skipped(self):
        self.scraping_status = CoreMemory.ScrapingStatus.SKIPPED
        self.save()

    @property
    def is_scraping_pending(self) -> bool:
        return self.scraping_status == CoreMemory.ScrapingStatus.PENDING and (
            self.scraping_started_at is None or (self.scraping_started_at + timedelta(minutes=5)) > timezone.now()
        )

    @property
    def is_scraping_finished(self) -> bool:
        return self.scraping_status in [CoreMemory.ScrapingStatus.COMPLETED, CoreMemory.ScrapingStatus.SKIPPED]

    def set_core_memory(self, text: str):
        self.text = text
        self.initial_text = text
        self.scraping_status = CoreMemory.ScrapingStatus.COMPLETED
        self.save()

    def append_core_memory(self, text: str):
        self.text = self.text + "\n" + text
        self.save()

    def replace_core_memory(self, original_fragment: str, new_fragment: str):
        if original_fragment not in self.text:
            raise ValueError(f"Original fragment {original_fragment} not found in core memory")
        self.text = self.text.replace(original_fragment, new_fragment)
        self.save()

    @property
    def formatted_text(self) -> str:
        return self.text[0:5000]
