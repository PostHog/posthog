from typing import TYPE_CHECKING, cast
from urllib.parse import quote

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Exists, OuterRef, Q

from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.organization import OrganizationMembership
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.organization_offboarding_types import OffboardingResource

if TYPE_CHECKING:
    from posthog.models.user import User


@frozen
class PublicResourceKind:
    kind: str
    identifier_field: str
    name_field: str


PUBLIC_RESOURCE_KINDS = (
    PublicResourceKind(kind="dashboard", identifier_field="id", name_field="name"),
    PublicResourceKind(kind="insight", identifier_field="id", name_field="name"),
    PublicResourceKind(kind="notebook", identifier_field="short_id", name_field="title"),
    PublicResourceKind(kind="recording", identifier_field="session_id", name_field="session_id"),
)


class OrganizationOffboarding:
    def __init__(self, membership: OrganizationMembership) -> None:
        self.membership = membership
        self.organization_id = str(membership.organization_id)
        self.user_id = membership.user_id

    def _public_resources(
        self, resource_kind: PublicResourceKind, *, include_deleted: bool = False
    ) -> list[OffboardingResource]:
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
        if not include_deleted:
            configurations = configurations.exclude(**{f"{kind}__deleted": True})
        resources: dict[str, OffboardingResource] = {}
        for configuration in configurations.iterator(chunk_size=200):
            resource = cast(models.Model, getattr(configuration, kind))
            resource_id = f"public_link:{kind}:{configuration.team_id}:{getattr(configuration, f'{kind}_id')}"
            name = cast(str | None, getattr(resource, resource_kind.name_field))
            if kind == "insight" and not name:
                name = cast(str | None, resource.derived_name)
            path = {"dashboard": "dashboard", "insight": "insights", "notebook": "notebooks", "recording": "replay"}[
                kind
            ]
            identifier = (
                resource.short_id
                if kind in ("insight", "notebook")
                else getattr(resource, resource_kind.identifier_field)
            )
            resources.setdefault(
                resource_id,
                OffboardingResource(
                    id=resource_id,
                    kind=kind,
                    name=name or f"Untitled {kind}",
                    team_id=configuration.team_id,
                    project_name=configuration.team.name,
                    password_required=not configuration.has_unprotected_link,
                    url=f"/project/{configuration.team_id}/{path}/{quote(str(identifier), safe='')}",
                ),
            )
        return list(resources.values())

    def resources(self, *, include_deleted: bool = False) -> list[OffboardingResource]:
        resources = [
            resource
            for kind in PUBLIC_RESOURCE_KINDS
            for resource in self._public_resources(kind, include_deleted=include_deleted)
        ]
        return sorted(resources, key=lambda resource: (resource.name, resource.id))

    def remove(self, keep: set[str], *, actor: "User", was_impersonated: bool = False) -> None:
        if self.membership.level == OrganizationMembership.Level.OWNER:
            raise ValidationError("Cannot leave the organization as its owner!")
        with transaction.atomic():
            for resource in self.resources(include_deleted=True):
                if resource.id not in keep:
                    resource_id = resource.id.split(":", 3)[3]
                    configurations = SharingConfiguration.objects.filter(
                        team_id=resource.team_id, **{f"{resource.kind}_id": resource_id}
                    )
                    field = cast(models.ForeignKey, SharingConfiguration._meta.get_field(resource.kind))
                    resource_model = cast(type[models.Model], field.related_model)
                    # Cleanup includes soft-deleted objects hidden by the default manager.
                    locked_resource = resource_model._base_manager.select_for_update().get(
                        **{field.target_field.name: resource_id, "team_id": resource.team_id}
                    )
                    changed = configurations.filter(enabled=True).update(enabled=False)
                    if changed:
                        scope = {
                            "dashboard": "Dashboard",
                            "insight": "Insight",
                            "notebook": "Notebook",
                            "recording": "SessionRecording",
                        }[resource.kind]
                        short_id = getattr(locked_resource, "short_id", None)
                        log_activity(
                            organization_id=self.membership.organization_id,
                            team_id=resource.team_id,
                            user=actor,
                            was_impersonated=was_impersonated,
                            item_id=short_id if resource.kind == "notebook" else resource_id,
                            scope=scope,
                            activity="sharing disabled",
                            detail=Detail(
                                name=resource.name,
                                short_id=str(short_id) if short_id else None,
                                changes=[
                                    Change(type=scope, action="changed", field="sharing", before=True, after=False)
                                ],
                            ),
                        )
                    if resource.kind == "dashboard":
                        configuration = configurations.select_related("dashboard").first()
                        if configuration and configuration.dashboard:
                            configuration.dashboard.is_shared = False
                            configuration.dashboard.save(update_fields=["is_shared"])
            self.membership.user.leave(organization=self.membership.organization)
