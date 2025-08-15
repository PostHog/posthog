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

# TODO: review this limit on standup. Should there be a limit, or should it be from the frontend?
MAX_RECENT_ACTIVITY_RESULTS = 50


class DataWarehouseViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """
    API endpoints for data warehouse aggregate statistics and operations.
    """

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
                try:
                    billing_period_start = parser.parse(billing_period["current_period_start"])
                    billing_period_end = parser.parse(billing_period["current_period_end"])
                except (ValueError, TypeError, KeyError) as e:
                    logger.warning("Failed to parse billing period dates", exc_info=e)
                    billing_period_start = None
                    billing_period_end = None
                billing_interval = billing_period.get("interval", "month")

                usage_summary = org_billing.get("usage_summary", {})
                if isinstance(usage_summary, dict) and "rows_synced" in usage_summary:
                    rows_synced_data = usage_summary["rows_synced"]
                    if isinstance(rows_synced_data, dict):
                        billing_tracked_rows = rows_synced_data.get("usage", 0)
                    else:
                        billing_tracked_rows = 0
                else:
                    billing_tracked_rows = 0
                billing_available = True

                # Only query database if we have valid billing period dates
                if billing_period_start and billing_period_end:
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
                    # Fallback when billing period dates are invalid
                    rows_synced = billing_tracked_rows
                    materialized_rows = 0
                    pending_billing_rows = 0

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
            limit_param = request.query_params.get("limit", str(MAX_RECENT_ACTIVITY_RESULTS))
            limit = int(limit_param)
            if limit <= 0 or limit > MAX_RECENT_ACTIVITY_RESULTS:
                limit = MAX_RECENT_ACTIVITY_RESULTS
        except (ValueError, TypeError, OverflowError):
            limit = MAX_RECENT_ACTIVITY_RESULTS

        external_jobs = (
            ExternalDataJob.objects.filter(team_id=self.team_id)
            .select_related("schema", "pipeline")
            .order_by("-created_at")[:limit]
        )

        modeling_jobs = (
            DataModelingJob.objects.filter(team_id=self.team_id)
            .select_related("saved_query")
            .order_by("-created_at")[:limit]
        )

        def safe_serialize_external_job(job):
            """Safely serialize ExternalDataJob with proper null checks."""
            try:
                return {
                    "id": str(job.id) if job.id else "unknown",
                    "type": job.pipeline.source_type if job.pipeline else None,
                    "name": job.schema.name if job.schema else None,
                    "status": job.status or "Unknown",
                    "rows": job.rows_synced or 0,
                    "created_at": job.created_at,
                    "finished_at": job.finished_at,
                    "latest_error": job.latest_error,
                    "schema_id": str(job.schema.id) if job.schema and job.schema.id else None,
                    "source_id": str(job.pipeline.id) if job.pipeline and job.pipeline.id else None,
                    "workflow_run_id": job.workflow_run_id,
                }
            except Exception as e:
                logger.warning(f"Failed to serialize external job {getattr(job, 'id', 'unknown')}", exc_info=e)
                return None

        def safe_serialize_modeling_job(job):
            """Safely serialize DataModelingJob with proper null checks."""
            try:
                return {
                    "id": str(job.id) if job.id else "unknown",
                    "type": "materialized_view",
                    "name": job.saved_query.name if job.saved_query else None,
                    "status": job.status or "Unknown",
                    "rows": job.rows_materialized or 0,
                    "created_at": job.created_at,
                    "finished_at": None,  # DataModelingJob doesn't have finished_at field
                    "latest_error": job.error,
                    "schema_id": None,
                    "source_id": None,
                    "workflow_run_id": job.workflow_run_id,
                }
            except Exception as e:
                logger.warning(f"Failed to serialize modeling job {getattr(job, 'id', 'unknown')}", exc_info=e)
                return None

        # Serialize jobs with error handling
        external_activities = [safe_serialize_external_job(job) for job in external_jobs]
        modeling_activities = [safe_serialize_modeling_job(job) for job in modeling_jobs]

        # Filter out any None results from failed serialization
        activities = [activity for activity in external_activities + modeling_activities if activity is not None]

        activities.sort(key=lambda x: x["created_at"], reverse=True)
        activities = activities[:limit]

        return Response(
            status=status.HTTP_200_OK,
            data={
                "activities": activities,
                "total_count": len(activities),
                "limit": limit,
            },
        )
