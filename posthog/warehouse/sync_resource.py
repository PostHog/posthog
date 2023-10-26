from posthog.warehouse.models.external_data_resource import ExternalDataResource
from posthog.warehouse.models import DataWarehouseCredential, DataWarehouseTable
from posthog.warehouse.external_data_resource.connection import retrieve_sync
from posthog.celery import app

from django.conf import settings
import structlog

logger = structlog.get_logger(__name__)


def sync_resources():
    resources = ExternalDataResource.objects.filter(are_tables_created=False, status="running")

    for resource in resources:
        _sync_resource.delay(resource.pk)


@app.task(ignore_result=True)
def _sync_resource(resource_id):
    resource = ExternalDataResource.objects.get(pk=resource_id)
    job = retrieve_sync(resource.connection_id)

    if job["status"] == "succeeded":

        resource = ExternalDataResource.objects.get(pk=resource_id)
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
