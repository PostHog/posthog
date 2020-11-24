from typing import Any, Dict, List

from django.db.models import QuerySet
from django.utils import timezone
from rest_framework import request, serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.routing import StructuredViewSetMixin
from posthog.decorators import CacheType, cached_function
from posthog.models import DashboardItem, Funnel
from posthog.permissions import ProjectMembershipNecessaryPermissions


class FunnelSerializer(serializers.HyperlinkedModelSerializer):
    steps = serializers.SerializerMethodField()

    class Meta:
        model = Funnel
        fields = ["id", "name", "deleted", "steps", "filters"]

    def get_steps(self, funnel: Funnel) -> List[Dict[str, Any]]:
        # for some reason, rest_framework executes SerializerMethodField multiple times,
        # causing lots of slow queries.
        # Seems a known issue: https://stackoverflow.com/questions/55023511/serializer-being-called-multiple-times-django-python
        if hasattr(funnel, "steps_cache"):
            return []
        funnel.steps_cache = True  # type: ignore

        if self.context.get("cache", None) is None and (
            self.context["view"].action != "retrieve" or self.context["request"].GET.get("exclude_count")
        ):
            return []
        return funnel.get_steps()

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Funnel:
        funnel = Funnel.objects.create(
            team_id=self.context["team_id"], created_by=self.context["request"].user, **validated_data
        )
        return funnel


class FunnelViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    legacy_team_compatibility = True  # to be moved to a separate Legacy*ViewSet Class

    queryset = Funnel.objects.all()
    serializer_class = FunnelSerializer
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions]

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == "list":
            queryset = queryset.filter(deleted=False)
        return queryset

    def retrieve(self, request, pk=None, **kwargs):
        data = self._retrieve(request, pk)
        return Response(data)

    @cached_function(cache_type=CacheType.FUNNEL)
    def _retrieve(self, request, pk=None) -> dict:
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        dashboard_id = request.GET.get("from_dashboard", None)
        if dashboard_id:
            DashboardItem.objects.filter(pk=dashboard_id).update(last_refresh=timezone.now())
        return serializer.data
