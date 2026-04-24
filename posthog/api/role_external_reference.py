from typing import Any

from django.db import IntegrityError
from django.db.models import Q, QuerySet

from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.scoped_related_fields import OrgScopedPrimaryKeyRelatedField
from posthog.api.shared import UserBasicSerializer
from posthog.models.role_external_reference import RoleExternalReference
from posthog.permissions import OrganizationAdminWritePermissions, TimeSensitiveActionPermission

from ee.models.rbac.role import Role


class OrganizationRoleScopedPrimaryKeyRelatedField(OrgScopedPrimaryKeyRelatedField):
    scope_field = "organization"


class RoleExternalReferenceSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    role = OrganizationRoleScopedPrimaryKeyRelatedField(
        queryset=Role.objects.all(),
        help_text="PostHog role UUID this external role maps to.",
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
            "created_at",
            "created_by",
        ]
        read_only_fields = ["id", "created_at", "created_by"]
        extra_kwargs = {
            "provider": {"help_text": "Integration kind (e.g., github, linear, jira, slack)."},
            "provider_organization_id": {"help_text": "Provider organization/workspace/site identifier."},
            "provider_role_id": {"help_text": "Stable provider role identifier."},
            "provider_role_slug": {"help_text": "Human-friendly provider role identifier."},
            "provider_role_name": {"help_text": "Display name of the provider role."},
        }

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        organization = self.context["view"].organization
        provider = data.get("provider", "")
        provider_organization_id = data.get("provider_organization_id", "")

        provider_role_slug = data.get("provider_role_slug", "")
        if provider_role_slug:
            slug_conflict = RoleExternalReference.objects.filter(
                organization=organization,
                provider=provider,
                provider_organization_id__iexact=provider_organization_id,
                provider_role_slug__iexact=provider_role_slug,
            ).exists()
            if slug_conflict:
                raise serializers.ValidationError(
                    "A role external reference with this provider, organization, and role slug already exists."
                )

        provider_role_id = data.get("provider_role_id", "")
        if provider_role_id:
            id_conflict = RoleExternalReference.objects.filter(
                organization=organization,
                provider=provider,
                provider_organization_id__iexact=provider_organization_id,
                provider_role_id__iexact=provider_role_id,
            ).exists()
            if id_conflict:
                raise serializers.ValidationError(
                    "A role external reference with this provider, organization, and role ID already exists."
                )

        return data

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


@extend_schema(tags=["integrations"])
class RoleExternalReferenceViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "organization"
    serializer_class = RoleExternalReferenceSerializer
    queryset = RoleExternalReference.objects.select_related("created_by", "role").all()
    permission_classes = [OrganizationAdminWritePermissions, TimeSensitiveActionPermission]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        provider = self.request.query_params.get("provider")
        if provider:
            queryset = queryset.filter(provider=provider)

        provider_organization_id = self.request.query_params.get("provider_organization_id")
        if provider_organization_id:
            queryset = queryset.filter(provider_organization_id__iexact=provider_organization_id)

        role_id = self.request.query_params.get("role_id")
        if role_id:
            queryset = queryset.filter(role_id=role_id)

        return queryset.order_by("provider", "provider_organization_id", "provider_role_slug")

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
