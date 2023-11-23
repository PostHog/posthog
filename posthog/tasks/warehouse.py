from django.conf import settings
import datetime
from posthog.models import Team
from posthog.warehouse.external_data_source.client import send_request
from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.models import DataWarehouseCredential, DataWarehouseTable
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
