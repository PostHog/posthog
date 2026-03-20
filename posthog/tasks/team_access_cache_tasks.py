"""
No-op stubs for removed team access cache warming tasks.

Kept to avoid ImportError for tasks already enqueued in Celery.
Safe to delete once all in-flight messages have expired.
"""

from celery import shared_task


@shared_task(ignore_result=True)
def warm_user_teams_cache_task(user_id: int) -> None:
    pass


@shared_task(ignore_result=True)
def warm_personal_api_key_teams_cache_task(user_id: int) -> None:
    pass


@shared_task(ignore_result=True)
def warm_personal_api_key_deleted_cache_task(user_id: int, scoped_team_ids: list[int] | None) -> None:
    pass


@shared_task(ignore_result=True)
def warm_organization_teams_cache_task(organization_id: str, user_id: int, action: str) -> None:
    pass


@shared_task(ignore_result=True)
def warm_team_cache_task(project_token: str) -> None:
    pass


@shared_task(ignore_result=True)
def warm_all_team_access_caches_task() -> None:
    pass
