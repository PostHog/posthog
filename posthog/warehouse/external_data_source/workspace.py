import requests
from django.conf import settings
from posthog.warehouse.models.external_data_workspace import ExternalDataWorkspace

AIRBYTE_WORKSPACE_URL = "https://api.airbyte.io/api/v1/workspaces"


def create_workspace(team_id: int):
    token = settings.AIRBYTE_API_KEY
    if not token:
        raise ValueError("AIRBYTE_API_KEY must be set in order to create a source.")

    payload = {"name": "Team " + team_id}

    headers = {"accept": "application/json", "content-type": "application/json", "authorization": f"Bearer {token}"}

    response = requests.post(AIRBYTE_WORKSPACE_URL, json=payload, headers=headers)
    response_payload = response.json()

    if not response.ok:
        raise ValueError(response_payload["message"])

    return response_payload["workspaceId"]


def get_or_create_workspace(team_id: int):
    workspace = ExternalDataWorkspace.objects.get(team_id=team_id)

    if not workspace:
        workspace_id = create_workspace(team_id)

        workspace = ExternalDataWorkspace.objects.create(team_id=team_id, workspace_id=workspace_id)

    return workspace
