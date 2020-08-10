import datetime
import json
from typing import Any, Dict, List

from django.core.cache import cache
from django.db.models import QuerySet
from rest_framework import request, serializers, viewsets
from rest_framework.response import Response

from posthog.celery import update_cache_item_task
from posthog.decorators import FUNNEL_ENDPOINT, cached_function
from posthog.models import DashboardItem, Funnel
from posthog.utils import generate_cache_key


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
        request = self.context["request"]
        funnel = Funnel.objects.create(team=request.user.team_set.get(), created_by=request.user, **validated_data)
        return funnel


class FunnelViewSet(viewsets.ModelViewSet):
    queryset = Funnel.objects.all()
    serializer_class = FunnelSerializer

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == "list":  # type: ignore
            queryset = queryset.filter(deleted=False)
        return queryset.filter(team=self.request.user.team_set.get())

    def retrieve(self, request, pk=None):
        data = self._retrieve(request, pk)
        return Response(data)

    def _retrieve(self, request, pk=None) -> dict:
        team = request.user.team_set.get()
        refresh = request.GET.get("refresh", None)
        dashboard_id = request.GET.get("from_dashboard", None)

        cache_key = generate_cache_key("funnel_{}_{}".format(pk, team.pk))
        payload = {"funnel_id": pk, "team_id": team.pk}
        result = {"loading": True}

        if refresh:
            cache.delete(cache_key)
        else:
            cached_result = cache.get(cache_key)
            if cached_result:
                return cached_result["result"]

        update_cache_item_task.delay(cache_key, FUNNEL_ENDPOINT, payload)

        if dashboard_id:
            DashboardItem.objects.filter(pk=dashboard_id).update(last_refresh=datetime.datetime.now())

        return result
