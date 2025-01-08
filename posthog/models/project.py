from typing import TYPE_CHECKING, Optional, cast
from functools import cached_property
from django.db import models
from django.db import transaction
from django.core.validators import MinLengthValidator

from posthog.models.utils import sane_repr
from posthog.session_recordings.models.session_recording_playlist_templates import DEFAULT_PLAYLISTS
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist
from .team import Team
from .user import User


if TYPE_CHECKING:
    from posthog.models import Team, User


class ProjectManager(models.Manager):
    def create_with_team(
        self, *, team_fields: Optional[dict] = None, initiating_user: Optional["User"], **kwargs
    ) -> tuple["Project", "Team"]:
        if team_fields is None:
            team_fields = {}
        if "name" in kwargs and "name" not in team_fields:
            team_fields["name"] = kwargs["name"]

        with transaction.atomic(using=self.db):
            common_id = Team.objects.increment_id_sequence()
            project = cast("Project", self.create(id=common_id, **kwargs))
            team = Team.objects.create_with_data(
                id=common_id,
                organization_id=project.organization_id,
                project=project,
                initiating_user=initiating_user,
                **team_fields,
            )

            self._create_default_playlists(team, kwargs.get("initiating_user"))

            return project, team

    def _create_default_playlists(self, team: Team, created_by: Optional[User] = None) -> None:
        for playlist in DEFAULT_PLAYLISTS:
            SessionRecordingPlaylist.objects.create(
                team=team,
                name=playlist["name"],
                filters=playlist["filters"],
                description=playlist.get("description", ""),
                created_by=created_by,
            )


class Project(models.Model):
    id = models.BigIntegerField(primary_key=True, verbose_name="ID")  # Same as Team.id field
    organization = models.ForeignKey(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="projects",
        related_query_name="project",
    )
    name = models.CharField(
        max_length=200,
        default="Default project",
        validators=[MinLengthValidator(1, "Project must have a name!")],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    product_description = models.TextField(null=True, blank=True, max_length=1000)

    objects: ProjectManager = ProjectManager()

    def __str__(self):
        if self.name:
            return self.name
        return str(self.pk)

    __repr__ = sane_repr("id", "name")

    @cached_property
    def passthrough_team(self) -> "Team":
        return self.teams.get(pk=self.pk)
