from django.conf import settings

# Dagster Cloud deployment slug per PostHog cloud environment. The admin runs on web pods, which
# don't carry DAGSTER_DOMAIN (only Dagster pods do), so the run URL is derived from CLOUD_DEPLOYMENT.
DAGSTER_DEPLOYMENT_BY_CLOUD = {"US": "prod-us", "EU": "prod-eu", "DEV": "dev"}


def dagster_run_url(run_id: str) -> str | None:
    """Link to a Dagster run, or None when the deployment can't be identified (local/self-hosted)."""
    if settings.DAGSTER_DOMAIN:
        return f"https://{settings.DAGSTER_DOMAIN}/runs/{run_id}"
    deployment = DAGSTER_DEPLOYMENT_BY_CLOUD.get((settings.CLOUD_DEPLOYMENT or "").upper())
    if deployment:
        return f"https://posthog.dagster.cloud/{deployment}/runs/{run_id}"
    return None
