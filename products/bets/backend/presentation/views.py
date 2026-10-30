from typing import cast

from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle

from ..facade import api
from .serializers import (
    BetsActivitySerializer,
    BetsDetailSerializer,
    BetsGuardrailOptionSerializer,
    BetsGuardrailRequestSerializer,
    BetsIdeaSerializer,
    BetsMeasureRequestSerializer,
    BetsMeasureSearchSerializer,
    BetsMetricPreviewQuerySerializer,
    BetsMetricSerializer,
    BetsOverviewSerializer,
    BetsSettingsSerializer,
    BetsSettingsWriteSerializer,
    BetsStatusSerializer,
    BetsWorkActionSerializer,
    BetsWriteSerializer,
)


class BetsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"
    serializer_class = BetsDetailSerializer
    pagination_class = None
    lookup_field = "id"
    lookup_value_regex = "[0-9a-f-]{36}"

    def initial(self, request: Request, *args: object, **kwargs: object) -> None:
        super().initial(request, *args, **kwargs)
        api.authorize(self.team, cast(User, request.user), write=request.method not in ("GET", "HEAD", "OPTIONS"))

    @property
    def user(self) -> User:
        return cast(User, self.request.user)

    @extend_schema(responses=BetsOverviewSerializer(many=False))
    def list(self, request: Request, **kwargs: object) -> Response:
        return Response(BetsOverviewSerializer(api.overview(self.team, self.user)).data)

    @extend_schema(request=BetsWriteSerializer, responses={201: BetsDetailSerializer})
    def create(self, request: Request, **kwargs: object) -> Response:
        serializer = BetsWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            BetsDetailSerializer(api.create(self.team, self.user, serializer.validated_data)).data, status=201
        )

    @extend_schema(responses=BetsDetailSerializer)
    def retrieve(self, request: Request, id: str, **kwargs: object) -> Response:
        return Response(BetsDetailSerializer(api.detail(self.team, self.user, id)).data)

    @extend_schema(responses=BetsActivitySerializer(many=True))
    @action(detail=True, methods=["get"])
    def activity(self, request: Request, id: str, **kwargs: object) -> Response:
        return Response(BetsActivitySerializer(api.activity(self.team, self.user, id), many=True).data)

    @extend_schema(request=BetsWriteSerializer, responses=BetsDetailSerializer)
    def partial_update(self, request: Request, id: str, **kwargs: object) -> Response:
        existing = api.detail(self.team, self.user, id)
        serializer = BetsWriteSerializer(
            data=request.data,
            partial=True,
            context={"primary_insight": existing["goal_insight"], "secondary_metrics": existing["secondary_metrics"]},
        )
        serializer.is_valid(raise_exception=True)
        return Response(BetsDetailSerializer(api.update(self.team, self.user, id, serializer.validated_data)).data)

    @extend_schema(request=BetsStatusSerializer, responses=BetsDetailSerializer)
    @action(detail=True, methods=["post"], url_path="status")
    def set_status(self, request: Request, id: str, **kwargs: object) -> Response:
        serializer = BetsStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            BetsDetailSerializer(api.change_status(self.team, self.user, id, serializer.validated_data["status"])).data
        )

    @extend_schema(request=BetsWorkActionSerializer, responses=BetsDetailSerializer)
    @action(detail=True, methods=["post"])
    def work(self, request: Request, id: str, **kwargs: object) -> Response:
        serializer = BetsWorkActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        return Response(
            BetsDetailSerializer(
                api.work(self.team, self.user, id, data["work_id"], data["action"], data["reason"], data.get("plan"))
            ).data
        )

    @extend_schema(request=BetsIdeaSerializer, responses=BetsDetailSerializer)
    @action(detail=True, methods=["post"])
    def ideas(self, request: Request, id: str, **kwargs: object) -> Response:
        serializer = BetsIdeaSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            BetsDetailSerializer(api.add_idea(self.team, self.user, id, serializer.validated_data["title"])).data
        )

    @extend_schema(parameters=[BetsMetricPreviewQuerySerializer], responses=BetsMetricSerializer)
    @action(detail=False, methods=["get"], url_path="metric_preview")
    def metric_preview(self, request: Request, **kwargs: object) -> Response:
        serializer = BetsMetricPreviewQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        preview = api.metric_preview(self.team, self.user, serializer.validated_data["insight"])
        return Response(BetsMetricSerializer(preview).data)

    @extend_schema(request=BetsMeasureRequestSerializer, responses=BetsMeasureSearchSerializer)
    @action(
        detail=False,
        methods=["post"],
        url_path="measures",
        throttle_classes=[AIBurstRateThrottle, AISustainedRateThrottle],
    )
    def measures(self, request: Request, **kwargs: object) -> Response:
        serializer = BetsMeasureRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        search = api.measure_options(self.team, self.user, serializer.validated_data["goal"])
        return Response(BetsMeasureSearchSerializer(search).data)

    @extend_schema(request=BetsGuardrailRequestSerializer, responses=BetsGuardrailOptionSerializer(many=True))
    @action(
        detail=False,
        methods=["post"],
        url_path="guardrails",
        throttle_classes=[AIBurstRateThrottle, AISustainedRateThrottle],
    )
    def guardrails(self, request: Request, **kwargs: object) -> Response:
        serializer = BetsGuardrailRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        options = api.guardrail_options(
            self.team, self.user, serializer.validated_data["goal"], serializer.validated_data["measure"]
        )
        return Response(BetsGuardrailOptionSerializer(options, many=True).data)

    @extend_schema(request=BetsSettingsWriteSerializer, responses=BetsSettingsSerializer)
    @action(detail=False, methods=["get", "patch"], url_path="settings")
    def workspace_settings(self, request: Request, **kwargs: object) -> Response:
        if request.method == "GET":
            return Response(BetsSettingsSerializer(api.settings(self.team, self.user)).data)
        serializer = BetsSettingsWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return Response(
            BetsSettingsSerializer(api.update_settings(self.team, self.user, serializer.validated_data)).data
        )
