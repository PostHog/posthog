from django.db import models

from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import UUIDModel


class AssistantThread(UUIDModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)


class AssistantCheckpoint(UUIDModel):
    thread = models.ForeignKey(AssistantThread, on_delete=models.CASCADE, related_name="checkpoints")
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


class AssistantCheckpointBlob(UUIDModel):
    checkpoint = models.ForeignKey(AssistantCheckpoint, on_delete=models.CASCADE, related_name="blobs")
    channel = models.TextField(
        help_text="An arbitrary string defining the channel name. For example, it can be a node name or a reserved LangGraph's enum."
    )
    version = models.TextField(help_text="Monotonically increasing version of the channel.")
    type = models.TextField(null=True, help_text="Type of the serialized blob. For example, `json`.")
    blob = models.BinaryField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["checkpoint_id", "channel", "version"],
                name="unique_checkpoint_blob",
            )
        ]


class AssistantCheckpointWrite(UUIDModel):
    checkpoint = models.ForeignKey(AssistantCheckpoint, on_delete=models.CASCADE, related_name="writes")
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
