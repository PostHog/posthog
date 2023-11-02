from posthog.warehouse.models.external_data_workspace import ExternalDataWorkspace
from posthog.warehouse.external_data_source.client import send_request

AIRBYTE_WORKSPACE_URL = "https://api.airbyte.io/api/v1/workspaces"


def create_workspace(team_id: int):
    payload = {"name": "Team " + team_id}
    response = send_request(AIRBYTE_WORKSPACE_URL, payload=payload)

    return response["workspaceId"]


def get_or_create_workspace(team_id: int):
    workspace = ExternalDataWorkspace.objects.get(team_id=team_id)

    if not workspace:
        workspace_id = create_workspace(team_id)

        workspace = ExternalDataWorkspace.objects.create(team_id=team_id, workspace_id=workspace_id)

    return workspace
