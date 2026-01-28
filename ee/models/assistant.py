import string
import secrets
from datetime import timedelta

from django.db import IntegrityError, models
from django.utils import timezone

from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import CreatedMetaFields, DeletedMetaFields, UpdatedMetaFields, UUIDModel, UUIDTModel


def generate_short_id():
    """Generate securely random 4 characters long alphanumeric ID.

    With team-scoped uniqueness, 4 characters (62^4 = 14.7M combinations)
    is sufficient to avoid collisions within a single team.
    """
    return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(4))


class Conversation(UUIDTModel):
    TITLE_MAX_LENGTH = 250

    class Meta:
        indexes = [
            models.Index(fields=["updated_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["team", "slack_thread_key"],
                name="unique_team_slack_thread_key",
                condition=models.Q(slack_thread_key__isnull=False),
            )
        ]

    class Status(models.TextChoices):
        IDLE = "idle", "Idle"
        IN_PROGRESS = "in_progress", "In progress"
        CANCELING = "canceling", "Canceling"

    class Type(models.TextChoices):
        ASSISTANT = "assistant", "Assistant"
        TOOL_CALL = "tool_call", "Tool call"
        DEEP_RESEARCH = "deep_research", "Deep research"
        SLACK = "slack", "Slack"

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IDLE)
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.ASSISTANT)
    title = models.CharField(
        null=True,
        blank=True,
        help_text="Title of the conversation.",
        max_length=TITLE_MAX_LENGTH,
    )
    is_internal = models.BooleanField(
        null=True,
        default=False,
        help_text="Whether this conversation was created during an impersonated session (e.g., by support agents). Internal conversations are hidden from customers.",
    )
    slack_thread_key = models.CharField(
        max_length=200,
        null=True,
        blank=True,
        help_text="Unique key for Slack thread: '{workspace_id}:{channel}:{thread_ts}'",
    )
    slack_workspace_domain = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Slack workspace subdomain (e.g. 'posthog' for posthog.slack.com)",
    )
    approval_decisions = models.JSONField(
        default=dict,
        blank=True,
        help_text="Stores approval card metadata for dangerous operations (payload lives in checkpoint). Format: {proposal_id: {decision_status: 'pending' | 'approved' | 'rejected' | 'auto_rejected', tool_name: str, preview: str, ...}}",
    )


class ConversationCheckpoint(UUIDTModel):
    thread = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="checkpoints")
    checkpoint_ns = models.TextField(
        default="",
        help_text='Checkpoint namespace. Denotes the path to the subgraph node the checkpoint originates from, separated by `|` character, e.g. `"child|grandchild"`. Defaults to "" (root graph).',
    )
    parent_checkpoint = models.ForeignKey(
        "self",
        null=True,
        on_delete=models.CASCADE,
        related_name="children",
        help_text="Parent checkpoint ID.",
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


class ConversationCheckpointBlob(UUIDTModel):
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


class ConversationCheckpointWrite(UUIDTModel):
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


MAX_ONBOARDING_QUESTIONS = 3
ONBOARDING_TIMEOUT_MINUTES = 10


class CoreMemory(UUIDTModel):
    class ScrapingStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        SKIPPED = "skipped", "Skipped"

    team = models.OneToOneField(Team, on_delete=models.CASCADE)
    text = models.TextField(
        default="",
        help_text="Dumped core memory where facts are separated by newlines.",
    )
    initial_text = models.TextField(default="", help_text="Scraped memory about the business.")
    scraping_status = models.CharField(max_length=20, choices=ScrapingStatus.choices, blank=True, null=True)
    scraping_started_at = models.DateTimeField(null=True)

    async def achange_status_to_pending(self):
        self.scraping_started_at = timezone.now()
        self.scraping_status = CoreMemory.ScrapingStatus.PENDING
        await self.asave()

    async def achange_status_to_skipped(self):
        self.scraping_status = CoreMemory.ScrapingStatus.SKIPPED
        await self.asave()

    @property
    def is_scraping_pending(self) -> bool:
        return self.scraping_status == CoreMemory.ScrapingStatus.PENDING and (
            self.scraping_started_at is None
            or (self.scraping_started_at + timedelta(minutes=ONBOARDING_TIMEOUT_MINUTES)) > timezone.now()
        )

    @property
    def is_scraping_finished(self) -> bool:
        return self.scraping_status in [
            CoreMemory.ScrapingStatus.COMPLETED,
            CoreMemory.ScrapingStatus.SKIPPED,
        ]

    async def aappend_question_to_initial_text(self, text: str):
        if self.initial_text != "":
            self.initial_text += "\n"
        self.initial_text += "Question: " + text + "\nAnswer:"
        self.initial_text = self.initial_text.strip()
        await self.asave()

    async def aappend_answer_to_initial_text(self, text: str):
        self.initial_text += " " + text
        self.initial_text = self.initial_text.strip()
        await self.asave()

    async def aset_core_memory(self, text: str):
        self.text = text
        self.scraping_status = CoreMemory.ScrapingStatus.COMPLETED
        await self.asave()

    async def aappend_core_memory(self, text: str):
        if self.text == "":
            self.text = text
        else:
            self.text = self.text + "\n" + text
        await self.asave()

    async def areplace_core_memory(self, original_fragment: str, new_fragment: str):
        if original_fragment not in self.text:
            raise ValueError(f"Original fragment {original_fragment} not found in core memory")
        self.text = self.text.replace(original_fragment, new_fragment)
        await self.asave()

    @property
    def formatted_text(self) -> str:
        if len(self.text) > 5000:
            # If memory text exceeds 5000 characters, truncate it. For the user, the most important bits are at the start
            # (i.e. foundational /init info) and at the end (i.e. freshest memories)
            return self.text[:2500] + "…" + self.text[-2500:]
        return self.text

    @property
    def answers_left(self) -> int:
        answers_given = self.initial_text.count("\nAnswer:")
        if self.initial_text.endswith("\nAnswer:"):
            answers_given -= 1
        return MAX_ONBOARDING_QUESTIONS - answers_given


class AgentArtifact(UUIDModel, CreatedMetaFields, UpdatedMetaFields, DeletedMetaFields):
    class Type(models.TextChoices):
        VISUALIZATION = "visualization", "Visualization"
        NOTEBOOK = "notebook", "Notebook"

    short_id = models.CharField(max_length=4, default=generate_short_id)
    name = models.CharField(max_length=400)
    type = models.CharField(max_length=50, choices=Type.choices)
    data = models.JSONField(help_text="Artifact content. Structure depends on artifact type.")
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="artifacts")
    team = models.ForeignKey(Team, on_delete=models.CASCADE)

    class Meta:
        indexes = [
            models.Index(fields=["team", "short_id"]),
            models.Index(fields=["team", "conversation", "created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["team", "short_id"], name="unique_team_short_id"),
        ]

    def save(self, *args, **kwargs):
        max_retries = 5
        for attempt in range(max_retries):
            try:
                return super().save(*args, **kwargs)
            except IntegrityError as e:
                if "short_id" in str(e) and attempt < max_retries - 1:
                    self.short_id = generate_short_id()
                else:
                    raise
