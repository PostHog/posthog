import uuid
import datetime as dt
from typing import Any

from django.db.models import Count, Q
from django.db.models.functions import TruncDay

from rest_framework import mixins, request, response, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models import BatchExportRun
from posthog.models.plugin import PluginConfig
from posthog.queries.app_metrics.app_metrics import AppMetricsErrorDetailsQuery, AppMetricsErrorsQuery, AppMetricsQuery
from posthog.queries.app_metrics.historical_exports import historical_export_metrics, historical_exports_activity
from posthog.queries.app_metrics.serializers import AppMetricsErrorsRequestSerializer, AppMetricsRequestSerializer
from posthog.utils import relative_date_parse


class AppMetricsViewSet(TeamAndOrgViewSetMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    scope_object = "plugin"
    queryset = PluginConfig.objects.all()

    def retrieve(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        try:
            dates, successes, failures = self.get_batch_export_runs_app_metrics_queryset(batch_export_id=kwargs["pk"])

            return response.Response(
                {
                    "metrics": {
                        "dates": dates,
                        "successes": successes,
                        "successes_on_retry": [0] * len(dates),
                        "failures": failures,
                        "totals": {
                            "successes": sum(successes),
                            "successes_on_retry": 0,
                            "failures": sum(failures),
                        },
                    },
                    "errors": None,
                }
            )
        except ValueError:
            pass

        filter = AppMetricsRequestSerializer(data=request.query_params)
        filter.is_valid(raise_exception=True)

        if "hog-" in kwargs["pk"]:
            # TODO: Make app metrics work with string IDs
            metric_results = {
                "dates": [],
                "successes": [],
                "successes_on_retry": [],
                "failures": [],
                "totals": {"successes": 0, "successes_on_retry": 0, "failures": 0},
            }
            errors = []
        else:
            metric_results = AppMetricsQuery(self.team, kwargs["pk"], filter).run()
            errors = AppMetricsErrorsQuery(self.team, kwargs["pk"], filter).run()
        return response.Response({"metrics": metric_results, "errors": errors})

    @action(methods=["GET"], detail=True)
    def error_details(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        filter = AppMetricsErrorsRequestSerializer(data=request.query_params)
        filter.is_valid(raise_exception=True)

        error_details = AppMetricsErrorDetailsQuery(self.team, kwargs["pk"], filter).run()
        return response.Response({"result": error_details})

    def get_batch_export_runs_app_metrics_queryset(self, batch_export_id: str):
        """Use the Django ORM and ClickHouse to fetch app metrics for batch export runs.

        Raises:
            ValueError: If provided 'batch_export_id' is not a valid UUID.
        """
        batch_export_uuid = uuid.UUID(batch_export_id)

        after = self.request.GET.get("date_from", "-30d")
        before = self.request.GET.get("date_to", None)
        after_datetime = relative_date_parse(after, self.team.timezone_info)
        before_datetime = relative_date_parse(before, self.team.timezone_info) if before else dt.datetime.now(dt.UTC)
        date_range = (after_datetime, before_datetime)
        runs = (
            BatchExportRun.objects.select_related("batch_export__destination")
            .filter(
                batch_export_id=batch_export_uuid,
                last_updated_at__range=date_range,
                status__in=(
                    BatchExportRun.Status.COMPLETED,
                    BatchExportRun.Status.FAILED,
                    BatchExportRun.Status.FAILED_RETRYABLE,
                ),
            )
            .annotate(day=TruncDay("last_updated_at"))
            .values("day")
            .annotate(
                successes=Count("data_interval_end", filter=Q(status=BatchExportRun.Status.COMPLETED)),
                failures=Count(
                    "data_interval_end",
                    filter=(Q(status=BatchExportRun.Status.FAILED) | Q(status=BatchExportRun.Status.FAILED_RETRYABLE)),
                ),
            )
            .order_by("day")
            .all()
        )

        dates = []
        successes = []
        failures = []
        for run in runs:
            dates.append(run["day"].strftime("%Y-%m-%d"))
            successes.append(run["successes"])
            failures.append(run["failures"])

        return dates, successes, failures


class HistoricalExportsAppMetricsViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.ViewSet,
):
    scope_object = "plugin"

    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        return response.Response(
            {
                "results": historical_exports_activity(
                    team_id=self.team_id,
                    plugin_config_id=self.parents_query_dict["plugin_config_id"],
                )
            }
        )

    def retrieve(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        job_id = kwargs["pk"]
        plugin_config_id = self.parents_query_dict["plugin_config_id"]
        return response.Response(historical_export_metrics(self.team, plugin_config_id, job_id))
