from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import exceptions, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User
from posthog.rate_limit import AIGatewaySpendLimitBurstThrottle, AIGatewaySpendLimitSustainedThrottle

from ..facade import api
from .serializers import SpendLimitErrorSerializer, SpendLimitSerializer, SpendLimitWriteSerializer

_GATEWAY_ERROR = {502: OpenApiResponse(response=SpendLimitErrorSerializer)}
# Only a write fails when the gateway holds no limits; a read reports enforced=False.
_WRITE_ERRORS = {**_GATEWAY_ERROR, 503: OpenApiResponse(response=SpendLimitErrorSerializer)}


class _SpendLimitsUnsupported(exceptions.APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Spend limits aren't available on this deployment yet."
    default_code = "spend_limits_unsupported"


class _SpendLimitsUnavailable(exceptions.APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "Couldn't reach the spend limit service. Try again in a moment."
    default_code = "spend_limits_unavailable"


class _SpendLimitsRejected(exceptions.APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "The spend limit service rejected the request. Contact support if this keeps happening."
    default_code = "spend_limits_rejected"


class SingletonSchema(AutoSchema):
    """Stops drf-spectacular treating `list` as returning an array; this resource is one object per person."""

    def _is_list_view(self, serializer: object = None) -> bool:
        return False


class UserSpendLimitViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    # Product-scoped rather than riding `user`: a write moves a money control, so
    # it must not come for free with a broad `user:write` key. A named scope also
    # keeps the platform's team/org token scoping and the org's personal-API-key
    # ban in force, both of which `scope_object = "user"` is exempt from.
    scope_object = "ai_gateway"
    # `list` on a plain ViewSet and a custom @action match none of
    # ScopeBasePermission's default action lists, so personal-API-key requests
    # 403 without these spelled out.
    scope_object_read_actions = ["list"]
    scope_object_write_actions = ["create", "clear"]
    serializer_class = SpendLimitSerializer
    throttle_classes = [AIGatewaySpendLimitBurstThrottle, AIGatewaySpendLimitSustainedThrottle]
    schema = SingletonSchema()

    @extend_schema(
        operation_id="ai_gateway_user_spend_limit_retrieve",
        responses={200: SpendLimitSerializer, **_GATEWAY_ERROR},
    )
    def list(self, request: Request, **kwargs) -> Response:
        with _spend_limit_errors():
            limit = api.get_spend_limit(self.team_id, _requesting_user(request))
        return Response(SpendLimitSerializer(limit).data)

    @validated_request(
        request_serializer=SpendLimitWriteSerializer,
        operation_id="ai_gateway_user_spend_limit_create",
        responses={200: OpenApiResponse(response=SpendLimitSerializer), **_WRITE_ERRORS},
    )
    def create(self, request: ValidatedRequest, **kwargs) -> Response:
        with _spend_limit_errors():
            limit = api.set_spend_limit(
                self.team_id,
                _requesting_user(request),
                limit_usd=str(request.validated_data["limit_usd"]),
                window_seconds=request.validated_data["window_seconds"],
            )
        return Response(SpendLimitSerializer(limit).data)

    @extend_schema(
        operation_id="ai_gateway_user_spend_limit_clear",
        request=None,
        responses={200: SpendLimitSerializer, **_WRITE_ERRORS},
    )
    @action(detail=False, methods=["delete"])
    def clear(self, request: Request, **kwargs) -> Response:
        with _spend_limit_errors():
            limit = api.clear_spend_limit(self.team_id, _requesting_user(request))
        return Response(SpendLimitSerializer(limit).data)


def _requesting_user(request: Request | ValidatedRequest) -> User:
    return cast(User, request.user)


@contextmanager
def _spend_limit_errors() -> Iterator[None]:
    try:
        yield
    except api.SpendLimitsUnsupported as exc:
        raise _SpendLimitsUnsupported from exc
    except api.SpendLimitsRejected as exc:
        raise _SpendLimitsRejected from exc
    except api.SpendLimitsUnavailable as exc:
        raise _SpendLimitsUnavailable from exc
