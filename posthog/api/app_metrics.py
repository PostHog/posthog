from typing import Any

from rest_framework import mixins, request, response, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import StructuredViewSetMixin
from posthog.models.plugin import PluginConfig
from posthog.queries.app_metrics.app_metrics import AppMetricsErrorDetailsQuery, AppMetricsErrorsQuery, AppMetricsQuery
from posthog.queries.app_metrics.historical_exports import historical_export_metrics, historical_exports_activity
from posthog.queries.app_metrics.serializers import (
    AppMetricsErrorsRequestSerializer,
    AppMetricsRequestSerializer,
    WebhooksMetricsRequestSerializer,
)


class WebhooksViewSet(StructuredViewSetMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        filter = WebhooksMetricsRequestSerializer(data=request.query_params)
        filter.is_valid(raise_exception=True)
        ch_id = filter.validated_data.get("ch_id")
        date_from = filter.validated_data.get("date_from")

        metric_results = AppMetricsQuery(self.team, ch_id, "webhook", date_from).run()
        errors = AppMetricsErrorsQuery(self.team, ch_id, "webhook", date_from).run()
        return response.Response({"metrics": metric_results, "errors": errors})

    @action(methods=["GET"], detail=True)
    def error_details(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        plugin_config = self.get_object()

        filter = AppMetricsErrorsRequestSerializer(data=request.query_params)
        filter.is_valid(raise_exception=True)

        error_details = AppMetricsErrorDetailsQuery(self.team, plugin_config.pk, filter).run()
        return response.Response({"result": error_details})


class AppMetricsViewSet(StructuredViewSetMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = PluginConfig.objects.all()

    def retrieve(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        plugin_config = self.get_object()

        filter = AppMetricsRequestSerializer(data=request.query_params)
        filter.is_valid(raise_exception=True)
        job_id = filter.validated_data.get("job_id")
        category = filter.validated_data.get("category")
        date_from = filter.validated_data.get("date_from")
        date_to = filter.validated_data.get("date_to")

        metric_results = AppMetricsQuery(self.team, plugin_config.pk, category, date_from, date_to, job_id).run()
        errors = AppMetricsErrorsQuery(self.team, plugin_config.pk, category, date_from, date_to, job_id).run()
        return response.Response({"metrics": metric_results, "errors": errors})

    @action(methods=["GET"], detail=True)
    def error_details(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        plugin_config = self.get_object()

        filter = AppMetricsErrorsRequestSerializer(data=request.query_params)
        filter.is_valid(raise_exception=True)
        category = filter.validated_data.get("category")
        error_type = filter.validated_data.get("error_type")
        job_id = filter.validated_data.get("job_id")

        error_details = AppMetricsErrorDetailsQuery(self.team, plugin_config.pk, category, error_type, job_id).run()
        return response.Response({"result": error_details})


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
