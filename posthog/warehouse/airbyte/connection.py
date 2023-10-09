import requests
from django.conf import settings
from pydantic import BaseModel

AIRBYTE_CONNECTION_URL = "https://api.airbyte.com/v1/connections"


class AirbyteConnection(BaseModel):
    connection_id: str
    source_id: str
    destination_id: str
    name: str
    workspace_id: str


def create_connection(source_id: str) -> AirbyteConnection:
    token = settings.AIRBYTE_API_KEY
    if not token:
        raise ValueError("AIRBYTE_API_KEY must be set in order to create a source.")

    headers = {"accept": "application/json", "content-type": "application/json", "Authorization": f"Bearer {token}"}

    payload = {
        "schedule": {"scheduleType": "cron", "cronExpression": "0 0 0 * * ?"},
        "namespaceFormat": None,
        "sourceId": source_id,
        "destinationId": settings.AIRBYTE_DESTINATION_ID,
    }

    response = requests.post(AIRBYTE_CONNECTION_URL, json=payload, headers=headers)
    response_payload = response.json()

    if not response.ok:
        raise ValueError(response_payload["detail"])

    return AirbyteConnection(
        source_id=response_payload["sourceId"],
        name=response_payload["name"],
        connection_id=response_payload["connectionId"],
        workspace_id=response_payload["workspaceId"],
        destination_id=response_payload["destinationId"],
    )
