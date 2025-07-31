import uuid
from django.db import models

from ..team import Team


class PersonArchive(models.Model):
    """
    Archive table for Person records that exceed the properties size limit.
    When a person's properties become too large to update, the original record
    is archived here before being trimmed to fit within the size constraints.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)

    original_person_id = models.BigIntegerField(
        db_index=True, help_text="ID of the original person record that was archived"
    )

    team = models.ForeignKey(Team, on_delete=models.CASCADE)

    uuid = models.UUIDField(db_index=True, help_text="UUID of the original person record")

    properties = models.JSONField(default=dict, help_text="Properties of the person at the time of archiving")

    properties_size_bytes = models.PositiveIntegerField(
        null=True, blank=True, db_index=True, help_text="Calculated size of the properties field in bytes"
    )

    created_at = models.DateTimeField(help_text="Original creation timestamp of the person record")

    version = models.BigIntegerField(
        null=True, blank=True, help_text="Version of the person record at the time of archiving"
    )

    is_identified = models.BooleanField(
        default=False, help_text="Whether the person was identified at the time of archiving"
    )

    archived_at = models.DateTimeField(auto_now_add=True, help_text="Timestamp when the record was archived")

    archive_reason = models.CharField(
        max_length=100, default="person_properties_size_violation", help_text="Reason for archiving the person record"
    )

    class Meta:
        db_table = "posthog_personarchive"
        indexes = [
            models.Index(fields=["team", "original_person_id"]),
            models.Index(fields=["team", "uuid"]),
            models.Index(fields=["archived_at"]),
            models.Index(fields=["archive_reason"]),
            models.Index(fields=["properties_size_bytes"]),
        ]

    def __str__(self):
        return f"PersonArchive(id={self.id}, original_person_id={self.original_person_id}, team_id={self.team_id})"
