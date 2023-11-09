from django.conf import settings
import datetime
from posthog.models import Team
from posthog.warehouse.external_data_source.client import send_request
from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.models import DataWarehouseCredential, DataWarehouseTable
from posthog.warehouse.external_data_source.connection import retrieve_sync
from urllib.parse import urlencode
from posthog.ph_client import get_ph_client

from posthog.celery import app
import structlog

logger = structlog.get_logger(__name__)

AIRBYTE_JOBS_URL = "https://api.airbyte.com/v1/jobs"

DEFAULT_DATE_TIME = datetime.datetime(2023, 11, 7, tzinfo=datetime.timezone.utc)


def sync_resources():
    resources = ExternalDataSource.objects.filter(are_tables_created=False, status__in=["running", "error"])

    for resource in resources:
        sync_resource.delay(resource.pk)


@app.task(ignore_result=True)
def sync_resource(resource_id):
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
def check_external_data_source_billing_limit_by_team(team_id):
    from posthog.warehouse.external_data_source.connection import deactivate_connection_by_id, activate_connection_by_id

    team = Team.objects.get(pk=team_id)
    all_active_connections = ExternalDataSource.objects.filter(team=team, status__in=["running", "succeeded"])
    all_inactive_connections = ExternalDataSource.objects.filter(team=team, status="inactive")

    _usage_limit = _get_data_warehouse_usage_limit(team_id)

    # TODO: consider more boundaries
    if _usage_limit and team.external_data_workspace_rows_synced_in_month >= (_usage_limit * ROWS_PER_DOLLAR):
        for connection in all_active_connections:
            deactivate_connection_by_id(connection.connection_id)
            connection.status = "inactive"
            connection.save()
    else:
        for connection in all_inactive_connections:
            activate_connection_by_id(connection.connection_id)
            connection.status = "running"
            connection.save()


def _get_data_warehouse_usage_limit(team_id):
    from posthog.cloud_utils import get_cached_instance_license
    from ee.billing.billing_manager import BillingManager

    license = get_cached_instance_license()
    team = Team.objects.get(pk=team_id)
    org = team.organization

    response = BillingManager(license).get_billing(org, None)
    try:
        data_warehouse_product = [product for product in response["products"] if product["name"] == "Data Warehouse"][0]
        usage_limit = data_warehouse_product["usage_limit"]
    except Exception as e:
        logger.exception("Data Warehouse: Failed to retrieve data warehouse billing product", exc_info=e)
        usage_limit = DEFAULT_USAGE_LIMIT

    return usage_limit


@app.task(ignore_result=True, max_retries=2)
def calculate_workspace_rows_synced_by_team(team_id):
    ph_client = get_ph_client()
    team = Team.objects.get(pk=team_id)
    now = datetime.datetime.now(datetime.timezone.utc)
    begin = team.external_data_workspace_last_synced or now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = now

    params = {
        "workspaceIds": team.external_data_workspace_id,
        "limit": 100,
        "offset": 0,
        "status": "succeeded",
        "orderBy": "createdAt|ASC",
        "updatedAtStart": begin.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "updatedAtEnd": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    result_totals = _traverse_jobs_by_field(ph_client, team, AIRBYTE_JOBS_URL + "?" + urlencode(params), "rowsSynced")

    # reset accumulated to new period if the month has changed
    if end.month != begin.month:
        total = sum([result["count"] for result in result_totals if result["startTime"].month == end.month])
    elif team.external_data_workspace_last_synced and team.external_data_workspace_last_synced.month != begin.month:
        total = sum([result["count"] for result in result_totals])
    else:
        total = (
            team.external_data_workspace_rows_synced_in_month
            if team.external_data_workspace_rows_synced_in_month is not None
            else 0
        ) + sum(
            [
                result["count"]
                for result in result_totals
                if datetime.datetime.strptime(result["startTime"], "%Y-%m-%dT%H:%M:%SZ").month == end.month
            ]
        )

    team = Team.objects.get(pk=team_id)

    # TODO: check assumption that ordering is possible with API
    team.external_data_workspace_last_synced = result_totals[-1]["startTime"] if result_totals else end
    team.external_data_workspace_rows_synced_in_month = total
    team.save()

    ph_client.shutdown()


def _traverse_jobs_by_field(ph_client, team, url, field, acc=[]):
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
