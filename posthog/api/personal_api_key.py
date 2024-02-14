from typing import cast
import uuid

from rest_framework import response, serializers, viewsets

from posthog.models import PersonalAPIKey, User
from posthog.models.personal_api_key import API_SCOPE_ACTIONS, API_SCOPE_OBJECTS, hash_key_value
from posthog.models.team.team import Team
from posthog.models.utils import generate_random_token_personal
from posthog.user_permissions import UserPermissions


class StringListField(serializers.Field):
    def to_representation(self, value):
        return value.split(",") if value else None

    def to_internal_value(self, data):
        return ",".join(data)


class StringListIntsField(serializers.Field):
    def to_representation(self, value):
        return [int(x) for x in value.split(",")] if value else None

    def to_internal_value(self, data):
        return ",".join(str(x) for x in data)


class PersonalAPIKeySerializer(serializers.ModelSerializer):
    scopes = StringListField(required=True)
    scoped_teams = StringListIntsField(required=False)
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

        scoped_teams_list = scoped_teams.split(",")
        teams = Team.objects.filter(pk__in=scoped_teams_list)

        if len(teams) != len(scoped_teams_list):
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
            organization_uuids = [uuid.UUID(organization_id) for organization_id in scoped_organizations.split(",")]

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
