import dagster

from dags import oauth

from . import resources

defs = dagster.Definitions(
    jobs=[
        oauth.oauth_clear_expired_oauth_tokens_job,
    ],
    schedules=[
        oauth.oauth_clear_expired_oauth_tokens_schedule,
    ],
    resources=resources,
)
