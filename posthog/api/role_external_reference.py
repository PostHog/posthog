import dataclasses
from typing import Any

from django.db import IntegrityError
from django.db.models import Q, QuerySet

from drf_spectacular.utils import extend_schema, extend_schema_field, extend_schema_view
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.scoped_related_fields import OrgScopedPrimaryKeyRelatedField
from posthog.api.shared import UserBasicSerializer
from posthog.models.utils import strict_fetch
from posthog.permissions import OrganizationAdminWritePermissions, TimeSensitiveActionPermission

from products.access_control.backend.facade import api as access_control_api
from products.access_control.backend.facade.contracts import RoleMembershipDrift, RoleSyncActionMode
from products.access_control.backend.models.role import Role
from products.access_control.backend.models.role_external_reference import RoleExternalReference


class OrganizationRoleScopedPrimaryKeyRelatedField(OrgScopedPrimaryKeyRelatedField):
    scope_field = "organization"


class RoleExternalReferenceDriftSerializer(serializers.Serializer):
    has_drift = serializers.BooleanField(
        read_only=True,
        help_text="Whether the PostHog role's current members differ from the external team's resolved PostHog members.",
    )
    to_add_count = serializers.IntegerField(
        read_only=True,
        help_text="Organization members on the external team who are not yet in the PostHog role.",
    )
    to_remove_count = serializers.IntegerField(
        read_only=True,
        help_text="Current PostHog role members who are not on the external team.",
    )
    provider_member_count = serializers.IntegerField(
        allow_null=True,
        read_only=True,
        help_text="Total handles on the external team at last sync, or null when never synced.",
    )
    matched_posthog_member_count = serializers.IntegerField(
        read_only=True,
        help_text="External team handles matched to PostHog organization members.",
    )
    current_role_member_count = serializers.IntegerField(
        read_only=True,
        help_text="Current valid member count on the PostHog role.",
    )


class RoleExternalReferenceSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    role = OrganizationRoleScopedPrimaryKeyRelatedField(
        queryset=Role.objects.all(),
        help_text="PostHog role UUID this external role maps to.",
    )
    drift = serializers.SerializerMethodField(
        help_text="Membership drift summary comparing the PostHog role against the last synced external team roster."
    )

    class Meta:
        model = RoleExternalReference
        fields = [
            "id",
            "provider",
            "provider_organization_id",
            "provider_role_id",
            "provider_role_slug",
            "provider_role_name",
            "role",
            "sync_mode",
            "role_created_by_sync",
            "orphaned_at",
            "last_synced_at",
            "drift",
            "created_at",
            "created_by",
        ]
        read_only_fields = [
            "id",
            "sync_mode",
            "role_created_by_sync",
            "orphaned_at",
            "last_synced_at",
            "drift",
            "created_at",
            "created_by",
        ]
        extra_kwargs = {
            "provider": {"help_text": "Integration kind (e.g., github, linear, jira, slack)."},
            "provider_organization_id": {"help_text": "Provider organization/workspace/site identifier."},
            "provider_role_id": {"help_text": "Stable provider role identifier."},
            "provider_role_slug": {"help_text": "Human-friendly provider role identifier."},
            "provider_role_name": {"help_text": "Display name of the provider role."},
            "sync_mode": {
                "help_text": "How membership updates from the external team apply (`manual`, `proposed`, or `auto`)."
            },
            "role_created_by_sync": {
                "help_text": "Whether the linked PostHog role was originally created by external team ingestion."
            },
            "orphaned_at": {
                "help_text": "Timestamp when the external team disappeared on the provider while keeping the PostHog role."
            },
            "last_synced_at": {"help_text": "Timestamp of the most recent external team sync."},
        }

    @extend_schema_field(RoleExternalReferenceDriftSerializer)
    def get_drift(self, obj: RoleExternalReference) -> dict[str, Any]:
        drifts_by_id = self.context.get("drifts_by_id")
        if drifts_by_id is None:
            drifts_by_id = access_control_api.compute_role_reference_drifts(
                organization_id=obj.organization_id,
                reference_ids=[obj.id],
            )
        drift = drifts_by_id.get(obj.id) or RoleMembershipDrift(
            has_drift=False,
            to_add_user_ids=frozenset(),
            to_remove_user_ids=frozenset(),
            provider_member_count=None,
            matched_posthog_member_count=0,
            current_role_member_count=0,
        )
        return {
            "has_drift": drift.has_drift,
            "to_add_count": len(drift.to_add_user_ids),
            "to_remove_count": len(drift.to_remove_user_ids),
            "provider_member_count": drift.provider_member_count,
            "matched_posthog_member_count": drift.matched_posthog_member_count,
            "current_role_member_count": drift.current_role_member_count,
        }

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        organization = self.context["view"].organization
        provider = data.get("provider", self.instance.provider if self.instance else "")
        provider_organization_id = data.get(
            "provider_organization_id", self.instance.provider_organization_id if self.instance else ""
        )

        provider_role_slug = data.get("provider_role_slug", self.instance.provider_role_slug if self.instance else "")
        if provider_role_slug:
            slug_qs = RoleExternalReference.objects.filter(
                organization=organization,
                provider=provider,
                provider_organization_id__iexact=provider_organization_id,
                provider_role_slug__iexact=provider_role_slug,
            )
            if self.instance is not None:
                slug_qs = slug_qs.exclude(pk=self.instance.pk)
            if slug_qs.exists():
                raise serializers.ValidationError(
                    "A role external reference with this provider, organization, and role slug already exists."
                )

        provider_role_id = data.get("provider_role_id", self.instance.provider_role_id if self.instance else "")
        if provider_role_id:
            id_qs = RoleExternalReference.objects.filter(
                organization=organization,
                provider=provider,
                provider_organization_id__iexact=provider_organization_id,
                provider_role_id__iexact=provider_role_id,
            )
            if self.instance is not None:
                id_qs = id_qs.exclude(pk=self.instance.pk)
            if id_qs.exists():
                raise serializers.ValidationError(
                    "A role external reference with this provider, organization, and role ID already exists."
                )

        return data

    def update(self, instance: RoleExternalReference, validated_data: dict[str, Any]) -> RoleExternalReference:
        if "role" in validated_data and validated_data["role"].id != instance.role_id:
            validated_data["role_created_by_sync"] = False
            if instance.sync_mode == RoleExternalReference.SyncMode.PROPOSED:
                validated_data["sync_mode"] = RoleExternalReference.SyncMode.MANUAL
        try:
            return super().update(instance, validated_data)
        except IntegrityError as err:
            raise serializers.ValidationError(
                "A role external reference with this provider, organization, and role identifier already exists."
            ) from err

    def create(self, validated_data: dict[str, Any]) -> RoleExternalReference:
        validated_data["organization"] = self.context["view"].organization
        validated_data["created_by"] = self.context["request"].user
        try:
            return super().create(validated_data)
        except IntegrityError as err:
            raise serializers.ValidationError(
                "A role external reference with this provider, organization, and role identifier already exists."
            ) from err


class RoleLookupQuerySerializer(serializers.Serializer):
    provider = serializers.CharField(help_text="Integration kind (e.g., github, linear, jira, slack).")
    provider_organization_id = serializers.CharField(help_text="Provider organization/workspace/site identifier.")
    provider_role_slug = serializers.CharField(required=False, help_text="Human-friendly provider role identifier.")
    provider_role_id = serializers.CharField(required=False, help_text="Stable provider role identifier.")

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        if not data.get("provider_role_slug") and not data.get("provider_role_id"):
            raise serializers.ValidationError("Either provider_role_slug or provider_role_id must be provided.")
        return data


class RoleLookupResponseSerializer(serializers.Serializer):
    reference = RoleExternalReferenceSerializer(
        allow_null=True, help_text="Matching reference, or null if none exists."
    )


class RoleExternalReferenceListQuerySerializer(serializers.Serializer):
    provider = serializers.CharField(
        required=False,
        help_text="Filter references by integration kind (e.g., github, linear, jira, slack).",
    )
    provider_organization_id = serializers.CharField(
        required=False,
        help_text="Filter references by provider organization/workspace/site identifier.",
    )
    role_id = serializers.UUIDField(
        required=False,
        help_text="Filter references mapped to a specific PostHog role UUID.",
    )


class RoleExternalReferenceApplySyncSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(
        choices=RoleSyncActionMode.choices,
        help_text="Sync operation to apply: `once` (reconcile members now), `auto` (keep in sync), or `manual` (pause automatic sync).",
    )


class GitHubRoleSyncResponseSerializer(serializers.Serializer):
    created_roles = serializers.IntegerField(
        read_only=True,
        help_text="New PostHog roles created from GitHub teams.",
    )
    updated_roles = serializers.IntegerField(
        read_only=True,
        help_text="Existing GitHub role references refreshed.",
    )
    proposed_roles = serializers.IntegerField(
        read_only=True,
        help_text="Pre-existing manual PostHog roles matched as sync proposals without mutating members.",
    )
    orphaned_references = serializers.IntegerField(
        read_only=True,
        help_text="Previously synced references marked orphaned because their GitHub team was deleted.",
    )
    skipped_missing_members_permission = serializers.BooleanField(
        read_only=True,
        help_text="True when at least one GitHub organization installation lacked `members: read` permission.",
    )


@extend_schema(extensions={"x-product": "integrations"})
@extend_schema_view(list=extend_schema(parameters=[RoleExternalReferenceListQuerySerializer]))
class RoleExternalReferenceViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "organization"
    serializer_class = RoleExternalReferenceSerializer
    queryset = RoleExternalReference.objects.select_related("created_by", "role").all()
    permission_classes = [OrganizationAdminWritePermissions, TimeSensitiveActionPermission]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        if self.action == "list":
            queryset = strict_fetch(queryset)

        provider = self.request.query_params.get("provider")
        if provider:
            queryset = queryset.filter(provider=provider)

        provider_organization_id = self.request.query_params.get("provider_organization_id")
        if provider_organization_id:
            queryset = queryset.filter(provider_organization_id__iexact=provider_organization_id)

        role_id = self.request.query_params.get("role_id")
        if role_id:
            queryset = queryset.filter(role_id=role_id)

        return queryset.order_by("provider", "provider_organization_id", "provider_role_slug", "provider_role_name")

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        rows = list(page) if page is not None else list(queryset)
        context = {
            **self.get_serializer_context(),
            "drifts_by_id": access_control_api.compute_role_reference_drifts(
                organization_id=self.organization.id,
                reference_ids=[row.id for row in rows],
            ),
        }
        serializer = self.get_serializer(rows, many=True, context=context)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @extend_schema(parameters=[RoleLookupQuerySerializer], responses={200: RoleLookupResponseSerializer})
    @action(detail=False, methods=["GET"], url_path="lookup")
    def lookup(self, request: Request, **kwargs: Any) -> Response:
        query = RoleLookupQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)

        base_q = Q(
            organization=self.organization,
            provider=query.validated_data["provider"],
            provider_organization_id__iexact=query.validated_data["provider_organization_id"],
        )

        match_q = Q()
        if query.validated_data.get("provider_role_slug"):
            match_q |= Q(provider_role_slug__iexact=query.validated_data["provider_role_slug"])
        if query.validated_data.get("provider_role_id"):
            match_q |= Q(provider_role_id__iexact=query.validated_data["provider_role_id"])

        reference = RoleExternalReference.objects.filter(base_q & match_q).select_related("created_by", "role").first()

        serializer = self.get_serializer(reference) if reference else None
        return Response({"reference": serializer.data if serializer else None})

    @extend_schema(
        request=RoleExternalReferenceApplySyncSerializer,
        responses={200: RoleExternalReferenceSerializer},
    )
    @action(detail=True, methods=["POST"], url_path="apply_sync")
    def apply_sync(self, request: Request, **kwargs: Any) -> Response:
        instance = self.get_object()
        payload = RoleExternalReferenceApplySyncSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        access_control_api.apply_role_external_reference_sync(
            organization_id=self.organization.id,
            reference_id=instance.id,
            mode=RoleSyncActionMode(payload.validated_data["mode"]),
        )
        refreshed = RoleExternalReference.objects.select_related("created_by", "role").get(
            id=instance.id,
            organization=self.organization,
        )
        return Response(self.get_serializer(refreshed).data)

    @extend_schema(
        request=None,
        responses={200: GitHubRoleSyncResponseSerializer},
    )
    @action(detail=False, methods=["POST"], url_path="sync_github")
    def sync_github(self, request: Request, **kwargs: Any) -> Response:
        outcome = access_control_api.sync_organization_github_roles(
            organization_id=self.organization.id,
            interactive=True,
        )
        return Response(GitHubRoleSyncResponseSerializer(dataclasses.asdict(outcome)).data, status=status.HTTP_200_OK)
