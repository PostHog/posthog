from typing import Any
from rest_framework import serializers, viewsets, permissions
from rest_framework.request import Request
from rest_framework.response import Response

from rest_framework import mixins
from posthog.models.vercel_resouce import VercelResource


class VercelResourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = VercelResource
        fields = "__all__"


class VercelResourceViewSet(
    mixins.RetrieveModelMixin, mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    serializer_class = VercelResourceSerializer
    lookup_field = "resource_id"
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        installation_id = self.kwargs.get("installation_id")
        return VercelResource.objects.filter(installation__installation_id=installation_id)

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raise serializers.MethodNotAllowed("POST")

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().retrieve(request, *args, **kwargs)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raise serializers.MethodNotAllowed("PATCH")

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raise serializers.MethodNotAllowed("DELETE")
