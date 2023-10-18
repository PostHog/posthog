from posthog.warehouse.models.airbyte_resource import AirbyteResource
from posthog.warehouse.models import DataWarehouseCredential, DataWarehouseTable

from django.conf import settings
import structlog

logger = structlog.get_logger(__name__)


def sync_resources():
    resources = AirbyteResource.objects.filter(are_tables_created=False, status="succeeded")

    for resource in resources:
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
            "url_pattern": f"https://databeach-hackathon.s3.amazonaws.com/airbyte/13/customers/*.parquet",
            "team_id": resource.team.pk,
        }

        table = DataWarehouseTable(**data)
        try:
            table.columns = table.get_columns()
        except Exception as e:
            logger.exception("Sync Resource failed with an unexpected exception.", exc_info=e)
            continue
        finally:
            table.save()

            resource.are_tables_created = True
            resource.save()
