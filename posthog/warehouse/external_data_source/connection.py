import requests
from django.conf import settings
from pydantic import BaseModel
from typing import Dict

AIRBYTE_CONNECTION_URL = "https://api.airbyte.com/v1/connections"
AIRBYTE_JOBS_URL = "https://api.airbyte.com/v1/jobs"


class ExternalDataConnection(BaseModel):
    connection_id: str
    source_id: str
    destination_id: str
    name: str
    workspace_id: str


def create_connection(source_id: str, destination_id: str) -> ExternalDataConnection:
    token = settings.AIRBYTE_API_KEY
    if not token:
        raise ValueError("AIRBYTE_API_KEY must be set in order to create a source.")

    headers = {"accept": "application/json", "content-type": "application/json", "Authorization": f"Bearer {token}"}

    payload = {
        "schedule": {"scheduleType": "cron", "cronExpression": "0 0 0 * * ?"},
        "namespaceFormat": None,
        "sourceId": source_id,
        "destinationId": destination_id,
    }

    response = requests.post(AIRBYTE_CONNECTION_URL, json=payload, headers=headers)
    response_payload = response.json()

    if not response.ok:
        raise ValueError(response_payload["detail"])

    update_connection_stream(response_payload["connectionId"], headers)

    return ExternalDataConnection(
        source_id=response_payload["sourceId"],
        name=response_payload["name"],
        connection_id=response_payload["connectionId"],
        workspace_id=response_payload["workspaceId"],
        destination_id=response_payload["destinationId"],
    )


def update_connection_stream(connection_id: str, headers: Dict):
    connection_id_url = f"{AIRBYTE_CONNECTION_URL}/{connection_id}"

    # TODO: hardcoded to stripe stream right now
    payload = {
        "configurations": {"streams": [{"name": "customers", "syncMode": "full_refresh_overwrite"}]},
        "schedule": {"scheduleType": "cron", "cronExpression": "0 0 0 * * ?"},
        "namespaceFormat": None,
    }

    response = requests.patch(connection_id_url, json=payload, headers=headers)
    response_payload = response.json()

    if not response.ok:
        raise ValueError(response_payload["detail"])


def start_sync(connection_id: str):
    token = settings.AIRBYTE_API_KEY
    if not token:
        raise ValueError("AIRBYTE_API_KEY must be set in order to start sync.")

    headers = {"accept": "application/json", "content-type": "application/json", "Authorization": f"Bearer {token}"}
    payload = {"jobType": "sync", "connectionId": connection_id}

    response = requests.post(AIRBYTE_JOBS_URL, json=payload, headers=headers)
    response_payload = response.json()

    if not response.ok:
        raise ValueError(response_payload["detail"])


def retrieve_sync(connection_id: str):
    token = settings.AIRBYTE_API_KEY
    headers = {"accept": "application/json", "content-type": "application/json", "Authorization": f"Bearer {token}"}
    params = {"connectionId": connection_id, "limit": 1}
    response = requests.get(AIRBYTE_JOBS_URL, params=params, headers=headers)
    response_payload = response.json()["data"]
    latest_job = response_payload[0]

    if not response.ok:
        raise ValueError(response_payload["detail"])

    return latest_job
