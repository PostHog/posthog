from typing import Any

from django.conf import settings
from django.db.models import QuerySet
from rest_framework import exceptions, mixins, serializers, viewsets
from sentry_sdk.api import capture_exception

from ee.models.license import License
from posthog.event_usage import report_license_activated


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
        response = None
        try:
            response = super().create({"key": validated_data.get("key")})
            report_license_activated(self.context["request"].user.distinct_id, {"key": validated_data.get("key")})
        except exceptions.APIException as e:
            capture_exception(e)
            raise e
        except Exception as e:
            capture_exception(e)

        return response


class LicenseViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet,
):
    queryset = License.objects.all()
    serializer_class = LicenseSerializer

    def get_queryset(self) -> QuerySet:
        if getattr(settings, "MULTI_TENANCY", False):
            return License.objects.none()

        return super().get_queryset()
