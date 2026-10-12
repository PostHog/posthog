"""
DRF views for authz.

Validate JSON via serializers, call facade methods,
return serialized responses. No business logic here.
"""

from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.permissions import IsStaffUser

from ..facade import api
from .serializers import OpenFgaStatusSerializer


class AuthzViewSet(viewsets.ViewSet):
    """Staff-only endpoints of the authz product."""

    # Staff-only and session-only: IsStaffUser gates access, and no API key scope grants it.
    scope_object = "INTERNAL"
    permission_classes = [IsAuthenticated, IsStaffUser]

    # A custom action instead of `list`, because drf-spectacular types a `list` response as an array.
    @extend_schema(responses={200: OpenFgaStatusSerializer})
    @action(methods=["GET"], detail=False)
    def status(self, request: Request, **kwargs: Any) -> Response:
        """Return whether OpenFGA is reachable, and the store and authorization model that authz uses."""
        return Response(OpenFgaStatusSerializer(api.get_openfga_status()).data)
