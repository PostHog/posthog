from typing import cast

from django.db import IntegrityError
from django.db.models import QuerySet
from django.utils import timezone

import posthoganalytics
from rest_framework import response, serializers, status, viewsets
from rest_framework.exceptions import ValidationError

from posthog.api.documentation import extend_schema
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.auth import PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.models import User
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.utils import generate_random_token_secret, hash_key_value, mask_key_value
from posthog.permissions import TeamMemberStrictManagementPermission, TimeSensitiveActionPermission
from posthog.scopes import (
    API_SCOPE_ACTIONS,
    API_SCOPE_OBJECTS,
    INTERNAL_API_SCOPE_OBJECTS,
    PROJECT_SECRET_API_KEY_ALLOWED_API_SCOPE_ACTION,
)

MAX_PROJECT_SECRET_API_KEYS_PER_TEAM = 50


class ProjectSecretAPIKeySerializer(serializers.ModelSerializer):
    value = serializers.SerializerMethodField(method_name="get_key_value", read_only=True)
    scopes = serializers.ListField(
        child=serializers.CharField(required=True),
        allow_empty=False,
        help_text=(
            "Project-wide API scopes granted to this key. Project secret API keys do not honor object-level "
            "access controls, so a scope can access resources of that type even when per-resource RBAC would "
            "hide them from an individual user."
        ),
    )
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = ProjectSecretAPIKey
        fields = [
            "id",
            "label",
            "value",
            "mask_value",
            "created_at",
            "created_by",
            "last_used_at",
            "last_rolled_at",
            "scopes",
        ]
        read_only_fields = [
            "id",
            "mask_value",
            "created_at",
            "created_by",
            "last_used_at",
            "last_rolled_at",
        ]

    def get_key_value(self, obj: ProjectSecretAPIKey) -> str:
        return getattr(obj, "_value", None)  # type: ignore

    def validate_scopes(self, scopes):
        allowed = set(PROJECT_SECRET_API_KEY_ALLOWED_API_SCOPE_ACTION)
        # Allow llm_gateway:read only when the flag is on or the key already has it, so a flag
        # rollback can't make an existing key unsaveable. Flag is evaluated only when requested.
        if any(s.startswith("llm_gateway:") for s in scopes) and self._llm_gateway_grantable():
            allowed.add(("llm_gateway", "read"))

        for scope in scopes:
            if scope == "*":
                raise serializers.ValidationError(
                    "Wildcard scope '*' is not allowed for project API keys. Please specify explicit scopes."
                )
            scope_parts = scope.split(":")
            if (
                len(scope_parts) != 2
                or scope_parts[0] not in API_SCOPE_OBJECTS
                or scope_parts[0] in INTERNAL_API_SCOPE_OBJECTS
                or scope_parts[1] not in API_SCOPE_ACTIONS
            ):
                raise serializers.ValidationError(f"Invalid scope: {scope}")

            if (scope_parts[0], scope_parts[1]) not in allowed:
                if (scope_parts[0], scope_parts[1]) == ("llm_gateway", "read"):
                    raise serializers.ValidationError(
                        "LLM gateway scope is not available for this project. Contact support to enable this feature."
                    )
                allowed_scopes = ", ".join(f"{obj}:{action}" for obj, action in sorted(allowed))
                raise serializers.ValidationError(
                    f"Scope '{scope}' can not be assigned to a project secret API key. Allowed scopes: {allowed_scopes}"
                )
        return scopes

    def _llm_gateway_grantable(self) -> bool:
        existing_has_llm_gateway = self.instance is not None and any(
            s.startswith("llm_gateway:") for s in (self.instance.scopes or [])
        )
        return existing_has_llm_gateway or self._ai_gateway_enabled()

    def _ai_gateway_enabled(self) -> bool:
        team = self.context["view"].team
        user = self.context["request"].user
        return bool(
            posthoganalytics.feature_enabled(
                "ai-gateway",
                str(user.distinct_id),
                groups={"organization": str(team.organization_id), "project": str(team.id)},
                group_properties={"organization": {"id": str(team.organization_id)}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        ret["scopes"] = ret["scopes"] or []
        return ret

    def create(self, validated_data: dict, **kwargs) -> ProjectSecretAPIKey:
        user = self.context["request"].user
        team = self.context["view"].team
        count = ProjectSecretAPIKey.objects.filter(team=team).count()
        if count >= MAX_PROJECT_SECRET_API_KEYS_PER_TEAM:
            raise serializers.ValidationError(
                f"You can only have {MAX_PROJECT_SECRET_API_KEYS_PER_TEAM} project secret API keys. Remove an existing key before creating a new one."
            )

        key_value = generate_random_token_secret()
        masked_key_value = mask_key_value(key_value)
        secure_key_value = hash_key_value(key_value)
        try:
            project_secret_api_key = ProjectSecretAPIKey.objects.create(
                team=team,
                secure_value=secure_key_value,
                mask_value=masked_key_value,
                created_by=cast(User, user),
                label=validated_data["label"],
                scopes=validated_data["scopes"],
            )
            project_secret_api_key._value = key_value  # type: ignore
            return project_secret_api_key
        except IntegrityError as e:
            if "unique_team_label" in str(e):
                raise ValidationError(f"Project secret API key with label '{validated_data['label']}' already exists.")
            raise

    def roll(self, project_secret_api_key: ProjectSecretAPIKey) -> ProjectSecretAPIKey:
        key_value = generate_random_token_secret()
        masked_key_value = mask_key_value(key_value)
        secure_key_value = hash_key_value(key_value)

        project_secret_api_key = super().update(
            project_secret_api_key,
            {"secure_value": secure_key_value, "mask_value": masked_key_value, "last_rolled_at": timezone.now()},
        )
        project_secret_api_key._value = key_value  # type: ignore

        return project_secret_api_key


@extend_schema(extensions={"x-product": "core"})
class ProjectSecretAPIKeyViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "project"
    scope_object_write_actions = ["create", "update", "partial_update", "patch", "destroy", "roll"]
    lookup_field = "id"
    serializer_class = ProjectSecretAPIKeySerializer
    permission_classes = [TimeSensitiveActionPermission, TeamMemberStrictManagementPermission]
    authentication_classes = [PersonalAPIKeyAuthentication, SessionAuthentication]

    queryset = ProjectSecretAPIKey.objects.all()

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.select_related("created_by").order_by("-created_at")

    @extend_schema(
        description="Roll a project secret API key", request=None, responses={200: ProjectSecretAPIKeySerializer}
    )
    @action(methods=["POST"], detail=True, url_path="roll")
    def roll(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = cast(ProjectSecretAPIKeySerializer, self.get_serializer(instance))
        serializer.roll(instance)
        return response.Response(serializer.data, status=status.HTTP_200_OK)
