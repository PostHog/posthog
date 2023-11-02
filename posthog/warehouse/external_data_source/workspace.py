from posthog.warehouse.models.external_data_workspace import ExternalDataWorkspace
from posthog.warehouse.external_data_source.client import send_request

AIRBYTE_WORKSPACE_URL = "https://api.airbyte.com/v1/workspaces"


def create_workspace(team_id: int):
    payload = {"name": "Team " + str(team_id)}
    response = send_request(AIRBYTE_WORKSPACE_URL, method="POST", payload=payload)

    return response["workspaceId"]


def get_or_create_workspace(team_id: int):
    workspace_exists = ExternalDataWorkspace.objects.filter(team_id=team_id).exists()

    if not workspace_exists:
        workspace_id = create_workspace(team_id)

        workspace = ExternalDataWorkspace.objects.create(team_id=team_id, workspace_id=workspace_id)
    else:
        workspace = ExternalDataWorkspace.objects.get(team_id=team_id)
    return workspace
