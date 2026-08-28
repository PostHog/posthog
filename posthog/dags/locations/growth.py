import dagster

from products.growth.dags import (
    ai_enrichment,
    custom_product_push_campaigns,
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
    # Kept unscheduled: connection-time default seeding replaced the monthly colleague
    # sync, but the job stays available for manual runs.
    user_product_list.sync_colleagues_products_monthly_job,
    user_product_list.sync_cross_sell_products_monthly_job,
    team_production_event_activation.detect_first_team_production_event_job,
    product_push_campaigns.product_push_campaigns_job,
    # Manual-run only: growth names the organizations, product, and window per run.
    custom_product_push_campaigns.custom_product_push_campaigns_job,
]
schedules = [
    oauth.oauth_clear_expired_oauth_tokens_schedule,
    github_sdk_versions.cache_github_sdk_versions_schedule,
    user_product_list.sync_cross_sell_products_monthly_schedule,
    team_production_event_activation.detect_first_team_production_event_schedule,
    product_push_campaigns.product_push_campaigns_schedule,
]
# Identity matching processes internal PostHog data that only exists on Cloud US (team 2),
# so the job is not registered on Cloud EU.
if identity_matching.is_identity_matching_registered():
    jobs.append(identity_matching.identity_matching_job)
# AI enrichment sends organization signup data to an external LLM gateway, so — like
# identity matching — it is not registered on Cloud EU.
if ai_enrichment.is_ai_enrichment_registered():
    jobs.append(ai_enrichment.ai_enrichment_job)
    schedules.append(ai_enrichment.ai_enrichment_schedule)

defs = dagster.Definitions(
    jobs=jobs,
    schedules=schedules,
    loggers=loggers,
    resources=resources,
)
