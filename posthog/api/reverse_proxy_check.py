from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.team.reverse_proxy_check import get_has_reverse_proxy


class ReverseProxyCheckSerializer(serializers.Serializer):
    has_reverse_proxy = serializers.BooleanField(
        help_text="Whether a $pageview or $screen event from the last day came through a custom API host, "
        "such as a reverse proxy. True when the reverse proxy setup task is already completed."
    )


class ReverseProxyCheckViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    # Only the app asks this, to decide on the reverse proxy notice and setup task, so API keys get no access.
    scope_object = "INTERNAL"

    @extend_schema(
        operation_id="reverse_proxy_check_retrieve",
        responses={200: ReverseProxyCheckSerializer},
        extensions={"x-product": "core"},
    )
    @action(detail=False, methods=["GET"], url_path="check")
    def check(self, request: Request, **kwargs: object) -> Response:
        return Response(ReverseProxyCheckSerializer({"has_reverse_proxy": get_has_reverse_proxy(self.team)}).data)
