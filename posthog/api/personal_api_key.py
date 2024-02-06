from typing import Type, cast

from rest_framework import mixins, response, serializers, viewsets

from posthog.models import PersonalAPIKey, User
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_personal


class PersonalAPIKeySerializer(serializers.ModelSerializer):
    """Standard PersonalAPIKey serializer that doesn't return key value."""

    class Meta:
        model = PersonalAPIKey
        fields = ["id", "label", "created_at", "last_used_at", "user_id", "scopes"]
        read_only_fields = ["id", "created_at", "last_used_at", "user_id"]

    def get_scopes(self, obj: PersonalAPIKey) -> list[str]:
        return obj.scopes.split(",") if obj.scopes else []


class PersonalAPIKeySerializerCreateOnly(serializers.ModelSerializer):
    """Create-only PersonalAPIKey serializer that also returns key value."""

    # Specifying method name because the serializer class already has a get_value method
    value = serializers.SerializerMethodField(method_name="get_key_value", read_only=True)

    class Meta:
        model = PersonalAPIKey
        fields = ["id", "label", "value", "created_at", "last_used_at", "user_id", "scopes"]
        read_only_fields = ["id", "value", "created_at", "last_used_at", "user_id"]

    def get_key_value(self, obj: PersonalAPIKey) -> str:
        return obj._value  # type: ignore

    def create(self, validated_data: dict, **kwargs) -> PersonalAPIKey:
        user = self.context["request"].user
        value = generate_random_token_personal()
        secure_value = hash_key_value(value)
        personal_api_key = PersonalAPIKey.objects.create(user=user, secure_value=secure_value, **validated_data)
        personal_api_key._value = value  # type: ignore
        return personal_api_key


class PersonalAPIKeyViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    lookup_field = "id"

    def get_queryset(self):
        return PersonalAPIKey.objects.filter(user_id=cast(User, self.request.user).id).order_by("-created_at")

    def get_serializer_class(self) -> Type[serializers.Serializer]:
        if self.request.method == "POST":
            return PersonalAPIKeySerializerCreateOnly
        else:
            return PersonalAPIKeySerializer

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return response.Response(serializer.data)
