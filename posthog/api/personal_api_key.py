from typing import cast

from rest_framework import response, serializers, viewsets

from posthog.models import PersonalAPIKey, User
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_personal


class StringListField(serializers.Field):
    def to_representation(self, value):
        return value.split(",") if value else None

    def to_internal_value(self, data):
        return ",".join(data)


class PersonalAPIKeySerializer(serializers.ModelSerializer):
    scopes = StringListField(required=True)

    # Specifying method name because the serializer class already has a get_value method
    value = serializers.SerializerMethodField(method_name="get_key_value", read_only=True)

    class Meta:
        model = PersonalAPIKey
        fields = ["id", "label", "value", "created_at", "last_used_at", "user_id", "scopes"]
        read_only_fields = ["id", "value", "created_at", "last_used_at", "user_id"]

    def get_key_value(self, obj: PersonalAPIKey) -> str:
        return getattr(obj, "_value", None)  # type: ignore

    def validate(self, attrs):
        # TODO: Properly check that they are valid scopes
        return attrs

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
