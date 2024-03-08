from typing import TYPE_CHECKING, Tuple
from django.db import models
from django.core.validators import MinLengthValidator

if TYPE_CHECKING:
    from .team import Team


class ProjectManager(models.Manager):
    def create_with_team(self, *args, team_fields: dict, **kwargs) -> Tuple["Project", "Team"]:
        from .team import Team

        with models.transaction.atomic():
            project = self.create(*args, **kwargs)
            team = Team.objects.create(organization=project.organization, project=project, **team_fields)
            return project, team


class Project(models.Model):
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

    objects = ProjectManager()
