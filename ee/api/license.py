from typing import Any

from django.conf import settings
from django.db.models import QuerySet
from rest_framework import mixins, serializers, viewsets

from ee.models.license import License


class LicenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = License
        fields = [
            "id",
            "key",
            "plan",
            "valid_until",
            "max_users",
            "created_at",
        ]
        read_only_fields = ["plan", "valid_until", "max_users"]

    def create(self, validated_data: Any) -> Any:
        return super().create({"key": validated_data.get("key")})


class LicenseViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet,
):
    queryset = License.objects.all()
    serializer_class = LicenseSerializer

    def get_queryset(self) -> QuerySet:
        if getattr(settings, "MULTI_TENANCY", False):
            return License.objects.none()

        return super().get_queryset()
