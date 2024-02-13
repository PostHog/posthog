from typing import cast

from rest_framework import response, serializers, viewsets

from posthog.models import PersonalAPIKey, User
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import API_SCOPE_ACTIONS, API_SCOPE_OBJECTS, hash_key_value
from posthog.models.utils import generate_random_token_personal
from posthog.user_permissions import UserPermissions


class StringListField(serializers.Field):
    def to_representation(self, value):
        return value.split(",") if value else None

    def to_internal_value(self, data):
        return ",".join(data)


class PersonalAPIKeySerializer(serializers.ModelSerializer):
    scopes = StringListField(required=True)
    scoped_teams = StringListField(required=False)
    scoped_organizations = StringListField(required=False)

    # Specifying method name because the serializer class already has a get_value method
    value = serializers.SerializerMethodField(method_name="get_key_value", read_only=True)

    class Meta:
        model = PersonalAPIKey
        fields = [
            "id",
            "label",
            "value",
            "created_at",
            "last_used_at",
            "user_id",
            "scopes",
            "scoped_teams",
            "scoped_organizations",
        ]
        read_only_fields = ["id", "value", "created_at", "last_used_at", "user_id"]

    def get_key_value(self, obj: PersonalAPIKey) -> str:
        return getattr(obj, "_value", None)  # type: ignore

    def validate_scopes(self, scopes):
        for scope in scopes.split(","):
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

        for team in scoped_teams.split(","):
            if user_permissions.team(team).effective_membership_level is None:
                raise serializers.ValidationError(f"You must be a member of all teams that you are scoping the key to.")

        return scoped_teams

    def validate_scoped_organizations(self, scoped_organizations):
        requesting_user: User = self.context["request"].user
        user_permissions = UserPermissions(requesting_user)
        org_memberships = user_permissions.organization_memberships

        for organization in scoped_organizations.split(","):
            if scoped_organizations not in org_memberships or not org_memberships[organization].level:
                raise serializers.ValidationError(
                    f"You must be a member of all organizations that you are scoping the key to."
                )

        return scoped_organizations

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        ret["scopes"] = ret["scopes"] or ["*"]
        return ret

    def create(self, validated_data: dict, **kwargs) -> PersonalAPIKey:
        user = self.context["request"].user
        value = generate_random_token_personal()
        secure_value = hash_key_value(value)
        personal_api_key = PersonalAPIKey.objects.create(user=user, secure_value=secure_value, **validated_data)
        personal_api_key._value = value  # type: ignore
        return personal_api_key


class PersonalAPIKeyViewSet(viewsets.ModelViewSet):
    lookup_field = "id"
    serializer_class = PersonalAPIKeySerializer

    def get_queryset(self):
        return PersonalAPIKey.objects.filter(user_id=cast(User, self.request.user).id).order_by("-created_at")

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return response.Response(serializer.data)
