import dagster

from dags import oauth
from dags.sdk_doctor import github_sdk_versions, team_sdk_versions

from . import resources

defs = dagster.Definitions(
    jobs=[
        oauth.oauth_clear_expired_oauth_tokens_job,
        github_sdk_versions.cache_github_sdk_versions_job,
        team_sdk_versions.cache_all_team_sdk_versions_job,
    ],
    schedules=[
        oauth.oauth_clear_expired_oauth_tokens_schedule,
        github_sdk_versions.cache_github_sdk_versions_schedule,
        team_sdk_versions.cache_all_team_sdk_versions_schedule,
    ],
    resources=resources,
)
