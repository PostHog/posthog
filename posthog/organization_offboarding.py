from typing import cast
from urllib.parse import quote

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import CharField, Exists, OuterRef, Q
from django.db.models.functions import Cast

from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import OrganizationMembership
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.organization_offboarding_types import OffboardingResource

from products.subscriptions.backend.facade import api as subscriptions


@frozen
class PublicResourceKind:
    kind: str
    activity_scope: str
    activity_item_field: str
    name_field: str


PUBLIC_RESOURCE_KINDS = (
    PublicResourceKind(kind="dashboard", activity_scope="Dashboard", activity_item_field="id", name_field="name"),
    PublicResourceKind(kind="insight", activity_scope="Insight", activity_item_field="id", name_field="name"),
    PublicResourceKind(kind="notebook", activity_scope="Notebook", activity_item_field="short_id", name_field="title"),
    PublicResourceKind(
        kind="recording", activity_scope="SessionRecording", activity_item_field="session_id", name_field="session_id"
    ),
)


class OrganizationOffboarding:
    def __init__(self, membership: OrganizationMembership) -> None:
        self.membership = membership
        self.organization_id = str(membership.organization_id)
        self.user_id = membership.user_id

    def _public_resources(self, resource_kind: PublicResourceKind) -> list[OffboardingResource]:
        kind = resource_kind.kind
        sharing_history = ActivityLog.objects.filter(
            team_id=OuterRef("team_id"),
            scope=resource_kind.activity_scope,
            activity="sharing enabled",
        )
        shared_ids = sharing_history.filter(user_id=self.user_id).values("item_id")
        related_to_member = Q(shared_by__id=self.user_id) | Q(resource_log_id__in=shared_ids)
        if kind != "recording":
            related_to_member |= Q(**{f"{kind}__created_by_id": self.user_id})
        configurations = (
            SharingConfiguration.objects.filter(
                SharingConfiguration.tokens_active_q(),
                team__organization_id=self.organization_id,
                **{f"{kind}__isnull": False},
            )
            .exclude(**{f"{kind}__deleted": True})
            .annotate(resource_log_id=Cast(f"{kind}__{resource_kind.activity_item_field}", output_field=CharField()))
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
            .order_by("-created_at")
            .distinct()
        )
        resources: dict[str, OffboardingResource] = {}
        for configuration in configurations:
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
                else getattr(resource, resource_kind.activity_item_field)
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

    def resources(self) -> list[OffboardingResource]:
        resources = [resource for kind in PUBLIC_RESOURCE_KINDS for resource in self._public_resources(kind)]
        resources.extend(subscriptions.list_member_offboarding_resources(self.organization_id, self.user_id))
        return sorted(resources, key=lambda resource: (resource.name, resource.id))

    def remove(self, keep: set[str]) -> None:
        if self.membership.level == OrganizationMembership.Level.OWNER:
            raise ValidationError("Cannot leave the organization as its owner!")
        with transaction.atomic():
            for resource in self.resources():
                if resource.kind != "subscription" and resource.id not in keep:
                    resource_id = resource.id.split(":", 3)[3]
                    configurations = SharingConfiguration.objects.filter(
                        team_id=resource.team_id, **{f"{resource.kind}_id": resource_id}
                    )
                    configurations.update(enabled=False)
                    if resource.kind == "dashboard":
                        configuration = configurations.select_related("dashboard").first()
                        if configuration and configuration.dashboard:
                            configuration.dashboard.is_shared = False
                            configuration.dashboard.save(update_fields=["is_shared"])
            subscriptions.disable_member_offboarding_resources(self.organization_id, self.user_id, keep)
            self.membership.user.leave(organization=self.membership.organization)
