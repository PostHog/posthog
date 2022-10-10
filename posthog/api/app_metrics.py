from typing import Any

from rest_framework import mixins, request, response, viewsets

from posthog.api.routing import StructuredViewSetMixin
from posthog.models.plugin import PluginConfig
from posthog.queries.app_metrics.app_metrics import AppMetricsQuery
from posthog.queries.app_metrics.serializers import AppMetricsRequestSerializer


class AppMetricsViewSet(StructuredViewSetMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = PluginConfig.objects.all()

    def retrieve(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        plugin_config = self.get_object()

        filter = AppMetricsRequestSerializer(data=request.query_params)
        filter.is_valid(raise_exception=True)

        results = AppMetricsQuery(self.team, plugin_config.pk, filter).run()
        return response.Response(results)
