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

from products.alerts.backend.facade import organization_offboarding as alerts
from products.subscriptions.backend.facade import api as subscriptions

if TYPE_CHECKING:
    from posthog.models.user import User

    from products.dashboards.backend.models.dashboard import Dashboard
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
                    kind=kind,
                    name=name or f"Untitled {kind}",
                    team_id=configuration.team_id,
                    project_name=configuration.team.name,
                    password_required=not configuration.has_unprotected_link,
                    url=f"/project/{configuration.team_id}/{resource_kind.url_path}/{quote(str(identifier), safe='')}",
                ),
            )
        return list(resources.values())

    def resources(self, *, include_deleted: bool = False) -> list[OffboardingResource]:
        resources = [
            resource
            for kind in PUBLIC_RESOURCE_KINDS
            for resource in self._public_resources(kind, include_deleted=include_deleted)
        ]
        resources.extend(alerts.list_member_offboarding_resources(self.organization_id, self.user_id))
        resources.extend(subscriptions.list_member_offboarding_resources(self.organization_id, self.user_id))
        return sorted(resources, key=lambda resource: (resource.name, resource.id))

    def _set_public_sharing(self, resource_id: str, enabled: bool, *, actor: "User", was_impersonated: bool) -> None:
        parts = resource_id.split(":", 3)
        if len(parts) != 4 or parts[0] != "public_link" or not parts[2].isdigit():
            raise ValidationError("Invalid public resource.")
        _, kind, team_id, object_id = parts
        resource_kind = next((item for item in PUBLIC_RESOURCE_KINDS if item.kind == kind), None)
        if resource_kind is None:
            raise ValidationError("Invalid public resource.")
        field = cast(models.ForeignKey, SharingConfiguration._meta.get_field(kind))
        resource_model = cast(type[models.Model], field.related_model)
        object_id = field.target_field.to_python(object_id)
        resource = (
            resource_model._base_manager.select_for_update()
            .filter(
                team_id=int(team_id),
                team__organization_id=self.organization_id,
                **{field.target_field.name: object_id},
            )
            .first()
        )
        if resource is None or (enabled and getattr(resource, "deleted", False)):
            raise ValidationError("Resource no longer available.")

        configurations = SharingConfiguration.objects.filter(team_id=int(team_id), **{f"{kind}_id": object_id})
        if enabled:
            configuration = SharingConfiguration.get_active_for_resource(
                dedupe=True, team_id=int(team_id), **{f"{kind}_id": object_id}
            )
            if configuration is None:
                raise ValidationError("Resource no longer has a current public link.")
            changed = not configuration.enabled
            configuration.enabled = True
            configuration.shared_by = actor
            configuration.save(update_fields=["enabled", "shared_by"])
        else:
            changed = bool(configurations.filter(enabled=True).update(enabled=False))

        if changed:
            scope = {
                "dashboard": "Dashboard",
                "insight": "Insight",
                "notebook": "Notebook",
                "recording": "SessionRecording",
            }[kind]
            short_id = getattr(resource, "short_id", None)
            name = getattr(resource, resource_kind.name_field)
            log_activity(
                organization_id=self.membership.organization_id,
                team_id=int(team_id),
                user=actor,
                was_impersonated=was_impersonated,
                item_id=short_id if kind == "notebook" else object_id,
                scope=scope,
                activity="sharing " + ("enabled" if enabled else "disabled"),
                detail=Detail(
                    name=name or f"Untitled {kind}",
                    short_id=str(short_id) if short_id else None,
                    changes=[Change(type=scope, action="changed", field="sharing", before=not enabled, after=enabled)],
                ),
            )
        if kind == "dashboard":
            dashboard = cast("Dashboard", resource)
            dashboard.is_shared = enabled
            dashboard.save(update_fields=["is_shared"])

    def update_resources(self, ids: list[str], enabled: bool, *, actor: "User", was_impersonated: bool = False) -> None:
        with transaction.atomic():
            for resource_id in sorted(set(ids)):
                if resource_id.startswith("subscription:"):
                    subscriptions.update_member_offboarding_resource(
                        self.organization_id, self.user_id, resource_id, enabled
                    )
                elif resource_id.startswith("alert:"):
                    alerts.update_member_offboarding_resource(self.organization_id, self.user_id, resource_id, enabled)
                else:
                    self._set_public_sharing(resource_id, enabled, actor=actor, was_impersonated=was_impersonated)

    def remove(self, keep: set[str], *, actor: "User", was_impersonated: bool = False) -> None:
        if self.membership.level == OrganizationMembership.Level.OWNER:
            raise ValidationError("Cannot leave the organization as its owner!")
        with transaction.atomic():
            self.update_resources(
                [resource.id for resource in self.resources(include_deleted=True) if resource.id not in keep],
                False,
                actor=actor,
                was_impersonated=was_impersonated,
            )
            self.membership.user.leave(organization=self.membership.organization)
