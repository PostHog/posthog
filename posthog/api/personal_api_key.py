from typing import Type, cast

from rest_framework import mixins, response, serializers, viewsets

from posthog.models import PersonalAPIKey
from posthog.models.user import User


class PersonalAPIKeySerializer(serializers.ModelSerializer):
    """Standard PersonalAPIKey serializer that doesn't return key value."""

    class Meta:
        model = PersonalAPIKey
        fields = ["id", "label", "created_at", "last_used_at", "user_id"]
        read_only_fields = ["id", "created_at", "last_used_at", "user_id"]


class PersonalAPIKeySerializerCreateOnly(PersonalAPIKeySerializer):
    """Create-only PersonalAPIKey serializer that also returns key value."""

    class Meta:
        model = PersonalAPIKey
        fields = ["id", "label", "value", "created_at", "last_used_at", "user_id"]
        read_only_fields = ["id", "value", "created_at", "last_used_at", "user_id"]

    def create(self, validated_data: dict, **kwargs) -> PersonalAPIKey:
        user = self.context["request"].user
        personal_api_key = PersonalAPIKey.objects.create(user=user, **validated_data)
        return personal_api_key


class PersonalAPIKeyViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = PersonalAPIKeySerializer
    lookup_field = "id"

    def get_queryset(self):
        return PersonalAPIKey.objects.filter(user_id=cast(User, self.request.user).id).order_by("-created_at")

    def get_serializer_class(self) -> Type[serializers.ModelSerializer]:
        serializer_class = self.serializer_class
        if self.request.method == "POST":
            serializer_class = PersonalAPIKeySerializerCreateOnly
        return serializer_class

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return response.Response(serializer.data)
