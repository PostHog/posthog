from typing import TYPE_CHECKING, Optional, cast
from django.db import models
from django.db import transaction
from django.core.validators import MinLengthValidator

from posthog.models.utils import sane_repr

if TYPE_CHECKING:
    from .team import Team


class ProjectManager(models.Manager):
    def create_with_team(self, team_fields: Optional[dict] = None, **kwargs) -> tuple["Project", "Team"]:
        from .team import Team

        with transaction.atomic(using=self.db):
            common_id = Team.objects.increment_id_sequence()
            project = cast("Project", self.create(id=common_id, **kwargs))
            team = Team.objects.create(
                id=common_id, organization=project.organization, project=project, **(team_fields or {})
            )
            return project, team


class Project(models.Model):
    """DO NOT USE YET - you probably mean the `Team` model instead.

    `Project` is part of the environments feature, which is a work in progress.
    """

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

    objects: ProjectManager = ProjectManager()

    def __str__(self):
        if self.name:
            return self.name
        return str(self.pk)

    __repr__ = sane_repr("id", "name")
