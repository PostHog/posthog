import dagster

from products.growth.dags import (
    github_sdk_versions,
    identity_matching,
    oauth,
    product_push_campaigns,
    team_production_event_activation,
    user_product_list,
)

from . import loggers, resources

jobs = [
    oauth.oauth_clear_expired_oauth_tokens_job,
    github_sdk_versions.cache_github_sdk_versions_job,
    user_product_list.populate_user_product_list_job,
    user_product_list.sync_colleagues_products_monthly_job,
    user_product_list.sync_cross_sell_products_monthly_job,
    team_production_event_activation.detect_first_team_production_event_job,
    product_push_campaigns.product_push_campaigns_job,
]
# Identity matching processes internal PostHog data that only exists on Cloud US (team 2),
# so the job is not registered on Cloud EU.
if identity_matching.is_identity_matching_registered():
    jobs.append(identity_matching.identity_matching_job)

defs = dagster.Definitions(
    jobs=jobs,
    schedules=[
        oauth.oauth_clear_expired_oauth_tokens_schedule,
        github_sdk_versions.cache_github_sdk_versions_schedule,
        user_product_list.sync_colleagues_products_monthly_schedule,
        user_product_list.sync_cross_sell_products_monthly_schedule,
        team_production_event_activation.detect_first_team_production_event_schedule,
        product_push_campaigns.product_push_campaigns_schedule,
    ],
    loggers=loggers,
    resources=resources,
)
