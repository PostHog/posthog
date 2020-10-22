from typing import Any

from django.conf import settings
from django.db.models import QuerySet
from rest_framework import authentication, exceptions, request, response, serializers, viewsets
from rest_framework.response import Response

from ee.models.license import License, LicenseError


class LicenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = License
        fields = [
            "created_at",
            "plan",
            "key",
            "valid_until",
        ]
        read_only_fields = ["created_at", "plan", "valid_until"]


class LicenseViewSet(viewsets.ModelViewSet):
    queryset = License.objects.all()
    serializer_class = LicenseSerializer

    def get_queryset(self) -> QuerySet:
        if getattr(settings, "MULTI_TENANCY", False):
            return License.objects.none()

        return super().get_queryset()

    def create(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        try:
            license = License.objects.create(key=request.data["key"])
        except LicenseError as e:
            return Response(data={"detail": e.detail, "code": e.code}, status=400)

        return Response(LicenseSerializer(license, context={"request": request}).data)
