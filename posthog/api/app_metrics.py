import datetime as dt
from typing import Any
import uuid
import itertools
import operator

from django.db.models.functions import TruncDay, TruncHour
from django.db.models.functions.datetime import TruncBase
from django.db.models import Count
from rest_framework import mixins, request, response, viewsets
from rest_framework.decorators import action
from posthog.batch_exports.models import BatchExportRun
from posthog.api.routing import StructuredViewSetMixin
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


def query_batch_export_metrics(batch_export_id: uuid.UUID, date_from: str) -> dict[str, Any]:
    """Fetch metrics for batch export matching batch_export_id from given date_from.

    The counts contained in the metrics represent counts of batch export runs, aggregated by the
    date they were created. If these runs are triggered manually, 'created_at' will not match
    'data_interval_end' (i.e. the batch period).
    """
    now = dt.datetime.now(tz=dt.timezone.utc)
    if date_from == "-30d":
        created_at_date_from = now - dt.timedelta(days=30)
        trunc_func: type[TruncBase] = TruncDay
        datetime_format = "%Y-%m-%d"

    elif date_from == "-7d":
        created_at_date_from = now - dt.timedelta(days=7)
        trunc_func = TruncDay
        datetime_format = "%Y-%m-%d"

    else:
        created_at_date_from = now - dt.timedelta(hours=24)
        trunc_func = TruncHour
        datetime_format = "%Y-%m-%d %H:%M:%S"

    runs_query_set = (
        BatchExportRun.objects.filter(
            batch_export_id=batch_export_id,
            created_at__gte=created_at_date_from,
        )
        .annotate(aggregate_date=trunc_func("created_at"))
        .values("aggregate_date", "status")
        .annotate(count=Count("*"))
        .order_by("aggregate_date", "status")
    )

    dates = []
    successes = []
    failures = []
    totals = {"successes": 0, "successes_on_retry": 0, "failures": 0}

    for aggregate_date, group in itertools.groupby(runs_query_set, operator.itemgetter("aggregate_date")):
        dates.append(aggregate_date.strftime(datetime_format))

        for row in group:
            if row["status"] == "Completed":
                successes.append(row["count"])
                totals["successes"] += row["count"]

            elif row["status"] == "Failed":
                failures.append(row["count"])
                totals["failures"] += row["count"]

    return {
        "dates": dates,
        "successes": successes,
        "successes_on_retry": [],
        "failures": failures,
        "totals": totals,
    }


class AppMetricsViewSet(StructuredViewSetMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = PluginConfig.objects.all()

    def retrieve(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        try:
            # probe if we have a valid uuid, and thus are requesting metrics for a batch export
            batch_export_id = uuid.UUID(kwargs["pk"])
        except ValueError:
            pass
        else:
            metrics = query_batch_export_metrics(batch_export_id, date_from=request.query_params["date_from"])
            return response.Response(
                {
                    "metrics": [metrics],
                    "errors": None,
                }
            )

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
    StructuredViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.ViewSet,
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
