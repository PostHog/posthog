import dagster

from products.growth.dags import github_sdk_versions, oauth, team_sdk_versions, user_product_list

from . import resources

defs = dagster.Definitions(
    jobs=[
        oauth.oauth_clear_expired_oauth_tokens_job,
        github_sdk_versions.cache_github_sdk_versions_job,
        team_sdk_versions.cache_all_team_sdk_versions_job,
        user_product_list.populate_user_product_list_job,
        user_product_list.sync_colleagues_products_monthly_job,
        user_product_list.sync_cross_sell_products_monthly_job,
    ],
    schedules=[
        oauth.oauth_clear_expired_oauth_tokens_schedule,
        github_sdk_versions.cache_github_sdk_versions_schedule,
        team_sdk_versions.cache_all_team_sdk_versions_schedule,
        user_product_list.sync_colleagues_products_monthly_schedule,
        user_product_list.sync_cross_sell_products_monthly_schedule,
    ],
    resources=resources,
)
