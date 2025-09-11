import uuid
from typing import cast

from django.utils import timezone

from rest_framework import response, serializers, status, viewsets
from rest_framework.permissions import BasePermission, IsAuthenticated

from posthog.api.utils import action
from posthog.auth import PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.models import PersonalAPIKey, User
from posthog.models.personal_api_key import hash_key_value
from posthog.models.team.team import Team
from posthog.models.utils import generate_random_token_personal, mask_key_value
from posthog.permissions import TimeSensitiveActionPermission
from posthog.scopes import API_SCOPE_ACTIONS, API_SCOPE_OBJECTS
from posthog.user_permissions import UserPermissions

MAX_API_KEYS_PER_USER = 10  # Same as in scopes.tsx


class PersonalAPIKeySerializer(serializers.ModelSerializer):
    # Specifying method name because the serializer class already has a get_value method
    value = serializers.SerializerMethodField(method_name="get_key_value", read_only=True)
    scopes = serializers.ListField(child=serializers.CharField(required=True))
    scoped_teams = serializers.ListField(child=serializers.IntegerField(required=False))
    scoped_organizations = serializers.ListField(child=serializers.CharField(required=False))

    class Meta:
        model = PersonalAPIKey
        fields = [
            "id",
            "label",
            "value",
            "mask_value",
            "created_at",
            "last_used_at",
            "user_id",
            "scopes",
            "scoped_teams",
            "scoped_organizations",
            "last_rolled_at",
        ]
        read_only_fields = ["id", "value", "mask_value", "created_at", "last_used_at", "user_id", "last_rolled_at"]

    def get_key_value(self, obj: PersonalAPIKey) -> str:
        return getattr(obj, "_value", None)  # type: ignore

    def validate_scopes(self, scopes):
        for scope in scopes:
            if scope == "*":
                continue

            scope_parts = scope.split(":")
            if (
                len(scope_parts) != 2
                or scope_parts[0] not in API_SCOPE_OBJECTS
                or scope_parts[1] not in API_SCOPE_ACTIONS
            ):
                raise serializers.ValidationError(f"Invalid scope: {scope}")

        return scopes

    def validate_scoped_teams(self, scoped_teams):
        requesting_user: User = self.context["request"].user
        user_permissions = UserPermissions(requesting_user)

        teams = Team.objects.filter(pk__in=scoped_teams)

        if len(teams) != len(scoped_teams):
            raise serializers.ValidationError(f"You must be a member of all teams that you are scoping the key to.")

        for team in teams:
            if user_permissions.team(team).effective_membership_level is None:
                raise serializers.ValidationError(f"You must be a member of all teams that you are scoping the key to.")

        return scoped_teams

    def validate_scoped_organizations(self, scoped_organizations):
        requesting_user: User = self.context["request"].user
        user_permissions = UserPermissions(requesting_user)
        org_memberships = user_permissions.organization_memberships

        try:
            organization_uuids = [uuid.UUID(organization_id) for organization_id in scoped_organizations]

            for organization_id in organization_uuids:
                if organization_id not in org_memberships or not org_memberships[organization_id].level:
                    raise serializers.ValidationError(
                        f"You must be a member of all organizations that you are scoping the key to."
                    )
        except ValueError:
            raise serializers.ValidationError("Invalid organization UUID")

        return scoped_organizations

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        ret["scopes"] = ret["scopes"] or ["*"]
        return ret

    def create(self, validated_data: dict, **kwargs) -> PersonalAPIKey:
        user = self.context["request"].user
        count = PersonalAPIKey.objects.filter(user=user).count()
        if count >= MAX_API_KEYS_PER_USER:
            raise serializers.ValidationError(
                f"You can only have {MAX_API_KEYS_PER_USER} personal API keys. Remove an existing key before creating a new one."
            )
        value = generate_random_token_personal()
        mask_value = mask_key_value(value)
        secure_value = hash_key_value(value)
        personal_api_key = PersonalAPIKey.objects.create(
            user=user, secure_value=secure_value, mask_value=mask_value, **validated_data
        )
        personal_api_key._value = value  # type: ignore
        return personal_api_key

    def roll(self, personal_api_key: PersonalAPIKey) -> PersonalAPIKey:
        value = generate_random_token_personal()
        mask_value = mask_key_value(value)
        secure_value = hash_key_value(value)

        personal_api_key = super().update(
            personal_api_key,
            {
                "secure_value": secure_value,
                "mask_value": mask_value,
                "last_rolled_at": timezone.now(),
            },
        )
        personal_api_key._value = value  # type: ignore
        return personal_api_key


class PersonalApiKeySelfAccessPermission(BasePermission):
    """
    Personal API Keys can only access their own key and only for retrieval
    """

    message = "This action does not support Personal API Key access"

    def has_permission(self, request, view) -> bool:
        # This permission check only applies to the personal api key
        if not isinstance(request.successful_authenticator, PersonalAPIKeyAuthentication):
            return True

        return view.action == "retrieve"

    def has_object_permission(self, request, view, item: PersonalAPIKey) -> bool:
        if not isinstance(request.successful_authenticator, PersonalAPIKeyAuthentication):
            return True

        return request.successful_authenticator.personal_api_key == item


class PersonalAPIKeyViewSet(viewsets.ModelViewSet):
    lookup_field = "id"
    serializer_class = PersonalAPIKeySerializer
    permission_classes = [IsAuthenticated, TimeSensitiveActionPermission, PersonalApiKeySelfAccessPermission]
    authentication_classes = [PersonalAPIKeyAuthentication, SessionAuthentication]
    queryset = PersonalAPIKey.objects.none()

    def get_queryset(self):
        return PersonalAPIKey.objects.filter(user_id=cast(User, self.request.user).id).order_by("-created_at")

    def get_object(self) -> PersonalAPIKey:
        lookup_value = self.kwargs[self.lookup_field]
        if lookup_value == "@current":
            authenticator = cast(PersonalAPIKeyAuthentication, self.request.successful_authenticator)
            return authenticator.personal_api_key

        return super().get_object()

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return response.Response(serializer.data)

    @action(methods=["POST"], detail=True, url_path="roll")
    def roll(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = cast(PersonalAPIKeySerializer, self.get_serializer(instance))
        serializer.roll(instance)
        return response.Response(serializer.data, status=status.HTTP_200_OK)
