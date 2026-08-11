from celery import shared_task

from ee.billing.quota_limiting import refresh_org_self_driving_quota


@shared_task(ignore_result=True, max_retries=0)
def refresh_org_self_driving_quota_task(organization_id: str) -> None:
    """Event-driven self-driving quota re-evaluation for one org (see `refresh_org_self_driving_quota`).

    No retries: the 15-minute quota cron is the backstop for a failed refresh, and re-running a
    stale refresh later could briefly overwrite a fresher `todays_usage`.
    """
    refresh_org_self_driving_quota(organization_id)
