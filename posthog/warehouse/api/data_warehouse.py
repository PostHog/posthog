from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import connection
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate, TruncHour

import structlog
from dateutil import parser
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
    def job_stats(self, request: Request, **kwargs) -> Response:
        """
        Returns success and failed job statistics for the last 1, 7, or 30 days.
        Query parameter 'days' can be 1, 7, or 30 (default: 7).
        """

        # TODO: Will want to cache this data to not spam PG
        try:
            days = int(request.GET.get("days", 7))
            if days not in [1, 7, 30]:
                return Response(
                    {"error": "Invalid days parameter. Must be 1, 7, or 30."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except (ValueError, TypeError):
            return Response({"error": "Invalid days parameter"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            project_tz = ZoneInfo(self.team.timezone) if self.team.timezone else ZoneInfo("UTC")
        except Exception:
            project_tz = ZoneInfo("UTC")
        now = datetime.now(project_tz)
        cutoff_time = now - timedelta(days=days)

        try:
            external_jobs = ExternalDataJob.objects.filter(
                team_id=self.team_id, finished_at__gte=cutoff_time, billable=True
            )

            external_stats = external_jobs.aggregate(
                total=Count("id"),
                successful=Count("id", filter=Q(status=ExternalDataJob.Status.COMPLETED)),
                failed=Count(
                    "id",
                    filter=Q(
                        status__in=[
                            ExternalDataJob.Status.FAILED,
                            ExternalDataJob.Status.BILLING_LIMIT_REACHED,
                            ExternalDataJob.Status.BILLING_LIMIT_REACHED,
                        ]
                    ),
                ),
            )

            modeling_jobs = DataModelingJob.objects.filter(team_id=self.team_id, created_at__gte=cutoff_time)

            modeling_stats = modeling_jobs.aggregate(
                total=Count("id"),
                successful=Count("id", filter=Q(status=DataModelingJob.Status.COMPLETED)),
                failed=Count("id", filter=Q(status=DataModelingJob.Status.FAILED)),
            )

            total_jobs = external_stats["total"] + modeling_stats["total"]
            total_successful = external_stats["successful"] + modeling_stats["successful"]
            total_failed = external_stats["failed"] + modeling_stats["failed"]

            breakdown = {}
            if days == 1:
                external_by_hour = (
                    external_jobs.annotate(hour=TruncHour("created_at", tzinfo=project_tz))
                    .values("hour")
                    .annotate(
                        successful=Count("id", filter=Q(status=ExternalDataJob.Status.COMPLETED)),
                        failed=Count(
                            "id",
                            filter=Q(
                                status__in=[
                                    ExternalDataJob.Status.FAILED,
                                    ExternalDataJob.Status.BILLING_LIMIT_REACHED,
                                    ExternalDataJob.Status.BILLING_LIMIT_REACHED,
                                ]
                            ),
                        ),
                    )
                )

                modeling_by_hour = (
                    modeling_jobs.annotate(hour=TruncHour("created_at", tzinfo=project_tz))
                    .values("hour")
                    .annotate(
                        successful=Count("id", filter=Q(status=DataModelingJob.Status.COMPLETED)),
                        failed=Count("id", filter=Q(status=DataModelingJob.Status.FAILED)),
                    )
                )

                external_lookup = {result["hour"]: result for result in external_by_hour}
                modeling_lookup = {result["hour"]: result for result in modeling_by_hour}

                for i in range(24):
                    hour_start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=i)
                    external_data = external_lookup.get(hour_start, {"successful": 0, "failed": 0})
                    modeling_data = modeling_lookup.get(hour_start, {"successful": 0, "failed": 0})

                    breakdown[hour_start.isoformat()] = {
                        "successful": external_data["successful"] + modeling_data["successful"],
                        "failed": external_data["failed"] + modeling_data["failed"],
                    }
            else:
                external_by_day = (
                    external_jobs.annotate(day=TruncDate("created_at", tzinfo=project_tz))
                    .values("day")
                    .annotate(
                        successful=Count("id", filter=Q(status=ExternalDataJob.Status.COMPLETED)),
                        failed=Count(
                            "id",
                            filter=Q(
                                status__in=[
                                    ExternalDataJob.Status.FAILED,
                                    ExternalDataJob.Status.BILLING_LIMIT_REACHED,
                                    ExternalDataJob.Status.BILLING_LIMIT_REACHED,
                                ]
                            ),
                        ),
                    )
                )

                modeling_by_day = (
                    modeling_jobs.annotate(day=TruncDate("created_at", tzinfo=project_tz))
                    .values("day")
                    .annotate(
                        successful=Count("id", filter=Q(status=DataModelingJob.Status.COMPLETED)),
                        failed=Count("id", filter=Q(status=DataModelingJob.Status.FAILED)),
                    )
                )

                external_lookup = {result["day"]: result for result in external_by_day}
                modeling_lookup = {result["day"]: result for result in modeling_by_day}

                for i in range(days):
                    day_date = (now - timedelta(days=i)).date()
                    external_data = external_lookup.get(day_date, {"successful": 0, "failed": 0})
                    modeling_data = modeling_lookup.get(day_date, {"successful": 0, "failed": 0})

                    breakdown[str(day_date)] = {
                        "successful": external_data["successful"] + modeling_data["successful"],
                        "failed": external_data["failed"] + modeling_data["failed"],
                    }

            running_external_data_jobs = ExternalDataJob.objects.filter(
                team_id=self.team_id, status=ExternalDataJob.Status.RUNNING, billable=True, created_at__gte=cutoff_time
            ).count()
            running_modeling_jobs = DataModelingJob.objects.filter(
                team_id=self.team_id, status=DataModelingJob.Status.RUNNING, created_at__gte=cutoff_time
            ).count()

            return Response(
                {
                    "days": days,
                    "cutoff_time": cutoff_time,
                    "total_jobs": total_jobs,
                    "successful_jobs": total_successful,
                    "failed_jobs": total_failed,
                    "external_data_jobs": {
                        "total": external_stats["total"],
                        "running": running_external_data_jobs,
                        "successful": external_stats["successful"],
                        "failed": external_stats["failed"],
                    },
                    "modeling_jobs": {
                        "total": modeling_stats["total"],
                        "running": running_modeling_jobs,
                        "successful": modeling_stats["successful"],
                        "failed": modeling_stats["failed"],
                    },
                    "breakdown": breakdown,
                }
            )

        except Exception as e:
            logger.exception("Error retrieving job statistics", exc_info=e)
            return Response(
                {"error": "An error occurred retrieving job statistics"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
