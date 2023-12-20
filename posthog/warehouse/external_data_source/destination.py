from django.conf import settings
from pydantic import BaseModel

from posthog.warehouse.external_data_source.client import send_request

AIRBYTE_DESTINATION_URL = "https://api.airbyte.com/v1/destinations"


class ExternalDataDestination(BaseModel):
    destination_id: str


def create_destination(team_id: int, workspace_id: str) -> ExternalDataDestination:
    payload = {
        "configuration": {
            "format": {"format_type": "Parquet", "compression_codec": "UNCOMPRESSED"},
            "destinationType": "s3",
            "s3_bucket_region": settings.AIRBYTE_BUCKET_REGION,
            "access_key_id": settings.AIRBYTE_BUCKET_KEY,
            "secret_access_key": settings.AIRBYTE_BUCKET_SECRET,
            "s3_bucket_name": settings.AIRBYTE_BUCKET_NAME,
            "s3_bucket_path": f"airbyte/{team_id}",
        },
        "name": f"S3/{team_id}",
        "workspaceId": workspace_id,
    }

    response = send_request(AIRBYTE_DESTINATION_URL, method="POST", payload=payload)

    return ExternalDataDestination(
        destination_id=response["destinationId"],
    )


def delete_destination(destination_id: str) -> None:
    send_request(AIRBYTE_DESTINATION_URL + "/" + destination_id, method="DELETE")
