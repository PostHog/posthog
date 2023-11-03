from posthog.models import Team
from posthog.warehouse.external_data_source.client import send_request

AIRBYTE_WORKSPACE_URL = "https://api.airbyte.com/v1/workspaces"


def create_workspace(team_id: int):
    payload = {"name": "Team " + str(team_id)}
    response = send_request(AIRBYTE_WORKSPACE_URL, method="POST", payload=payload)

    return response["workspaceId"]


def get_or_create_workspace(team_id: int):
    team = Team.objects.get(id=team_id)

    if not team.external_data_workspace_id:
        workspace_id = create_workspace(team_id)
        team.external_data_workspace_id = workspace_id
        team.save()

    return team.external_data_workspace_id
