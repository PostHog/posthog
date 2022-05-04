import requests
from django.conf import settings
from django.db.models import QuerySet
from rest_framework import mixins, serializers, viewsets

from ee.models.license import License, LicenseError


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

    def validate(self, data):
        validation = requests.post("https://license.posthog.com/licenses/activate", data={"key": data["key"]})
        resp = validation.json()
        if not validation.ok:
            raise LicenseError(resp["code"], resp["detail"])
        data["valid_until"] = resp["valid_until"]
        data["plan"] = resp["plan"]
        data["max_users"] = resp.get("max_users", 0)
        return data


class LicenseViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet,
):
    queryset = License.objects.all()
    serializer_class = LicenseSerializer

    def get_queryset(self) -> QuerySet:
        if getattr(settings, "MULTI_TENANCY", False):
            return License.objects.none()

        return super().get_queryset()
