import structlog
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

MAX_RECENT_ACTIVITY_RESULTS = 50


class DataWarehouseViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"

    @action(methods=["GET"], detail=False)
    def total_rows_stats(self, request: Request, **kwargs) -> Response:
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
                "billingAvailable": billing_available,
                "billingInterval": billing_interval,
                "billingPeriodEnd": billing_period_end,
                "billingPeriodStart": billing_period_start,
                "materializedRowsInBillingPeriod": materialized_rows,
                "totalRows": rows_synced,
                "trackedBillingRows": billing_tracked_rows,
                "pendingBillingRows": pending_billing_rows,
            },
        )

    @action(methods=["GET"], detail=False)
    def recent_activity(self, request: Request, **kwargs) -> Response:
        try:
            limit = int(request.query_params.get("limit", str(MAX_RECENT_ACTIVITY_RESULTS)))
            if limit < 1:
                limit = MAX_RECENT_ACTIVITY_RESULTS
            else:
                limit = min(limit, MAX_RECENT_ACTIVITY_RESULTS)
        except (ValueError, TypeError):
            limit = MAX_RECENT_ACTIVITY_RESULTS

        external_jobs = ExternalDataJob.objects.filter(team_id=self.team_id).select_related("schema", "pipeline")[
            :limit
        ]
        modeling_jobs = DataModelingJob.objects.filter(team_id=self.team_id).select_related("saved_query")[:limit]

        activities = [
            {
                "id": str(job.id),
                "type": job.pipeline.source_type if job.pipeline else None,
                "name": job.schema.name if job.schema else None,
                "status": job.status,
                "rows": job.rows_synced or 0,
                "created_at": job.created_at,
                "finished_at": job.finished_at,
                "latest_error": job.latest_error,
                "schema_id": str(job.schema.id) if job.schema else None,
                "source_id": str(job.pipeline.id) if job.pipeline else None,
                "workflow_run_id": job.workflow_run_id,
            }
            for job in external_jobs
        ] + [
            {
                "id": str(job.id),
                "type": "materialized_view",
                "name": job.saved_query.name if job.saved_query else None,
                "status": job.status,
                "rows": job.rows_materialized or 0,
                "created_at": job.created_at,
                "finished_at": None,
                "latest_error": job.error,
                "schema_id": None,
                "source_id": None,
                "workflow_run_id": job.workflow_run_id,
            }
            for job in modeling_jobs
        ]

        activities.sort(key=lambda x: x["created_at"], reverse=True)

        return Response(
            {
                "activities": activities[:limit],
                "total_count": len(activities),
                "limit": limit,
            }
        )
