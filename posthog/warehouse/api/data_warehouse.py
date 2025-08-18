import structlog
from dateutil import parser
from django.db.models import Sum
from django.db import connection
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from typing import TypedDict, Optional

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.warehouse.models import ExternalDataJob
from posthog.warehouse.models.data_modeling_job import DataModelingJob
from ee.billing.billing_manager import BillingManager
from posthog.cloud_utils import get_cached_instance_license

logger = structlog.get_logger(__name__)


class DataWarehouseViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """
    API endpoints for data warehouse aggregate statistics and operations.
    """

    scope_object = "INTERNAL"

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

        try:
            billing_manager = BillingManager(get_cached_instance_license())
            org_billing = billing_manager.get_billing(organization=self.team.organization)

            if org_billing and org_billing.get("billing_period"):
                billing_period = org_billing["billing_period"]
                billing_period_start = parser.parse(billing_period["current_period_start"])
                billing_period_end = parser.parse(billing_period["current_period_end"])
                billing_interval = billing_period.get("interval", "month")

                usage_summary = org_billing.get("usage_summary", {})
                billing_tracked_rows = usage_summary.get("rows_synced", {}).get("usage", 0)
                billing_available = True

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
                "materialized_rows_in_billing_period": materialized_rows,
                "total_rows": rows_synced,
                "tracked_billing_rows": billing_tracked_rows,
                "pending_billing_rows": pending_billing_rows,
            },
        )

    @action(methods=["GET"], detail=False)
    def recent_activity(self, request: Request, **kwargs) -> Response:
        class DataWarehouseActivityRow(TypedDict):
            id: str
            type: str
            name: Optional[str]
            status: str
            rows: int
            created_at: str
            finished_at: Optional[str]
            latest_error: Optional[str]
            workflow_run_id: Optional[str]

        limit = min(int(request.GET.get("limit", 50)), 250)
        offset = max(int(request.GET.get("offset", 0)), 0)

        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH external_jobs AS (
                    SELECT edj.id, 'Data sync' as type, eds.name, edj.status,
                           COALESCE(edj.rows_synced, 0) as rows, edj.created_at,
                           edj.finished_at, edj.latest_error, edj.workflow_run_id
                    FROM posthog_externaldatajob edj
                    LEFT JOIN posthog_externaldataschema eds ON edj.schema_id = eds.id
                    WHERE edj.team_id = %s
                ),
                modeling_jobs AS (
                    SELECT dmj.id, 'Materialized view' as type, dwsq.name, dmj.status,
                           COALESCE(dmj.rows_materialized, 0) as rows, dmj.created_at,
                           dmj.last_run_at, dmj.error, dmj.workflow_run_id
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
            results = [dict(zip(columns, row)) for row in cursor.fetchall()]
            has_more = len(results) > limit

            return Response(
                {
                    "results": results[:limit],
                    "count": len(results[:limit]),
                    "has_more": has_more,
                    "pagination": {"next_offset": offset + limit if has_more else None},
                }
            )
