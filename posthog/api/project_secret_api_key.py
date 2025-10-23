from typing import cast

from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import ProjectSecretAPIKeyRequest

from posthog.api.documentation import extend_schema
from posthog.api.mixins import PydanticModelMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.exceptions_capture import capture_exception
from posthog.models.personal_api_key import hash_key_value
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.user import User
from posthog.models.utils import generate_random_token_secret, mask_key_value
from posthog.permissions import TeamMemberStrictManagementPermission, TimeSensitiveActionPermission
from posthog.scopes import API_SCOPE_ACTIONS

MAX_SECRET_API_KEYS_PER_TEAM = 10

# Keep in sync with frontend/src/lib/scopes.tsx
PROJECT_SECRET_API_KEY_ALLOWED_SCOPES: tuple[str, ...] = ("endpoint:read",)


class ProjectSecretAPIKeyViewSet(TeamAndOrgViewSetMixin, PydanticModelMixin, viewsets.ModelViewSet):
    scope_object = "project"
    lookup_field = "id"
    permission_classes = [TimeSensitiveActionPermission, TeamMemberStrictManagementPermission]
    queryset = ProjectSecretAPIKey.objects.all()

    def get_serializer_class(self):
        return None  # We use Pydantic models instead

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
        if key_count >= MAX_SECRET_API_KEYS_PER_TEAM:
            raise ValidationError(
                f"A team can have at most {MAX_SECRET_API_KEYS_PER_TEAM} secret API keys. Remove an existing key before creating a new one."
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
        keys_data = [
            {
                "id": str(key.id),
                "label": key.label,
                "mask_value": key.mask_value,
                "last_rolled_at": key.last_rolled_at,
                "scopes": key.scopes,
                "created_at": key.created_at,
                "created_by": UserBasicSerializer(key.created_by).data,
            }
            for key in queryset
        ]
        return Response(keys_data, status=status.HTTP_200_OK)

    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        instance = self.get_object()
        return Response(
            {
                "id": str(instance.id),
                "label": instance.label,
                "mask_value": instance.mask_value,
                "last_rolled_at": instance.last_rolled_at,
                "scopes": instance.scopes,
                "created_at": instance.created_at,
                "created_by": UserBasicSerializer(instance.created_by).data,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(request=ProjectSecretAPIKeyRequest, description="Update project secret API key")
    def update(self, request: Request, *args, **kwargs) -> Response:
        instance = self.get_object()
        data = self.get_model(request.data, ProjectSecretAPIKeyRequest)
        if data.scopes:
            self.validate_scopes(data.scopes)
            instance.scopes = data.scopes
        if data.label:
            instance.label = data.label

        instance.save()

        return Response(
            {
                "id": str(instance.id),
                "label": instance.label,
                "mask_value": instance.mask_value,
                "created_at": instance.created_at,
                "scopes": instance.scopes,
                "created_by": UserBasicSerializer(instance.created_by).data,
            },
            status=status.HTTP_200_OK,
        )

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
            {
                "id": str(instance.id),
                "label": instance.label,
                "mask_value": instance.mask_value,
                "created_at": instance.created_at,
                "scopes": instance.scopes,
                "last_rolled_at": instance.last_rolled_at,
                "value": key_value,
            },
            status=status.HTTP_200_OK,
        )

    def destroy(self, request: Request, id=None, *args, **kwargs) -> Response:
        project_secret_api_key = get_object_or_404(ProjectSecretAPIKey, team=self.team, id=id)
        project_secret_api_key.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
