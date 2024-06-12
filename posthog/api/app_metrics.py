import datetime as dt
import uuid
from typing import Any

from django.db.models import Q, Sum
from django.db.models.functions import Coalesce, TruncDay
from rest_framework import mixins, request, response, viewsets
from rest_framework.decorators import action

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import BatchExportRun
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
from posthog.utils import relative_date_parse


class AppMetricsViewSet(TeamAndOrgViewSetMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    scope_object = "plugin"
    queryset = PluginConfig.objects.all()

    def retrieve(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        try:
            rows = self.get_batch_export_runs_app_metrics_queryset(batch_export_id=kwargs["pk"])

            dates = [row["dates"].strftime("%Y-%m-%d") for row in rows]
            successes = [row["successes"] for row in rows]
            failures = [row["failures"] for row in rows]
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
        """Use the Django ORM to fetch app metrics for batch export runs.

        Attempts to (roughly) match the following (much more readable) query:
        ```
        select
            date_trunc('day', last_updated_at) as dates,
            sum(case when status = 'Completed' then coalesce(records_total_count, 0) else 0) as successes,
            sum(case when status != 'Completed' then coalesce(records_total_count, 0) else 0) as failures
        from
            posthog_batchexportrun
        where
            batch_export_id = :batch_export_id
            and last_updated_at between :date_from and :date_to
            and status != 'Running'
        group by
            date_trunc('day', last_updated_at)
        order by
            dates
        ```

        A truncated 'last_updated_at' is used as the grouping date as it reflects when a particular run
        was last updated. It feels easier to explain to users that if they see metrics for today, those
        correspond to runs that happened today, even if the runs themselves exported data from a year ago
        (because it was a backfill).

        Raises:
            ValueError: If provided 'batch_export_id' is not a valid UUID.
        """
        batch_export_uuid = uuid.UUID(batch_export_id)

        after = self.request.GET.get("date_from", "-30d")
        before = self.request.GET.get("date_to", None)
        after_datetime = relative_date_parse(after, self.team.timezone_info)
        before_datetime = (
            relative_date_parse(before, self.team.timezone_info) if before else dt.datetime.now(dt.timezone.utc)
        )
        date_range = (after_datetime, before_datetime)
        return (
            BatchExportRun.objects.filter(batch_export_id=batch_export_uuid, last_updated_at__range=date_range)
            .annotate(dates=TruncDay("last_updated_at"))
            .values("dates")
            .annotate(
                successes=Sum(
                    Coalesce("records_total_count", 0), filter=Q(status=BatchExportRun.Status.COMPLETED), default=0
                ),
                failures=Sum(
                    Coalesce("records_total_count", 0), filter=~Q(status=BatchExportRun.Status.COMPLETED), default=0
                ),
            )
            .order_by("dates")
            .all()
        )


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
