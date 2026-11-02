from urllib.parse import quote

from django.db.models import Exists, OuterRef, Q

from posthog.dataclasses import frozen
from posthog.models.organization import OrganizationMembership
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.organization_offboarding_types import OffboardingResource

from products.alerts.backend.facade import organization_offboarding as alerts
from products.subscriptions.backend.facade import api as subscriptions


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
            .values(
                "has_unprotected_link",
                "team_id",
                "team__name",
                f"{kind}_id",
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
            team_id = configuration["team_id"]
            object_id = configuration[f"{kind}_id"]
            resource_id = f"public_link:{kind}:{team_id}:{object_id}"
            name = configuration[f"{kind}__{resource_kind.name_field}"]
            if kind == "insight" and not name:
                name = configuration["insight__derived_name"]
            identifier = configuration[
                f"{kind}__short_id" if kind in ("insight", "notebook") else f"{kind}__{resource_kind.identifier_field}"
            ]
            resources.setdefault(
                resource_id,
                OffboardingResource(
                    id=resource_id,
                    resource_id=str(configuration["notebook__short_id"] if kind == "notebook" else object_id),
                    kind=kind,
                    name=name or f"Untitled {kind}",
                    team_id=team_id,
                    project_name=configuration["team__name"],
                    password_protected=not configuration["has_unprotected_link"],
                    url=f"/project/{team_id}/{resource_kind.url_path}/{quote(str(identifier), safe='')}",
                ),
            )
        return list(resources.values())

    def resources(self) -> list[OffboardingResource]:
        resources = [resource for kind in PUBLIC_RESOURCE_KINDS for resource in self._public_resources(kind)]
        resources.extend(alerts.list_member_offboarding_resources(self.organization_id, self.user_id))
        resources.extend(subscriptions.list_member_offboarding_resources(self.organization_id, self.user_id))
        return sorted(resources, key=lambda resource: (resource.name, resource.id))
