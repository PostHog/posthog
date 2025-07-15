from functools import cached_property
from typing import TYPE_CHECKING, Optional, cast

from django.core.validators import MinLengthValidator
from django.db import models, transaction

from posthog.models.utils import sane_repr

if TYPE_CHECKING:
    from posthog.models import Team, User


class ProjectManager(models.Manager):
    def create_with_team(
        self, *, team_fields: Optional[dict] = None, initiating_user: Optional["User"], **kwargs
    ) -> tuple["Project", "Team"]:
        from .team import Team

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
            return project, team


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
    # Deprecated in favor of CoreMemory
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
