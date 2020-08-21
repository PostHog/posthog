import datetime
import json
from typing import Any, Dict, List

from django.db.models import QuerySet
from rest_framework import exceptions, request, serializers, viewsets
from rest_framework.response import Response

from posthog.constants import DisplayMode
from posthog.decorators import CachedEndpoint, cached_function
from posthog.models import DashboardItem, Funnel


class FunnelBaseSerializer(serializers.HyperlinkedModelSerializer):
    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Funnel:
        request: request.Request = self.context["request"]
        funnel: Funnel = Funnel.objects.create(
            team=request.user.team_set.get(), created_by=request.user, **validated_data
        )
        return funnel


class FunnelStepsSerializer(FunnelBaseSerializer):
    steps = serializers.SerializerMethodField()

    class Meta:
        model = Funnel
        fields = ["id", "name", "deleted", "steps", "filters"]

    def get_steps(self, funnel: Funnel) -> List[Dict[str, Any]]:
        # For some reason, rest_framework executes SerializerMethodField multiple times, causing lots of slow queries.
        # Seems to be a known issue:
        # https://stackoverflow.com/questions/55023511/serializer-being-called-multiple-times-django-python
        if hasattr(funnel, "steps_cache"):
            return []
        funnel.steps_cache = True  # type: ignore

        if self.context.get("cache") is None and (
            self.context["view"].action != "retrieve" or self.context["request"].query_params.get("exclude_count")
        ):
            return []
        return funnel.get_steps()


class FunnelTrendsSerializer(FunnelBaseSerializer):
    trends = serializers.SerializerMethodField()

    class Meta:
        model = Funnel
        fields = ["id", "name", "deleted", "trends", "filters"]

    def get_trends(self, funnel: Funnel) -> List[Dict[str, Any]]:
        from_step = self.context["request"].query_params.get("from_step")
        to_step = self.context["request"].query_params.get("to_step")
        try:
            return funnel.get_trends(from_step=from_step, to_step=to_step)
        except ValueError as e:
            raise exceptions.ValidationError({"detail": str(e)})


class FunnelViewSet(viewsets.ModelViewSet):
    DISPLAY_TO_SERIALIZER = {
        DisplayMode.FUNNEL_TRENDS: FunnelTrendsSerializer,
        DisplayMode.FUNNEL_STEPS: FunnelStepsSerializer,
    }

    queryset = Funnel.objects.all()

    def get_serializer_class(self):
        display = self.request.query_params.get("display", DisplayMode.FUNNEL_STEPS)
        return self.DISPLAY_TO_SERIALIZER.get(display, FunnelStepsSerializer)

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == "list":  # type: ignore
            queryset = queryset.filter(deleted=False)
        return queryset.filter(team=self.request.user.team_set.get())

    def retrieve(self, request: request.Request, pk=None):
        return Response(self._cached_retrieve(request, pk))

    # TODO @cached_function(cache_type=CachedEndpoint.FUNNEL_STEPS)
    def _cached_retrieve(self, request: request.Request, pk=None) -> dict:
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        dashboard_id = request.query_params.get("from_dashboard")
        if dashboard_id:
            DashboardItem.objects.filter(pk=dashboard_id).update(last_refresh=datetime.datetime.now())
        return serializer.data
