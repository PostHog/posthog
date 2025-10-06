from typing import TYPE_CHECKING

from django.db import models
from django.db.models import JSONField, QuerySet
from django.utils import timezone

from posthog.models.file_system.file_system_mixin import FileSystemSyncMixin
from posthog.models.file_system.file_system_representation import FileSystemRepresentation
from posthog.models.utils import RootTeamMixin, UUIDTModel
from posthog.utils import generate_short_id

if TYPE_CHECKING:
    from posthog.models.team import Team


class Notebook(FileSystemSyncMixin, RootTeamMixin, UUIDTModel):
    class Visibility(models.TextChoices):
        INTERNAL = "internal", "internal"
        DEFAULT = "default", "default"

    short_id = models.CharField(max_length=12, blank=True, default=generate_short_id)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    title = models.CharField(max_length=256, blank=True, null=True)
    content: JSONField = JSONField(default=None, null=True, blank=True)
    text_content = models.TextField(blank=True, null=True)
    deleted = models.BooleanField(default=False)
    visibility = models.CharField(choices=Visibility.choices, default=Visibility.DEFAULT, max_length=20)
    version = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, blank=True)
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    last_modified_at = models.DateTimeField(default=timezone.now)
    last_modified_by = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="modified_notebooks",
    )

    class Meta:
        unique_together = ("team", "short_id")

    @classmethod
    def get_file_system_unfiled(cls, team: "Team") -> QuerySet["Notebook"]:
        base_qs = cls.objects.filter(team=team, deleted=False)
        return cls._filter_unfiled_queryset(base_qs, team, type="notebook", ref_field="short_id")

    def get_file_system_representation(self) -> FileSystemRepresentation:
        return FileSystemRepresentation(
            base_folder=self._get_assigned_folder("Unfiled/Notebooks"),
            type="notebook",  # sync with APIScopeObject in scopes.py
            ref=str(self.short_id),
            name=self.title or "Untitled",
            href=f"/notebooks/{self.short_id}",
            meta={"created_at": str(self.created_at), "created_by": self.created_by_id},
            should_delete=self.deleted or self.visibility == self.Visibility.INTERNAL,
        )
