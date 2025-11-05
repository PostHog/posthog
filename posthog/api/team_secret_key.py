from typing import cast

from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import Team, TeamSecretKey, User

MAX_SECRET_KEYS_PER_TEAM = 20


class TeamSecretKeySerializer(serializers.ModelSerializer):
    value = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = TeamSecretKey
        fields = [
            "id",
            "name",
            "value",
            "mask_value",
            "created_at",
            "last_used_at",
            "created_by",
        ]
        read_only_fields = ["id", "value", "mask_value", "created_at", "last_used_at", "created_by"]

    def get_value(self, obj: TeamSecretKey) -> str | None:
        """Only return the plaintext value when it's just been created."""
        return getattr(obj, "_plaintext_value", None)

    def create(self, validated_data: dict) -> TeamSecretKey:
        user = cast(User, self.context["request"].user)
        team = cast(Team, self.context["team"])

        # Check limit
        count = TeamSecretKey.objects.filter(team=team).count()
        if count >= MAX_SECRET_KEYS_PER_TEAM:
            raise serializers.ValidationError(
                f"You can only have {MAX_SECRET_KEYS_PER_TEAM} secret keys per team. "
                "Remove an existing key before creating a new one."
            )

        # Check for duplicate name
        name = validated_data.get("name")
        if TeamSecretKey.objects.filter(team=team, name=name).exists():
            raise serializers.ValidationError(f"A secret key with the name '{name}' already exists for this team.")

        # Create the secret key
        secret_key, plaintext_value = TeamSecretKey.create_key(
            team=team,
            name=name,
            created_by=user,
        )

        # Attach the plaintext value so it can be returned in the response
        secret_key._plaintext_value = plaintext_value  # type: ignore

        return secret_key


class TeamSecretKeyViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    lookup_field = "id"
    queryset = TeamSecretKey.objects.all()
    serializer_class = TeamSecretKeySerializer
    permission_classes = []  # TeamMemberAccessPermission is added by the mixin

    def safely_get_queryset(self, queryset):
        return queryset.filter(team=self.team).order_by("-created_at")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["team"] = self.team
        return context
