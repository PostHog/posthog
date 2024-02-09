from typing import Any
import uuid

from rest_framework import mixins, request, response, viewsets
from rest_framework.decorators import action

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.plugin import PluginConfig
from posthog.queries.app_metrics.app_metrics import (
    AppMetricsErrorDetailsQuery,
    AppMetricsErrorsQuery,
    AppMetricsQuery,
)
from posthog.queries.app_metrics.historical_exports import (
    historical_export_metrics,
    historical_exports_activity,
)
from posthog.queries.app_metrics.serializers import (
    AppMetricsErrorsRequestSerializer,
    AppMetricsRequestSerializer,
)


class AppMetricsViewSet(TeamAndOrgViewSetMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    base_scope = "plugin"
    queryset = PluginConfig.objects.all()

    def retrieve(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        try:
            # probe if we have a valid uuid, and thus are requesting metrics for a batch export
            uuid.UUID(kwargs["pk"])
            return response.Response(
                {
                    "metrics": [
                        {
                            "dates": [
                                "2024-01-04",
                                "2024-01-05",
                                "2024-01-06",
                                "2024-01-07",
                                "2024-01-08",
                                "2024-01-09",
                                "2024-01-10",
                                "2024-01-11",
                            ],
                            "successes": [0, 0, 0, 0, 0, 0, 9379, 6237],
                            "successes_on_retry": [0, 0, 0, 0, 0, 0, 0, 0],
                            "failures": [0, 0, 0, 0, 0, 0, 665, 0],
                            "totals": {"successes": 15616, "successes_on_retry": 0, "failures": 665},
                        }
                    ],
                    "errors": None,
                }
            )
        except ValueError:
            pass

        plugin_config = self.get_object()

        filter = AppMetricsRequestSerializer(data=request.query_params)
        filter.is_valid(raise_exception=True)

        metric_results = AppMetricsQuery(self.team, plugin_config.pk, filter).run()
        errors = AppMetricsErrorsQuery(self.team, plugin_config.pk, filter).run()
        return response.Response({"metrics": metric_results, "errors": errors})

    @action(methods=["GET"], detail=True)
    def error_details(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        plugin_config = self.get_object()

        filter = AppMetricsErrorsRequestSerializer(data=request.query_params)
        filter.is_valid(raise_exception=True)

        error_details = AppMetricsErrorDetailsQuery(self.team, plugin_config.pk, filter).run()
        return response.Response({"result": error_details})


class HistoricalExportsAppMetricsViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.ViewSet,
):
    base_scope = "plugin"

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
