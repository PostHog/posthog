from typing import cast

from django.db import IntegrityError
from django.db.models import QuerySet
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.utils import timezone

from rest_framework import response, serializers, status, viewsets
from rest_framework.exceptions import ValidationError

from posthog.api.documentation import extend_schema
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.auth import PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.models import User
from posthog.models.activity_logging.activity_log import changes_between
from posthog.models.activity_logging.model_activity import get_current_user, get_was_impersonated, model_activity_signal
from posthog.models.activity_logging.project_secret_api_key_utils import log_project_secret_api_key_activity
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.signals import mutable_receiver
from posthog.models.utils import generate_random_token_secret, hash_key_value, mask_key_value
from posthog.permissions import TeamMemberStrictManagementPermission, TimeSensitiveActionPermission
from posthog.scopes import (
    API_SCOPE_ACTIONS,
    API_SCOPE_OBJECTS,
    INTERNAL_API_SCOPE_OBJECTS,
    PROJECT_SECRET_API_KEY_ALLOWED_API_SCOPE_ACTION,
)

MAX_PROJECT_SECRET_API_KEYS_PER_TEAM = 10


class ProjectSecretAPIKeySerializer(serializers.ModelSerializer):
    value = serializers.SerializerMethodField(method_name="get_key_value", read_only=True)
    scopes = serializers.ListField(child=serializers.CharField(required=True), allow_empty=False)

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

            if (scope_parts[0], scope_parts[1]) not in PROJECT_SECRET_API_KEY_ALLOWED_API_SCOPE_ACTION:
                allowed_scopes = ", ".join(
                    [
                        f"{scope_object_action[0]}:{scope_object_action[1]}"
                        for scope_object_action in PROJECT_SECRET_API_KEY_ALLOWED_API_SCOPE_ACTION
                    ]
                )
                raise serializers.ValidationError(
                    f"Scope '{scope}' can not be assigned to a project secret API key. Allowed scopes: {allowed_scopes}"
                )
        return scopes

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


@extend_schema(tags=["core"])
class ProjectSecretAPIKeyViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "project"
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


@mutable_receiver(model_activity_signal, sender=ProjectSecretAPIKey)
def handle_project_secret_api_key_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    changes = changes_between(scope, previous=before_update, current=after_update)
    log_project_secret_api_key_activity(after_update, activity, user, was_impersonated, changes)


@receiver(pre_delete, sender=ProjectSecretAPIKey)
def handle_project_secret_api_key_delete(sender, instance, **kwargs):
    log_project_secret_api_key_activity(instance, "deleted", get_current_user(), get_was_impersonated())
