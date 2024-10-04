from rest_framework import status
from rest_framework import viewsets
from rest_framework.response import Response

from posthog.api.mixins import PydanticModelMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.cdp.validation import compile_hog
from posthog.schema import HogCompileResponse


class HogViewSet(TeamAndOrgViewSetMixin, PydanticModelMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"

    def create(self, request, *args, **kwargs) -> Response:
        hog = request.data.get("hog")
        bytecode = compile_hog(hog)

        return Response(HogCompileResponse(bytecode=bytecode).model_dump(), status=status.HTTP_200_OK)
