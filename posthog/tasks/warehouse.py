import datetime
from posthog.models import Team
from posthog.warehouse.external_data_source.client import send_request
from urllib.parse import urlencode

AIRBYTE_JOBS_URL = "https://api.airbyte.com/v1/jobs"

DEFAULT_DATE_TIME = datetime.datetime(2023, 11, 7, tzinfo=datetime.timezone.utc)


# TODO: split these into their own tasks
def calculate_workspace_rows_synced_by_team(ph_client, team_id):
    team = Team.objects.get(pk=team_id)
    now = datetime.datetime.now(datetime.timezone.utc)
    begin = team.external_data_workspace_last_synced or now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = now

    params = {
        "workspaceIds": team.external_data_workspace_id,
        "limit": 100,
        "offset": 0,
        "status": "succeeded",
        "orderBy": "createdAt|ASC",
        "updatedAtStart": begin.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "updatedAtEnd": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    result_totals = _traverse_jobs_by_field(ph_client, team, AIRBYTE_JOBS_URL + "?" + urlencode(params), "rowsSynced")

    # reset accumulated to new period if the month has changed
    if end.month != begin.month:
        total = sum([result["count"] for result in result_totals if result["startTime"].month == end.month])
    elif team.external_data_workspace_last_synced and team.external_data_workspace_last_synced.month != begin.month:
        total = sum([result["count"] for result in result_totals])
    else:
        total = (
            team.external_data_workspace_rows_synced_in_month
            if team.external_data_workspace_rows_synced_in_month is not None
            else 0
        ) + sum(
            [
                result["count"]
                for result in result_totals
                if datetime.datetime.strptime(result["startTime"], "%Y-%m-%dT%H:%M:%SZ").month == end.month
            ]
        )

    team = Team.objects.get(pk=team_id)
    team.external_data_workspace_last_synced = result_totals[-1]["startTime"] if result_totals else end
    team.external_data_workspace_rows_synced_in_month = total
    team.save()


def _traverse_jobs_by_field(ph_client, team, url, field, acc=[]):
    response = send_request(url, method="GET")
    response_data = response.get("data", [])
    response_next = response.get("next", None)

    for job in response_data:
        acc.append(
            {
                "count": job[field],
                "startTime": job["startTime"],
            }
        )
        ph_client.capture(
            team.pk,
            "external data sync job",
            {
                "count": job[field],
                "team_id": team.pk,
                "team_uuid": team.uuid,
                "startTime": job["startTime"],
            },
        )

    if response_next:
        return _traverse_jobs_by_field(ph_client, team, response_next, field, acc)

    return acc
