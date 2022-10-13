from typing import Any

from rest_framework import mixins, request, response, viewsets

from posthog.api.routing import StructuredViewSetMixin
from posthog.models.plugin import PluginConfig
from posthog.queries.app_metrics.app_metrics import AppMetricsErrorsQuery, AppMetricsQuery
from posthog.queries.app_metrics.historical_exports import historical_export_metrics, historical_exports_activity
from posthog.queries.app_metrics.serializers import AppMetricsRequestSerializer


class AppMetricsViewSet(StructuredViewSetMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = PluginConfig.objects.all()

    def retrieve(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        plugin_config = self.get_object()

        filter = AppMetricsRequestSerializer(data=request.query_params)
        filter.is_valid(raise_exception=True)

        metric_results = AppMetricsQuery(self.team, plugin_config.pk, filter).run()
        errors = AppMetricsErrorsQuery(self.team, plugin_config.pk, filter).run()
        return response.Response({"metrics": metric_results, "errors": errors})


class HistoricalExportsAppMetricsViewSet(
    StructuredViewSetMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.ViewSet
):
    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        return response.Response(
            {
                "results": historical_exports_activity(
                    team_id=self.parents_query_dict["team_id"],
                    plugin_config_id=self.parents_query_dict["plugin_config_id"],
                )
            }
        )

    def retrieve(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        job_id = kwargs["pk"]
        plugin_config_id = self.parents_query_dict["plugin_config_id"]
        return response.Response(historical_export_metrics(self.team, plugin_config_id, job_id))
