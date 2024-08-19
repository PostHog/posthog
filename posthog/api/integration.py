from typing import Any

from django.http import HttpResponse
from django.shortcuts import redirect
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.integration import Integration, OauthIntegration, SlackIntegration


class IntegrationSerializer(serializers.ModelSerializer):
    """Standard Integration serializer."""

    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = Integration
        fields = ["id", "kind", "config", "created_at", "created_by", "errors", "display_name"]
        read_only_fields = ["id", "created_at", "created_by", "errors", "display_name"]

    def create(self, validated_data: Any) -> Any:
        request = self.context["request"]
        team_id = self.context["team_id"]

        if validated_data["kind"] in OauthIntegration.supported_kinds:
            try:
                instance = OauthIntegration.integration_from_oauth_response(
                    validated_data["kind"], team_id, request.user, validated_data["config"]
                )
            except NotImplementedError:
                raise ValidationError("Kind not configured")
            return instance

        raise ValidationError("Kind not supported")


class IntegrationViewSet(
    TeamAndOrgViewSetMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "INTERNAL"
    queryset = Integration.objects.all()
    serializer_class = IntegrationSerializer

    @action(methods=["GET"], detail=False)
    def authorize(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        kind = request.GET.get("kind")
        next = request.GET.get("next", "")

        if kind in OauthIntegration.supported_kinds:
            try:
                auth_url = OauthIntegration.authorize_url(kind, next=next)
                return redirect(auth_url)
            except NotImplementedError:
                raise ValidationError("Kind not configured")

        raise ValidationError("Kind not supported")

    @action(methods=["GET"], detail=True, url_path="channels")
    def channels(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        slack = SlackIntegration(instance)

        channels = [
            {
                "id": channel["id"],
                "name": channel["name"],
                "is_private": channel["is_private"],
                "is_member": channel["is_member"],
                "is_ext_shared": channel["is_ext_shared"],
            }
            for channel in slack.list_channels()
        ]

        return Response({"channels": channels})
