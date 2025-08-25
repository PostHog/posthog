from django.db import connection
from django.db.models import Sum

import structlog
from typing import Any, Optional
from dateutil import parser
from django.db.models import Sum
from django.db.models.functions import TruncDate
from django.db import connection
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.cloud_utils import get_cached_instance_license
from posthog.warehouse.models import ExternalDataJob, ExternalDataSource
from posthog.warehouse.models.data_modeling_job import DataModelingJob

from ee.billing.billing_manager import BillingManager

logger = structlog.get_logger(__name__)


class DataWarehouseViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """
    API endpoints for data warehouse aggregate statistics and operations.
    """

    scope_object = "INTERNAL"

    def _get_billing_period(self) -> tuple[bool, Optional[Any], Optional[Any]]:
        """
        Helper method to retrieve billing period information.
        Returns: (billing_available, billing_period_start, billing_period_end)
        """
        try:
            billing_manager = BillingManager(get_cached_instance_license())
            org_billing = billing_manager.get_billing(organization=self.team.organization)

            if org_billing and org_billing.get("billing_period"):
                billing_period = org_billing["billing_period"]
                billing_period_start = parser.parse(billing_period["current_period_start"])
                billing_period_end = parser.parse(billing_period["current_period_end"])
                return True, billing_period_start, billing_period_end
            else:
                return False, None, None
        except Exception as e:
            logger.exception("Error retrieving billing period", exc_info=e)
            raise

    @action(methods=["GET"], detail=False)
    def total_rows_stats(self, request: Request, **kwargs) -> Response:
        """
        Returns aggregated statistics for the data warehouse total rows processed within the current billing period.
        Used by the frontend data warehouse scene to display usage information.
        """
        billing_interval = ""
        billing_period_start = None
        billing_period_end = None
        billing_tracked_rows = 0
        materialized_rows = 0
        pending_billing_rows = 0
        rows_synced = 0
        billing_available = False
        breakdown_of_rows_by_source = {}
        sources = ExternalDataSource.objects.filter(team_id=self.team_id, deleted=False)

        try:
            billing_available, billing_period_start, billing_period_end = self._get_billing_period()

            if billing_available:
                billing_manager = BillingManager(get_cached_instance_license())
                org_billing = billing_manager.get_billing(organization=self.team.organization)
                billing_period = org_billing["billing_period"]
                billing_interval = billing_period.get("interval", "month")

                usage_summary = org_billing.get("usage_summary", {})
                billing_tracked_rows = usage_summary.get("rows_synced", {}).get("usage", 0)

                all_external_jobs = ExternalDataJob.objects.filter(
                    team_id=self.team_id,
                    created_at__gte=billing_period_start,
                    created_at__lt=billing_period_end,
                    billable=True,
                )
                total_db_rows = all_external_jobs.aggregate(total=Sum("rows_synced"))["total"] or 0

                pending_billing_rows = max(0, total_db_rows - billing_tracked_rows)

                rows_synced = billing_tracked_rows + pending_billing_rows

                data_modeling_jobs = DataModelingJob.objects.filter(
                    team_id=self.team_id,
                    created_at__gte=billing_period_start,
                    created_at__lt=billing_period_end,
                )
                materialized_rows = data_modeling_jobs.aggregate(total=Sum("rows_materialized"))["total"] or 0

                for source in sources:
                    total_rows = (
                        ExternalDataJob.objects.filter(
                            pipeline=source,
                            created_at__gte=billing_period_start,
                            created_at__lt=billing_period_end,
                        ).aggregate(total=Sum("rows_synced"))["total"]
                        or 0
                    )

                    breakdown_of_rows_by_source[str(source.id)] = total_rows

            else:
                logger.info("No billing period information available, using defaults")

        except Exception as e:
            logger.exception("There was an error retrieving billing information", exc_info=e)
            return Response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                data={"error": "An error occurred retrieving billing information"},
            )

        return Response(
            status=status.HTTP_200_OK,
            data={
                "billing_available": billing_available,
                "billing_interval": billing_interval,
                "billing_period_end": billing_period_end,
                "billing_period_start": billing_period_start,
                "breakdown_of_rows_by_source": breakdown_of_rows_by_source,
                "materialized_rows_in_billing_period": materialized_rows,
                "total_rows": rows_synced,
                "tracked_billing_rows": billing_tracked_rows,
                "pending_billing_rows": pending_billing_rows,
            },
        )

    @action(methods=["GET"], detail=False)
    def recent_activity(self, request: Request, **kwargs) -> Response:
        DEFAULT_LIMIT = 20
        MAX_LIMIT = 50

        try:
            limit = min(int(request.GET.get("limit", DEFAULT_LIMIT)), MAX_LIMIT)
            offset = max(int(request.GET.get("offset", 0)), 0)
        except (ValueError, TypeError):
            return Response({"error": "Invalid limit or offset parameter"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    WITH external_jobs AS (
                        SELECT edj.id, edsrc.source_type as type, eds.name, edj.status,
                               COALESCE(edj.rows_synced, 0) as rows, edj.created_at,
                               edj.finished_at, edj.latest_error, edj.workflow_run_id
                        FROM posthog_externaldatajob edj
                        LEFT JOIN posthog_externaldataschema eds ON edj.schema_id = eds.id
                        LEFT JOIN posthog_externaldatasource edsrc ON eds.source_id = edsrc.id
                        WHERE edj.team_id = %s
                    ),
                    modeling_jobs AS (
                        SELECT dmj.id, 'Materialized view' as type, dwsq.name, dmj.status,
                               COALESCE(dmj.rows_materialized, 0) as rows, dmj.created_at,
                               dmj.last_run_at as finished_at, dmj.error as latest_error, dmj.workflow_run_id
                        FROM posthog_datamodelingjob dmj
                        LEFT JOIN posthog_datawarehousesavedquery dwsq ON dmj.saved_query_id = dwsq.id
                        WHERE dmj.team_id = %s
                    )
                    SELECT * FROM external_jobs
                    UNION ALL
                    SELECT * FROM modeling_jobs
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                """,
                    [self.team_id, self.team_id, limit + 1, offset],
                )

                columns = [col[0] for col in cursor.description]
                # Fetch with explicit limit to prevent OOM
                rows = cursor.fetchmany(limit + 1)
                has_more = len(rows) > limit

                actual_rows = rows[:limit]
                results = [dict(zip(columns, row)) for row in actual_rows]
        except Exception as e:
            logger.exception("Database error in recent_activity", exc_info=e)
            return Response({"error": "Database error occurred"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        next_url = None
        prev_url = None
        if has_more:
            next_url = f"?limit={limit}&offset={offset + limit}"
        if offset > 0:
            prev_url = f"?limit={limit}&offset={max(0, offset - limit)}"

        return Response(
            {
                "results": results,
                "next": next_url,
                "previous": prev_url,
            }
        )

    @action(methods=["GET"], detail=False)
    def breakdown_of_rows_synced_by_day_in_billing_period(self, request: Request, **kwargs) -> Response:
        """
        Returns daily breakdown of rows synced within the current billing period.
        Used by the frontend data warehouse scene to display sync activity trends.
        """
        log = structlog.get_logger()
        billing_period_start = billing_period_end = None
        billing_available = False
        breakdown_of_rows_by_day = []

        try:
            billing_available, billing_period_start, billing_period_end = self._get_billing_period()

            if billing_available:
                base_external_data_jobs = ExternalDataJob.objects.filter(
                    team_id=self.team_id,
                    created_at__gte=billing_period_start,
                    created_at__lt=billing_period_end,
                    status="Completed",
                    rows_synced__gt=0,
                )

                daily_totals = (
                    base_external_data_jobs.annotate(sync_date=TruncDate("created_at"))
                    .values("sync_date")
                    .annotate(total_rows_synced=Sum("rows_synced"))
                    .order_by("sync_date")
                )

                per_job = (
                    base_external_data_jobs.annotate(sync_date=TruncDate("created_at"))
                    .values(
                        "id",
                        "sync_date",
                        "rows_synced",
                        "status",
                        "created_at",
                        "finished_at",
                        "workflow_run_id",
                        "schema__name",
                        "pipeline__source_type",
                    )
                    .order_by("created_at")
                )

                jobs_by_date: dict[str, list[dict[str, Any]]] = {}
                for j in per_job:
                    key = j["sync_date"].strftime("%Y-%m-%d")
                    jobs_by_date.setdefault(key, []).append(
                        {
                            "id": j["id"],
                            "rows_synced": j["rows_synced"],
                            "status": j["status"],
                            "created_at": j["created_at"].isoformat() if j["created_at"] else None,
                            "finished_at": j["finished_at"].isoformat() if j["finished_at"] else None,
                            "workflow_run_id": j["workflow_run_id"],
                            "schema_name": j["schema__name"],
                            "source_type": j["pipeline__source_type"],
                        }
                    )

                breakdown_of_rows_by_day = [
                    {
                        "date": row["sync_date"].strftime("%Y-%m-%d"),
                        "rows_synced": row["total_rows_synced"] or 0,
                        "runs": jobs_by_date.get(row["sync_date"].strftime("%Y-%m-%d"), []),
                    }
                    for row in daily_totals
                ]
            else:
                log.info("no_billing_period_for_daily_breakdown")

        except Exception as e:
            log.exception("daily_breakdown_error", exc_info=e)
            return Response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                data={"error": "An error occurred retrieving daily breakdown"},
            )

        return Response(
            status=status.HTTP_200_OK,
            data={
                "billing_available": billing_available,
                "billing_period_start": billing_period_start.isoformat() if billing_period_start else None,
                "billing_period_end": billing_period_end.isoformat() if billing_period_end else None,
                "breakdown_of_rows_by_day": breakdown_of_rows_by_day,
            },
        )
