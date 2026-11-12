from typing import ClassVar

from django.db.models import Model, QuerySet
from django.urls import reverse

from posthog.dataclasses import frozen
from posthog.models.data_deletion_request import DataDeletionRequest
from posthog.models.organization import Organization
from posthog.models.project import Project
from posthog.models.team.team import Team
from posthog.models.user import User

# Support tools link to staff pages with `?ticket=<ticket url>`, and Log in as user prefills its reason from it.
SUPPORT_TICKET_PARAM = "ticket"


@frozen
class RecordLink:
    label: str
    href: str
    title: str = ""
    # Query parameters of the current page that the link passes on, for example a support ticket.
    keep_query: tuple[str, ...] = ()


class RecordType:
    """A kind of record the console has pages for, for example a team.

    The shell owns the record types. A panel names one by `key`, and the console builds the record's page,
    its operation pages and their URLs from it.
    """

    key: ClassVar[str]
    # The URL segment, for example "teams" in /admin/console/teams/7/.
    plural: ClassVar[str]
    label: ClassVar[str]
    # A Django path converter for the primary key, so a malformed key is a 404 before any query runs.
    pk_converter: ClassVar[str]

    def queryset(self) -> QuerySet:
        raise NotImplementedError

    def title(self, obj: Model) -> str:
        raise NotImplementedError

    def subtitle(self, obj: Model) -> str:
        return ""

    def parents(self, obj: Model) -> list[RecordLink]:
        """The records above this one, for the breadcrumb. A team sits under its organization."""
        return []

    def links(self, obj: Model) -> list[RecordLink]:
        """Buttons in the page header that leave the console, for example to the raw row in Django admin."""
        return []

    @property
    def url_name(self) -> str:
        return f"admin_console_{self.key}"

    @property
    def operation_url_name(self) -> str:
        return f"admin_console_{self.key}_operation"

    def url(self, obj: Model) -> str:
        return reverse(self.url_name, kwargs={"pk": obj.pk})


class TeamRecord(RecordType):
    key = "team"
    plural = "teams"
    label = "Team"
    pk_converter = "int"

    def queryset(self) -> QuerySet:
        return Team.objects.select_related("organization")

    def title(self, obj: Model) -> str:
        assert isinstance(obj, Team)
        return obj.name

    def subtitle(self, obj: Model) -> str:
        assert isinstance(obj, Team)
        return obj.organization.name

    def parents(self, obj: Model) -> list[RecordLink]:
        assert isinstance(obj, Team)
        return [RecordLink(label=obj.organization.name, href=RECORD_TYPES["organization"].url(obj.organization))]

    def links(self, obj: Model) -> list[RecordLink]:
        return [
            RecordLink(
                label="Raw record in Django admin",
                href=reverse("admin:posthog_team_change", args=[obj.pk]),
                title="The raw Team row, with every field",
            ),
            RecordLink(label="Open in app ↗", href=f"/project/{obj.pk}"),
        ]


class OrganizationRecord(RecordType):
    key = "organization"
    plural = "organizations"
    label = "Organization"
    pk_converter = "uuid"

    def queryset(self) -> QuerySet:
        return Organization.objects.all()

    def title(self, obj: Model) -> str:
        assert isinstance(obj, Organization)
        return obj.name

    def links(self, obj: Model) -> list[RecordLink]:
        return [
            RecordLink(
                label="Raw record in Django admin",
                href=reverse("admin:posthog_organization_change", args=[obj.pk]),
                title="The raw Organization row, with every field",
            ),
        ]


class ProjectRecord(RecordType):
    key = "project"
    plural = "projects"
    label = "Project"
    pk_converter = "int"

    def queryset(self) -> QuerySet:
        return Project.objects.select_related("organization")

    def title(self, obj: Model) -> str:
        assert isinstance(obj, Project)
        return obj.name

    def subtitle(self, obj: Model) -> str:
        assert isinstance(obj, Project)
        return obj.organization.name

    def parents(self, obj: Model) -> list[RecordLink]:
        assert isinstance(obj, Project)
        return [RecordLink(label=obj.organization.name, href=RECORD_TYPES["organization"].url(obj.organization))]

    def links(self, obj: Model) -> list[RecordLink]:
        return [
            RecordLink(
                label="Raw record in Django admin",
                href=reverse("admin:posthog_project_change", args=[obj.pk]),
                title="The raw Project row, with every field",
            ),
            RecordLink(label="Open in app ↗", href=f"/project/{obj.pk}"),
        ]


class UserRecord(RecordType):
    key = "user"
    plural = "users"
    label = "User"
    pk_converter = "int"

    def queryset(self) -> QuerySet:
        return User.objects.select_related("current_organization", "current_team")

    def title(self, obj: Model) -> str:
        assert isinstance(obj, User)
        return obj.email

    def subtitle(self, obj: Model) -> str:
        assert isinstance(obj, User)
        return f"{obj.first_name} {obj.last_name}".strip()

    def links(self, obj: Model) -> list[RecordLink]:
        # No "Log in as user" here: impersonation stays in Django admin, which asks for the reason it logs and
        # prefills it from the support ticket.
        return [
            RecordLink(
                label="Raw record in Django admin",
                href=reverse("admin:posthog_user_change", args=[obj.pk]),
                title="The raw User row, with every field, and Log in as user",
                keep_query=(SUPPORT_TICKET_PARAM,),
            ),
        ]


def request_type_label(obj: DataDeletionRequest) -> str:
    """The request type in sentence case. The model's choice labels are title case, such as "Event Removal"."""
    label = obj.get_request_type_display()
    return label if label.startswith("HogQL") else label.capitalize()


class DeletionRequestRecord(RecordType):
    key = "deletion-request"
    plural = "deletion-requests"
    label = "Deletion request"
    pk_converter = "uuid"

    def queryset(self) -> QuerySet:
        return DataDeletionRequest.objects.select_related("approved_by", "criteria_updated_by")

    def title(self, obj: Model) -> str:
        assert isinstance(obj, DataDeletionRequest)
        return f"{request_type_label(obj)} request"

    def subtitle(self, obj: Model) -> str:
        assert isinstance(obj, DataDeletionRequest)
        return f"Team {obj.team_id}"

    def parents(self, obj: Model) -> list[RecordLink]:
        assert isinstance(obj, DataDeletionRequest)
        # The request keeps a bare team ID, and the team may be gone by now.
        team = Team.objects.select_related("organization").filter(pk=obj.team_id).first()
        if team is None:
            return []
        return [*TeamRecord().parents(team), RecordLink(label=team.name, href=TeamRecord().url(team))]

    def links(self, obj: Model) -> list[RecordLink]:
        return [
            RecordLink(
                label="Raw record in Django admin",
                href=reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]),
                title="The raw request, with every field",
            ),
        ]


RECORD_TYPES: dict[str, RecordType] = {
    record.key: record
    for record in (TeamRecord(), OrganizationRecord(), ProjectRecord(), UserRecord(), DeletionRequestRecord())
}


def console_url_for(obj: Model) -> str | None:
    """The console page of a record, for the Django admin change form of the same row. None when the console has
    no page for its model."""
    for record_type in RECORD_TYPES.values():
        if isinstance(obj, record_type.queryset().model) and obj.pk is not None:
            return record_type.url(obj)
    return None
