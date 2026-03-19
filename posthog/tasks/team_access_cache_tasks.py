"""
No-op stubs for removed team access cache warming tasks.

Kept to avoid ImportError for tasks already enqueued in Celery.
Safe to delete once all in-flight messages have expired.
"""

from celery import shared_task

NOOP_RESULT: dict = {"status": "noop"}


@shared_task
def warm_user_teams_cache_task(user_id: int) -> dict:
    return NOOP_RESULT


@shared_task
def warm_personal_api_key_teams_cache_task(user_id: int) -> dict:
    return NOOP_RESULT


@shared_task
def warm_personal_api_key_deleted_cache_task(user_id: int, scoped_team_ids: list[int] | None) -> dict:
    return NOOP_RESULT


@shared_task
def warm_organization_teams_cache_task(organization_id: str, user_id: int, action: str) -> dict:
    return NOOP_RESULT


@shared_task
def warm_team_cache_task(project_token: str) -> dict:
    return NOOP_RESULT


@shared_task
def warm_all_team_access_caches_task() -> dict:
    return NOOP_RESULT
