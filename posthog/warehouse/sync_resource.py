from posthog.warehouse.models.airbyte_resource import AirbyteResource
from posthog.warehouse.models import DataWarehouseCredential, DataWarehouseTable

from django.conf import settings


def sync_resources():
    resources = AirbyteResource.objects.filter(are_tables_created=False, status="succeeded")

    for resource in resources:
        credential = DataWarehouseCredential.objects.get_or_create(
            team_id=resource.team.pk,
            access_key=settings.AIRBYTE_BUCKET_KEY,
            access_secret=settings.AIRBYTE_BUCKET_SECRET,
        )

        # TODO: THIS IS PATH SHOULD BE SPLIT BY TEAM_ID
        DataWarehouseTable.objects.create(
            credential=credential,
            name="stripe_customers",
            format="Parquet",
            url_pattern="https://databeach-hackathon.s3.amazonaws.com/airbyte-test/customers/*.parquet",
        )

        resource.are_tables_created = True
        resource.save()
