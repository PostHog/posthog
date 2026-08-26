from celery import shared_task

from posthog.query_cache.storage import delete_blob


# Not an app-level tasks.py, so celery autodiscovery never imports it; registered via
# CELERY_IMPORTS in posthog/settings/celery.py.
@shared_task(ignore_result=True)
def delete_query_cache_blob(bucket: str, key: str, team_id: int, trigger: str) -> None:
    delete_blob(bucket=bucket, key=key, team_id=team_id, trigger=trigger)
