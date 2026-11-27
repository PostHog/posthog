import re
from collections.abc import Callable
from typing import Any, ClassVar

from django.core.exceptions import ValidationError
from django.db.models import Model, Q, QuerySet
from django.urls import reverse

from posthog.admin.console.panels import Fact
from posthog.admin.dagster_links import dagster_run_url
from posthog.admin.organization_members import organization_memberships
from posthog.dataclasses import frozen
from posthog.helpers.impersonation import Impersonation
from posthog.models.data_deletion_request import DataDeletionRequest
from posthog.models.oauth import OAuthApplication
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.project import Project
from posthog.models.team.team import Team
from posthog.models.user import User

# Support tools link to staff pages with `?ticket=<ticket url>`, and Log in as user prefills its reason from it.
SUPPORT_TICKET_PARAM = "ticket"
RELATED_SEGMENT = "related"


@frozen
class RecordLink:
    label: str
    href: str
    title: str = ""


@frozen
class Relation:
    """Records related to a record, for example the teams of an organization.

    The shell shows the first few under the record's header and lists all of them on a page of their own, so every
    record page links to its relatives in the same place and in the same way. Declare the way back on the other
    record type too, and name it in `inverse`.
    """

    key: str
    label: str
    target: str
    # Takes the primary key of the record. Ordered, so the header shows the same first rows as the full list.
    rows: Callable[[Any], QuerySet]
    # The record a row stands for when the rows are a join model, for example the user of a membership.
    record_of: Callable[[Any], Model] | None = None
    detail_of: Callable[[Any], str] | None = None
    columns: tuple[str, ...] = ()
    cells_of: Callable[[Any], tuple[str, ...]] | None = None
    search: Callable[[QuerySet, str], QuerySet] | None = None
    # The key of the relation on the target record type that leads back to this record type.
    inverse: str | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", self.key):
            raise ValueError(f"Relation key {self.key!r} must be a lowercase slug")
        if bool(self.columns) != (self.cells_of is not None):
            raise ValueError(f"Relation {self.key!r} sets columns without cells_of, or cells_of without columns")

    def record(self, row: Model) -> Model:
        return self.record_of(row) if self.record_of is not None else row


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
        """Buttons in the page header, for example to the raw row in Django admin."""
        return []

    def relations(self) -> tuple[Relation, ...]:
        """The records the page links to under its header. The breadcrumb stays in `parents`."""
        return ()

    def relation(self, key: str) -> Relation | None:
        return next((relation for relation in self.relations() if relation.key == key), None)

    @property
    def url_name(self) -> str:
        return f"admin_console_{self.key}"

    @property
    def operation_url_name(self) -> str:
        return f"admin_console_{self.key}_operation"

    @property
    def related_url_name(self) -> str:
        return f"admin_console_{self.key}_related"

    def url(self, obj: Model) -> str:
        return reverse(self.url_name, kwargs={"pk": obj.pk})

    def find(self, pk: str) -> Model | None:
        """The record with this primary key, or None when the key is malformed or names no record."""
        try:
            return self.queryset().filter(pk=pk.strip()).first() if pk.strip() else None
        except (ValueError, ValidationError):
            return None

    def short_id(self, obj: Model) -> str:
        """The ID to show next to a link to the record. A UUID is too long to read there, so it shows none."""
        return str(obj.pk) if self.pk_converter == "int" else ""


class Memberships:
    """How the console shows an organization membership, from the organization's side or from the user's."""

    @staticmethod
    def role(membership: OrganizationMembership) -> str:
        return OrganizationMembership.Level(membership.level).label.capitalize()

    @staticmethod
    def cells(membership: OrganizationMembership) -> tuple[str, ...]:
        user = membership.user
        return (
            Memberships.role(membership),
            f"{user.first_name} {user.last_name}".strip(),
            user.last_login.strftime("%b %-d, %Y") if user.last_login else "Never",
            membership.joined_at.strftime("%b %-d, %Y"),
        )

    @staticmethod
    def search(memberships: QuerySet, text: str) -> QuerySet:
        return memberships.filter(
            Q(user__email__icontains=text) | Q(user__first_name__icontains=text) | Q(user__last_name__icontains=text)
        )

    @staticmethod
    def members(memberships: Callable[[Any], QuerySet], label: str, inverse: str | None = None) -> Relation:
        return Relation(
            key="members",
            label=label,
            target="user",
            rows=memberships,
            record_of=lambda membership: membership.user,
            detail_of=Memberships.role,
            columns=("Role", "Name", "Last login", "Joined"),
            cells_of=Memberships.cells,
            search=Memberships.search,
            inverse=inverse,
        )


class TeamRecord(RecordType):
    key = "team"
    plural = "teams"
    label = "Team"
    pk_converter = "int"

    def queryset(self) -> QuerySet:
        return Team.objects.select_related("organization", "project")

    def title(self, obj: Model) -> str:
        assert isinstance(obj, Team)
        return obj.name

    def subtitle(self, obj: Model) -> str:
        assert isinstance(obj, Team)
        return obj.organization.name

    def parents(self, obj: Model) -> list[RecordLink]:
        assert isinstance(obj, Team)
        return [
            RecordLink(label=obj.organization.name, href=RECORD_TYPES["organization"].url(obj.organization)),
            RecordLink(label=obj.project.name, href=RECORD_TYPES["project"].url(obj.project)),
        ]

    def links(self, obj: Model) -> list[RecordLink]:
        return [
            RecordLink(
                label="Raw record in Django admin",
                href=reverse("admin:posthog_team_change", args=[obj.pk]),
                title="The raw Team row, with every field",
            ),
            RecordLink(label="Open in app ↗", href=f"/project/{obj.pk}"),
        ]

    def relations(self) -> tuple[Relation, ...]:
        return (
            Relation(
                key="organization",
                label="Organization",
                target="organization",
                rows=lambda pk: Organization.objects.filter(team=pk),
                inverse="teams",
            ),
            Relation(
                key="project",
                label="Project",
                target="project",
                rows=lambda pk: Project.objects.filter(team=pk),
                inverse="teams",
            ),
            # Members belong to the organization, not to the team, so the label says whose members they are.
            Memberships.members(
                lambda pk: organization_memberships(Organization.objects.filter(team=pk).values("id")[:1]),
                label="Organization members",
            ),
        )


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

    def relations(self) -> tuple[Relation, ...]:
        return (
            Relation(
                key="projects",
                label="Projects",
                target="project",
                rows=lambda pk: Project.objects.filter(organization_id=pk).order_by("id"),
                inverse="organization",
            ),
            Relation(
                key="teams",
                label="Teams",
                target="team",
                rows=lambda pk: Team.objects.filter(organization_id=pk).order_by("id"),
                inverse="organization",
            ),
            Memberships.members(organization_memberships, label="Members", inverse="organizations"),
        )


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

    def relations(self) -> tuple[Relation, ...]:
        return (
            Relation(
                key="organization",
                label="Organization",
                target="organization",
                rows=lambda pk: Organization.objects.filter(project=pk),
                inverse="projects",
            ),
            Relation(
                key="teams",
                label="Teams",
                target="team",
                rows=lambda pk: Team.objects.filter(project_id=pk).order_by("id"),
                inverse="project",
            ),
            Memberships.members(
                lambda pk: organization_memberships(Organization.objects.filter(project=pk).values("id")[:1]),
                label="Organization members",
            ),
        )


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
        assert isinstance(obj, User)
        links = []
        # The most used staff action on a user, so it sits in the header and not in a panel further down.
        if Impersonation.refusal(obj) is None:
            links.append(
                RecordLink(
                    label="Log in as user",
                    href=reverse(
                        self.operation_url_name,
                        kwargs={"pk": obj.pk, "panel_key": "log-in-as", "operation_key": "log-in"},
                    ),
                )
            )
        links.append(
            RecordLink(
                label="Raw record in Django admin",
                href=reverse("admin:posthog_user_change", args=[obj.pk]),
                title="The raw User row, with every field",
            )
        )
        return links

    def relations(self) -> tuple[Relation, ...]:
        return (
            Relation(
                key="organizations",
                label="Organizations",
                target="organization",
                rows=lambda pk: (
                    OrganizationMembership.objects.filter(user_id=pk)
                    .select_related("organization")
                    .order_by("joined_at", "id")
                ),
                record_of=lambda membership: membership.organization,
                detail_of=Memberships.role,
                columns=("Role",),
                cells_of=lambda membership: (Memberships.role(membership),),
                inverse="members",
            ),
        )


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
        assert isinstance(obj, DataDeletionRequest)
        links = [
            RecordLink(
                label="Raw record in Django admin",
                href=reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]),
                title="The raw request, with every field",
            ),
        ]
        run_url = dagster_run_url(obj.last_dagster_run_id) if obj.last_dagster_run_id else None
        if run_url is not None:
            links.append(
                RecordLink(label="Last run in Dagster", href=run_url, title="The latest deletion run of this request")
            )
        return links


class OAuthApplicationRecord(RecordType):
    key = "oauth-application"
    plural = "oauth-applications"
    label = "OAuth application"
    pk_converter = "uuid"

    def queryset(self) -> QuerySet:
        return OAuthApplication.objects.select_related("organization", "provisioning_review")

    def title(self, obj: Model) -> str:
        assert isinstance(obj, OAuthApplication)
        return obj.name

    def subtitle(self, obj: Model) -> str:
        assert isinstance(obj, OAuthApplication)
        return obj.client_id

    def parents(self, obj: Model) -> list[RecordLink]:
        assert isinstance(obj, OAuthApplication)
        if obj.organization is None:
            return []
        return [RecordLink(label=obj.organization.name, href=RECORD_TYPES["organization"].url(obj.organization))]

    def links(self, obj: Model) -> list[RecordLink]:
        return [
            RecordLink(
                label="Raw record in Django admin",
                href=reverse("admin:posthog_oauthapplication_change", args=[obj.pk]),
                title="The raw OAuthApplication row: redirect URIs, scopes and the other OAuth settings",
            ),
        ]


RECORD_TYPES: dict[str, RecordType] = {
    record.key: record
    for record in (
        TeamRecord(),
        OrganizationRecord(),
        ProjectRecord(),
        UserRecord(),
        DeletionRequestRecord(),
        OAuthApplicationRecord(),
    )
}


def record_fact(label: str, obj: Model) -> Fact:
    """A fact that names another record. The record's name is the link and its ID follows as plain text, the same way
    the related records under the page header show it."""
    record_type = next(
        record_type for record_type in RECORD_TYPES.values() if isinstance(obj, record_type.queryset().model)
    )
    return Fact(label=label, value=record_type.title(obj), href=record_type.url(obj), detail=record_type.short_id(obj))


def console_url_for(obj: Model) -> str | None:
    """The console page of a record, for the Django admin change form of the same row. None when the console has
    no page for its model."""
    for record_type in RECORD_TYPES.values():
        if isinstance(obj, record_type.queryset().model) and obj.pk is not None:
            return record_type.url(obj)
    return None
