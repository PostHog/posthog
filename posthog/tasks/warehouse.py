from django.conf import settings
import datetime
from posthog.models import Team
from posthog.warehouse.external_data_source.client import send_request
from posthog.warehouse.data_load.service import (
    cancel_external_data_workflow,
    pause_external_data_schedule,
    unpause_external_data_schedule,
)
from posthog.warehouse.models import DataWarehouseCredential, DataWarehouseTable, ExternalDataSource, ExternalDataJob
from posthog.warehouse.external_data_source.connection import retrieve_sync
from urllib.parse import urlencode
from posthog.ph_client import get_ph_client
from typing import Any, Dict, List, TYPE_CHECKING
from posthog.celery import app
import structlog

logger = structlog.get_logger(__name__)

AIRBYTE_JOBS_URL = "https://api.airbyte.com/v1/jobs"
DEFAULT_DATE_TIME = datetime.datetime(2023, 11, 7, tzinfo=datetime.timezone.utc)

if TYPE_CHECKING:
    from posthoganalytics import Posthog


def sync_resources() -> None:
    resources = ExternalDataSource.objects.filter(are_tables_created=False, status__in=["running", "error"])

    for resource in resources:
        sync_resource.delay(resource.pk)


@app.task(ignore_result=True)
def sync_resource(resource_id: str) -> None:
    resource = ExternalDataSource.objects.get(pk=resource_id)

    try:
        job = retrieve_sync(resource.connection_id)
    except Exception as e:
        logger.exception("Data Warehouse: Sync Resource failed with an unexpected exception.", exc_info=e)
        resource.status = "error"
        resource.save()
        return

    if job is None:
        logger.error(f"Data Warehouse: No jobs found for connection: {resource.connection_id}")
        resource.status = "error"
        resource.save()
        return

    if job["status"] == "succeeded":
        resource = ExternalDataSource.objects.get(pk=resource_id)
        credential, _ = DataWarehouseCredential.objects.get_or_create(
            team_id=resource.team.pk,
            access_key=settings.AIRBYTE_BUCKET_KEY,
            access_secret=settings.AIRBYTE_BUCKET_SECRET,
        )

        data = {
            "credential": credential,
            "name": "stripe_customers",
            "format": "Parquet",
            "url_pattern": f"https://{settings.AIRBYTE_BUCKET_DOMAIN}/airbyte/{resource.team.pk}/customers/*.parquet",
            "team_id": resource.team.pk,
        }

        table = DataWarehouseTable(**data)
        try:
            table.columns = table.get_columns()
        except Exception as e:
            logger.exception(
                f"Data Warehouse: Sync Resource failed with an unexpected exception for connection: {resource.connection_id}",
                exc_info=e,
            )
        else:
            table.save()

            resource.are_tables_created = True
            resource.status = job["status"]
            resource.save()

    else:
        resource.status = job["status"]
        resource.save()


DEFAULT_USAGE_LIMIT = 1000000
ROWS_PER_DOLLAR = 66666  # 1 million rows per $15


@app.task(ignore_result=True, max_retries=2)
def check_external_data_source_billing_limit_by_team(team_id: int) -> None:
    from posthog.warehouse.external_data_source.connection import deactivate_connection_by_id, activate_connection_by_id
    from ee.billing.quota_limiting import list_limited_team_attributes, QuotaResource

    limited_teams_rows_synced = list_limited_team_attributes(QuotaResource.ROWS_SYNCED)

    team = Team.objects.get(pk=team_id)
    all_active_connections = ExternalDataSource.objects.filter(team=team, status__in=["running", "succeeded"])
    all_inactive_connections = ExternalDataSource.objects.filter(team=team, status="inactive")

    # TODO: consider more boundaries
    if team_id in limited_teams_rows_synced:
        for connection in all_active_connections:
            deactivate_connection_by_id(connection.connection_id)
            connection.status = "inactive"
            connection.save()
    else:
        for connection in all_inactive_connections:
            activate_connection_by_id(connection.connection_id)
            connection.status = "running"
            connection.save()


@app.task(ignore_result=True, max_retries=2)
def capture_workspace_rows_synced_by_team(team_id: int) -> None:
    ph_client = get_ph_client()
    team = Team.objects.get(pk=team_id)
    now = datetime.datetime.now(datetime.timezone.utc)
    begin = team.external_data_workspace_last_synced_at or DEFAULT_DATE_TIME

    params = {
        "workspaceIds": team.external_data_workspace_id,
        "limit": 100,
        "offset": 0,
        "status": "succeeded",
        "orderBy": "createdAt|ASC",
        "updatedAtStart": begin.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "updatedAtEnd": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    result_totals = _traverse_jobs_by_field(ph_client, team, AIRBYTE_JOBS_URL + "?" + urlencode(params), "rowsSynced")

    # TODO: check assumption that ordering is possible with API
    team.external_data_workspace_last_synced_at = result_totals[-1]["startTime"] if result_totals else now
    team.save()

    ph_client.shutdown()


def _traverse_jobs_by_field(
    ph_client: "Posthog", team: Team, url: str, field: str, acc: List[Dict[str, Any]] = []
) -> List[Dict[str, Any]]:
    response = send_request(url, method="GET")
    response_data = response.get("data", [])
    response_next = response.get("next", None)

    for job in response_data:
        acc.append(
            {
                "count": job[field],
                "startTime": job["startTime"],
            }
        )
        ph_client.capture(
            team.pk,
            "external data sync job",
            {
                "count": job[field],
                "workspace_id": team.external_data_workspace_id,
                "team_id": team.pk,
                "team_uuid": team.uuid,
                "startTime": job["startTime"],
                "job_id": str(job["jobId"]),
            },
        )

    if response_next:
        return _traverse_jobs_by_field(ph_client, team, response_next, field, acc)

    return acc


MONTHLY_LIMIT = 1_000_000


def check_synced_row_limits() -> None:
    team_ids = ExternalDataSource.objects.values_list("team", flat=True)
    for team_id in team_ids:
        check_synced_row_limits_of_team.delay(team_id)


@app.task(ignore_result=True)
def check_synced_row_limits_of_team(team_id: int) -> None:
    logger.info("Checking synced row limits of team", team_id=team_id)
    start_of_month = datetime.datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows_synced_list = [
        x
        for x in ExternalDataJob.objects.filter(team_id=team_id, created_at__gte=start_of_month).values_list(
            "rows_synced", flat=True
        )
        if x
    ]
    total_rows_synced = sum(rows_synced_list)

    if total_rows_synced > MONTHLY_LIMIT:
        running_jobs = ExternalDataJob.objects.filter(team_id=team_id, status=ExternalDataJob.Status.RUNNING)
        for job in running_jobs:
            try:
                cancel_external_data_workflow(job.workflow_id)
            except Exception as e:
                logger.exception("Could not cancel external data workflow", exc_info=e)

            try:
                pause_external_data_schedule(job.pipeline)
            except Exception as e:
                logger.exception("Could not pause external data schedule", exc_info=e)

            job.status = ExternalDataJob.Status.CANCELLED
            job.save()

            job.pipeline.status = ExternalDataSource.Status.PAUSED
            job.pipeline.save()
    else:
        all_sources = ExternalDataSource.objects.filter(team_id=team_id)
        for source in all_sources:
            try:
                unpause_external_data_schedule(source)
            except Exception as e:
                logger.exception("Could not unpause external data schedule", exc_info=e)

            source.status = ExternalDataSource.Status.COMPLETED
            source.save()
