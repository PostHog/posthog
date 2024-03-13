from typing import TYPE_CHECKING, Optional, Tuple
from django.db import models
from django.db import transaction
from django.core.validators import MinLengthValidator

if TYPE_CHECKING:
    from .team import Team


class ProjectManager(models.Manager):
    def create_with_team(self, team_fields: Optional[dict] = None, **kwargs) -> Tuple["Project", "Team"]:
        from .team import Team

        with transaction.atomic():
            common_id = Team.objects.increment_id_sequence()
            project = self.create(id=common_id, **kwargs)
            team = Team.objects.create(
                id=common_id, organization=project.organization, project=project, **(team_fields or {})
            )
            return project, team


class Project(models.Model):
    """DO NOT USE YET - you probably mean the `Team` model instead.

    `Project` is part of the environemnts feature, which is a work in progress.
    """

    id: models.BigIntegerField = models.BigIntegerField(primary_key=True, verbose_name="ID")
    organization: models.ForeignKey = models.ForeignKey(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="projects",
        related_query_name="project",
    )
    name: models.CharField = models.CharField(
        max_length=200,
        default="Default project",
        validators=[MinLengthValidator(1, "Project must have a name!")],
    )
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)

    objects: ProjectManager = ProjectManager()
