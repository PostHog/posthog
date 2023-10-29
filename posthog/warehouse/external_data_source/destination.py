import requests
from django.conf import settings
from pydantic import BaseModel

AIRBYTE_DESTINATION_URL = "https://api.airbyte.com/v1/destinations"


class ExternalDataDestination(BaseModel):
    destination_id: str


def create_destination(team_id: int) -> ExternalDataDestination:
    token = settings.AIRBYTE_API_KEY
    if not token:
        raise ValueError("AIRBYTE_API_KEY must be set in order to create a source.")

    payload = {
        "configuration": {
            "format": {"format_type": "Parquet", "compression_codec": "UNCOMPRESSED"},
            "destinationType": "s3",
            "s3_bucket_region": "us-east-1",
            "access_key_id": settings.AIRBYTE_BUCKET_KEY,
            "secret_access_key": settings.AIRBYTE_BUCKET_SECRET,
            "s3_bucket_name": "databeach-hackathon",
            "s3_bucket_path": f"airbyte/{team_id}",
        },
        "name": f"S3/{team_id}",
        "workspaceId": settings.AIRBYTE_WORKSPACE_ID,
    }
    headers = {"accept": "application/json", "content-type": "application/json", "authorization": f"Bearer {token}"}

    response = requests.post(AIRBYTE_DESTINATION_URL, json=payload, headers=headers)
    response_payload = response.json()

    if not response.ok:
        raise ValueError(response_payload["detail"])

    return ExternalDataDestination(
        destination_id=response_payload["destinationId"],
    )


def delete_destination(destination_id: str) -> None:
    token = settings.AIRBYTE_API_KEY
    if not token:
        raise ValueError("AIRBYTE_API_KEY must be set in order to delete a destiantion.")
    headers = {"authorization": "Bearer {token}"}

    response = requests.delete(AIRBYTE_DESTINATION_URL + "/" + destination_id, headers=headers)

    if not response.ok:
        raise ValueError(response.json()["detail"])
