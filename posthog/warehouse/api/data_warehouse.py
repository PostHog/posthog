import structlog
from datetime import datetime
from dateutil import parser
from django.db.models import Sum
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

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
        try:
            limit = int(request.query_params.get("limit", "10"))
            limit = max(1, min(limit, 50))
        except ValueError:
            limit = 10

        try:
            offset = int(request.query_params.get("offset", "0"))
            offset = max(0, offset)
        except ValueError:
            offset = 0

        fetch_limit = offset + limit

        external_jobs = list(
            ExternalDataJob.objects.filter(team_id=self.team_id)
            .select_related("schema", "pipeline")
            .order_by("-created_at")[:fetch_limit]
        )
        modeling_jobs = list(
            DataModelingJob.objects.filter(team_id=self.team_id)
            .select_related("saved_query")
            .order_by("-created_at")[:fetch_limit]
        )

        def job_to_activity(job, is_modeling=False):
            base = {
                "id": str(job.id),
                "status": job.status,
                "created_at": job.created_at,
                "workflow_run_id": job.workflow_run_id,
            }

            if is_modeling:
                return {
                    **base,
                    "type": "materialized_view",
                    "name": job.saved_query.name if job.saved_query else None,
                    "rows": job.rows_materialized or 0,
                    "finished_at": job.last_run_at,
                    "latest_error": job.error,
                    "schema_id": None,
                    "source_id": None,
                }
            else:
                return {
                    **base,
                    "type": job.pipeline.source_type if job.pipeline else "external_data_sync",
                    "name": job.schema.name if job.schema else None,
                    "rows": job.rows_synced or 0,
                    "finished_at": job.finished_at,
                    "latest_error": job.latest_error,
                    "schema_id": str(job.schema.id) if job.schema else None,
                    "source_id": str(job.pipeline.id) if job.pipeline else None,
                }

        activities = [job_to_activity(job) for job in external_jobs] + [
            job_to_activity(job, True) for job in modeling_jobs
        ]

        activities.sort(key=lambda x: x["created_at"] or datetime.min, reverse=True)

        return Response(
            {
                "results": activities[offset : offset + limit],
                "count": len(activities[offset : offset + limit]),
            }
        )
