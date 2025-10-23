from typing import cast

from django.db import IntegrityError
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.utils import timezone

from rest_framework import status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import ProjectSecretAPIKeyAllowedScope, ProjectSecretAPIKeyRequest

from posthog.api.documentation import extend_schema
from posthog.api.mixins import PydanticModelMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.activity_log import changes_between
from posthog.models.activity_logging.model_activity import get_current_user, get_was_impersonated
from posthog.models.activity_logging.project_secret_api_key_utils import log_project_secret_api_key_activity
from posthog.models.personal_api_key import hash_key_value
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.models.user import User
from posthog.models.utils import generate_random_token_secret, mask_key_value
from posthog.permissions import TeamMemberStrictManagementPermission, TimeSensitiveActionPermission
from posthog.scopes import API_SCOPE_ACTIONS

MAX_PROJECT_API_KEYS_PER_PROJECT = 10

PROJECT_SECRET_API_KEY_ALLOWED_SCOPES: tuple[str, ...] = tuple(scope.value for scope in ProjectSecretAPIKeyAllowedScope)


class ProjectSecretAPIKeyViewSet(TeamAndOrgViewSetMixin, PydanticModelMixin, viewsets.ModelViewSet):
    scope_object = "project"
    lookup_field = "id"
    permission_classes = [TimeSensitiveActionPermission, TeamMemberStrictManagementPermission]
    queryset = ProjectSecretAPIKey.objects.all()

    def get_serializer_class(self):
        return None  # We use Pydantic models instead

    def _serialize_project_secret_api_key(
        self, instance: ProjectSecretAPIKey, include_value: str | None = None
    ) -> dict:
        """Serialize a ProjectSecretAPIKey instance to a dictionary.

        Args:
            instance: The ProjectSecretAPIKey to serialize.
            include_value: If provided, includes the raw API key value in the response.
                          Used only for create and roll operations.
        """
        data = {
            "id": str(instance.id),
            "label": instance.label,
            "mask_value": instance.mask_value,
            "last_rolled_at": instance.last_rolled_at,
            "last_used_at": instance.last_used_at,
            "scopes": instance.scopes,
            "created_at": instance.created_at,
            "created_by": UserBasicSerializer(instance.created_by).data,
        }
        if include_value is not None:
            data["value"] = include_value
        return data

    @extend_schema(request=ProjectSecretAPIKeyRequest, description="Create a new project secret API key")
    def create(self, request: Request, *args, **kwargs) -> Response:
        data = self.get_model(request.data, ProjectSecretAPIKeyRequest)

        if not data.label or not data.label.strip():
            raise ValidationError({"label": "This field is required."})
        if not data.scopes:
            raise ValidationError({"scopes": "This field is required."})

        self.validate_scopes(data.scopes)
        team = self.team
        key_count = ProjectSecretAPIKey.objects.filter(team=team).count()
        if key_count >= MAX_PROJECT_API_KEYS_PER_PROJECT:
            raise ValidationError(
                f"A team can have at most {MAX_PROJECT_API_KEYS_PER_PROJECT} secret API keys. Remove an existing key before creating a new one."
            )

        key_value = generate_random_token_secret()
        masked_key_value = mask_key_value(key_value)
        secure_key_value = hash_key_value(key_value)

        try:
            project_secret_api_key = ProjectSecretAPIKey.objects.create(
                team=self.team,
                label=data.label,
                scopes=data.scopes,
                secure_value=secure_key_value,
                mask_value=masked_key_value,
                created_by=cast(User, request.user),
            )
            return Response(
                {
                    "id": str(project_secret_api_key.id),
                    "value": key_value,
                    "label": project_secret_api_key.label,
                    "created_at": project_secret_api_key.created_at,
                    "scopes": project_secret_api_key.scopes,
                },
                status=status.HTTP_201_CREATED,
            )
        except IntegrityError as e:
            if "unique_team_label" in str(e):
                raise ValidationError(
                    f"A secret API key with the label '{data.label}' already exists for this project."
                )
            capture_exception(e)
            raise ValidationError("Failed to create project secret API key.")
        except Exception as e:
            capture_exception(e)
            raise ValidationError("Failed to create project secret API key.")

    def validate_scopes(self, scopes):
        for scope in scopes:
            if scope == "*":
                raise ValidationError(
                    "Wildcard scope '*' is not allowed for project API keys. " "Please specify explicit scopes."
                )

            scope_parts = scope.split(":")
            if len(scope_parts) != 2 or scope_parts[1] not in API_SCOPE_ACTIONS:
                raise ValidationError(f"Invalid scope: {scope}")

            if scope not in PROJECT_SECRET_API_KEY_ALLOWED_SCOPES:
                raise ValidationError(
                    f"Scope '{scope}' is not available for project secret API keys. "
                    f"Allowed scopes: {', '.join(PROJECT_SECRET_API_KEY_ALLOWED_SCOPES)}"
                )
        return scopes

    def list(self, request: Request, *args, **kwargs) -> Response:
        queryset = self.filter_queryset(self.get_queryset())
        keys_data = [self._serialize_project_secret_api_key(instance) for instance in queryset]
        return Response(keys_data, status=status.HTTP_200_OK)

    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        instance = self.get_object()
        return Response(self._serialize_project_secret_api_key(instance), status=status.HTTP_200_OK)

    @extend_schema(request=ProjectSecretAPIKeyRequest, description="Update project secret API key")
    def update(self, request: Request, *args, **kwargs) -> Response:
        instance = self.get_object()
        data = self.get_model(request.data, ProjectSecretAPIKeyRequest)
        if data.scopes:
            self.validate_scopes(data.scopes)
            instance.scopes = data.scopes
        if data.label is not None:
            stripped_label = data.label.strip()
            if not stripped_label:
                raise ValidationError({"label": "Label cannot be empty."})
            instance.label = stripped_label

        instance.save()

        return Response(self._serialize_project_secret_api_key(instance), status=status.HTTP_200_OK)

    @extend_schema(description="Roll a project secret API key")
    @action(methods=["POST"], detail=True, url_path="roll")
    def roll(self, request: Request, *args, **kwargs) -> Response:
        instance = self.get_object()

        key_value = generate_random_token_secret()
        masked_key_value = mask_key_value(key_value)
        secure_key_value = hash_key_value(key_value)

        instance.secure_value = secure_key_value
        instance.mask_value = masked_key_value
        instance.last_rolled_at = timezone.now()
        instance.save()

        return Response(
            self._serialize_project_secret_api_key(instance, include_value=key_value), status=status.HTTP_200_OK
        )

    def destroy(self, request: Request, *args, **kwargs) -> Response:
        instance = self.get_object()
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@mutable_receiver(model_activity_signal, sender=ProjectSecretAPIKey)
def handle_project_secret_api_key_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    changes = changes_between(scope, previous=before_update, current=after_update)
    log_project_secret_api_key_activity(after_update, activity, user, was_impersonated, changes)


@receiver(pre_delete, sender=ProjectSecretAPIKey)
def handle_project_secret_api_key_delete(sender, instance, **kwargs):
    log_project_secret_api_key_activity(instance, "deleted", get_current_user(), get_was_impersonated())
