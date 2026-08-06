from functools import cached_property
from typing import TYPE_CHECKING, Optional, cast
from uuid import UUID

from django.core.validators import MinLengthValidator
from django.db import models, transaction

from posthog.models.utils import UpdatedMetaFields, sane_repr

if TYPE_CHECKING:
    from posthog.models import Team, User


DEFAULT_PROJECT_NAME = "Default project"


class ProjectManager(models.Manager["Project"]):
    def get_unique_default_name(self, organization_id: "UUID | str") -> str:
        """Return the default project name, suffixed with a number if already taken in the organization."""
        taken = {
            name.strip().lower()
            for name in self.filter(
                organization_id=organization_id, name__istartswith=DEFAULT_PROJECT_NAME
            ).values_list("name", flat=True)
        }
        if DEFAULT_PROJECT_NAME.lower() not in taken:
            return DEFAULT_PROJECT_NAME
        suffix = 2
        while f"{DEFAULT_PROJECT_NAME.lower()} {suffix}" in taken:
            suffix += 1
        return f"{DEFAULT_PROJECT_NAME} {suffix}"

    def create(self, **kwargs) -> "Project":
        # Without an explicit name the model default would produce ever more "Default project"
        # duplicates in the org, so pick the first free numbered variant instead.
        if not kwargs.get("name"):
            kwargs.pop("name", None)
            organization_id = kwargs.get("organization_id") or getattr(kwargs.get("organization"), "id", None)
            if organization_id is not None:
                kwargs["name"] = self.get_unique_default_name(organization_id)
        return super().create(**kwargs)

    def create_with_team(
        self, *, team_fields: Optional[dict] = None, initiating_user: Optional["User"], **kwargs
    ) -> tuple["Project", "Team"]:
        from .team import Team

        if team_fields is None:
            team_fields = {}
        if not kwargs.get("name"):
            kwargs.pop("name", None)
            organization_id = kwargs.get("organization_id") or getattr(kwargs.get("organization"), "id", None)
            if organization_id is not None:
                kwargs["name"] = self.get_unique_default_name(organization_id)
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


class Project(UpdatedMetaFields):
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
    is_pending_deletion = models.BooleanField(
        default=False,
        null=True,
        blank=True,
        help_text="Set to True when project deletion has been initiated. Blocks UI access to this project until the async task completes.",
    )

    objects: ProjectManager = ProjectManager()

    def __str__(self):
        if self.name:
            return self.name
        return str(self.pk)

    __repr__ = sane_repr("id", "name")

    @cached_property
    def passthrough_team(self) -> "Team":
        return self.teams.get(pk=self.pk)
