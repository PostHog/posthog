"""
DRF views for agent_stack.

Validate JSON via serializers, call facade methods,
return serialized responses. No business logic here.
"""

from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from ..facade import api, contracts
from .serializers import CreateSplineReticulatorSerializer, SplineReticulatorSerializer


class SplineReticulatorViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"

    @extend_schema(responses={200: SplineReticulatorSerializer(many=True)})
    def list(self, request: Request, **kwargs) -> Response:
        items = api.list_all()
        return Response(SplineReticulatorSerializer(items, many=True).data)

    @extend_schema(request=CreateSplineReticulatorSerializer, responses={201: SplineReticulatorSerializer})
    def create(self, request: Request, **kwargs) -> Response:
        serializer = CreateSplineReticulatorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dto = api.create(contracts.CreateSplineReticulatorInput(
            team_id=self.team_id,
            **serializer.validated_data,
        ))
        return Response(SplineReticulatorSerializer(dto).data, status=status.HTTP_201_CREATED)
