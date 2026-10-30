from typing import TYPE_CHECKING, cast
from urllib.parse import quote

from django.db import models
from django.db.models import Exists, OuterRef, Q

from posthog.dataclasses import frozen
from posthog.models.organization import OrganizationMembership
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.organization_offboarding_types import OffboardingResource

if TYPE_CHECKING:
    from products.notebooks.backend.models import Notebook
    from products.product_analytics.backend.models.insight import Insight


@frozen
class PublicResourceKind:
    kind: str
    identifier_field: str
    name_field: str
    url_path: str


PUBLIC_RESOURCE_KINDS = (
    PublicResourceKind(kind="dashboard", identifier_field="id", name_field="name", url_path="dashboard"),
    PublicResourceKind(kind="insight", identifier_field="id", name_field="name", url_path="insights"),
    PublicResourceKind(kind="notebook", identifier_field="short_id", name_field="title", url_path="notebooks"),
    PublicResourceKind(kind="recording", identifier_field="session_id", name_field="session_id", url_path="replay"),
)


class OrganizationOffboarding:
    def __init__(self, membership: OrganizationMembership) -> None:
        self.membership = membership
        self.organization_id = str(membership.organization_id)
        self.user_id = membership.user_id

    def _public_resources(self, resource_kind: PublicResourceKind) -> list[OffboardingResource]:
        kind = resource_kind.kind
        related_to_member = Q(shared_by_id=self.user_id)
        if kind != "recording":
            related_to_member |= Q(shared_by__isnull=True, **{f"{kind}__created_by_id": self.user_id})
        configurations = (
            SharingConfiguration.objects.filter(
                SharingConfiguration.tokens_active_q(),
                team__organization_id=self.organization_id,
                **{f"{kind}__isnull": False},
            )
            .filter(related_to_member)
            .annotate(
                has_unprotected_link=Exists(
                    SharingConfiguration.objects.filter(
                        SharingConfiguration.tokens_active_q(),
                        team_id=OuterRef("team_id"),
                        password_required=False,
                        **{f"{kind}_id": OuterRef(f"{kind}_id")},
                    )
                ),
            )
            .select_related(kind, "team")
            .only(
                "id",
                "team_id",
                "team__name",
                kind,
                f"{kind}__{resource_kind.name_field}",
                f"{kind}__{resource_kind.identifier_field}",
                *([f"{kind}__short_id"] if kind in ("insight", "notebook") else []),
                *(["insight__derived_name"] if kind == "insight" else []),
            )
            .order_by("-created_at")
        )
        # nosemgrep: orm-field-injection -- kind comes from the fixed PUBLIC_RESOURCE_KINDS registry
        configurations = configurations.exclude(**{f"{kind}__deleted": True})
        resources: dict[str, OffboardingResource] = {}
        for configuration in configurations.iterator(chunk_size=200):
            resource = cast(models.Model, getattr(configuration, kind))
            resource_id = f"public_link:{kind}:{configuration.team_id}:{getattr(configuration, f'{kind}_id')}"
            name = cast(str | None, getattr(resource, resource_kind.name_field))
            if kind == "insight" and not name:
                name = cast("Insight", resource).derived_name
            identifier = (
                cast("Insight | Notebook", resource).short_id
                if kind in ("insight", "notebook")
                else getattr(resource, resource_kind.identifier_field)
            )
            resources.setdefault(
                resource_id,
                OffboardingResource(
                    id=resource_id,
                    resource_id=str(
                        cast("Notebook", resource).short_id
                        if kind == "notebook"
                        else getattr(configuration, f"{kind}_id")
                    ),
                    kind=kind,
                    name=name or f"Untitled {kind}",
                    team_id=configuration.team_id,
                    project_name=configuration.team.name,
                    password_required=not configuration.has_unprotected_link,
                    url=f"/project/{configuration.team_id}/{resource_kind.url_path}/{quote(str(identifier), safe='')}",
                ),
            )
        return list(resources.values())

    def resources(self) -> list[OffboardingResource]:
        resources = [resource for kind in PUBLIC_RESOURCE_KINDS for resource in self._public_resources(kind)]
        return sorted(resources, key=lambda resource: (resource.name, resource.id))
