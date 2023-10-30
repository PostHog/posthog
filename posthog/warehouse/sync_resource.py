from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.models import DataWarehouseCredential, DataWarehouseTable
from posthog.warehouse.external_data_source.connection import AIRBYTE_JOBS_URL, retrieve_sync
from posthog.celery import app
from datetime import datetime
from urllib.parse import urlencode

import requests

from django.conf import settings
import structlog

logger = structlog.get_logger(__name__)


def sync_resources():
    resources = ExternalDataSource.objects.filter(are_tables_created=False, status="running")

    for resource in resources:
        _sync_resource.delay(resource.pk)


@app.task(ignore_result=True)
def _sync_resource(resource_id):
    resource = ExternalDataSource.objects.get(pk=resource_id)
    job = retrieve_sync(resource.connection_id)

    if job["status"] == "succeeded":

        resource = ExternalDataSource.objects.get(pk=resource_id)
        credential, _ = DataWarehouseCredential.objects.get_or_create(
            team_id=resource.team.pk,
            access_key=settings.AIRBYTE_BUCKET_KEY,
            access_secret=settings.AIRBYTE_BUCKET_SECRET,
        )

        # TODO: THIS IS PATH SHOULD BE SPLIT BY TEAM_ID
        data = {
            "credential": credential,
            "name": "stripe_customers",
            "format": "Parquet",
            "url_pattern": f"https://databeach-hackathon.s3.amazonaws.com/airbyte/{resource.team.pk}/customers/*.parquet",
            "team_id": resource.team.pk,
        }

        table = DataWarehouseTable(**data)
        try:
            table.columns = table.get_columns()
        except Exception as e:
            logger.exception("Sync Resource failed with an unexpected exception.", exc_info=e)
        else:
            table.save()

            resource.are_tables_created = True
            resource.status = job["status"]
            resource.save()


def get_rows_synced_by_team(begin: datetime, end: datetime, team_id):
    resources = ExternalDataSource.objects.filter(team_id=team_id, are_tables_created=True)
    return sum([get_rows_synced_by_resource_id(begin, end, resource.pk) for resource in resources])


def get_rows_synced_by_resource_id(begin: datetime, end: datetime, resource_id, offset=0):

    resource = ExternalDataSource.objects.get(pk=resource_id)
    params = {
        "connectionId": resource.connection_id,
        "limit": 100,
        "offset": offset,
        "status": "succeeded",
        "updatedAtStart": begin.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "updatedAtEnd": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    return _accumulate_jobs_field(AIRBYTE_JOBS_URL + "?" + urlencode(params), "rowsSynced")


def _accumulate_jobs_field(url, field, acc=0):
    token = settings.AIRBYTE_API_KEY

    headers = {"accept": "application/json", "authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)
    response_payload = response.json()
    response_data = response_payload.get("data", [])
    response_next = response_payload.get("next", None)
    acc += sum([job[field] for job in response_data])

    if response_next:
        return _accumulate_jobs_field(response_payload["next"], field, acc=acc)

    return acc
