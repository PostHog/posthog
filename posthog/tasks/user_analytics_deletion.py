from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

import requests
from celery import shared_task

from posthog.celery_queues import CeleryQueue
from posthog.scoping_audit import skip_team_scope_audit


class UserAnalyticsDeletionFailed(Exception):
    pass


def _deletion_url() -> str:
    host = settings.POSTHOG_HOST.rstrip("/")
    parsed = urlsplit(host)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
        or settings.POSTHOG_PROJECT_ID <= 0
        or not settings.POSTHOG_USER_DELETION_API_KEY
    ):
        raise ImproperlyConfigured("PostHog user analytics deletion requires an HTTPS origin, project ID and API key")
    return f"{host}/api/projects/{settings.POSTHOG_PROJECT_ID}/persons/bulk_delete/"


def _request_deletion(url: str, distinct_ids: list[str], *, keep_person: bool) -> None:
    try:
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {settings.POSTHOG_USER_DELETION_API_KEY}"},
            json={
                "distinct_ids": distinct_ids,
                "delete_events": keep_person,
                "delete_recordings": True,
                "keep_person": keep_person,
            },
            timeout=(3, 30),
            allow_redirects=False,
        )
    except requests.RequestException:
        # Request exceptions can contain the credential and identifying response data.
        raise UserAnalyticsDeletionFailed("request_failed") from None

    if response.status_code != 202:
        raise UserAnalyticsDeletionFailed(f"http_{response.status_code}")
    try:
        result = response.json()
    except ValueError:
        raise UserAnalyticsDeletionFailed("invalid_response") from None
    if not isinstance(result, dict):
        raise UserAnalyticsDeletionFailed("invalid_response")
    found = result.get("persons_found")
    deleted = result.get("persons_deleted", 0)
    queued = result.get("persons_queued_for_deletion", 0)
    if (
        type(found) is not int
        or type(deleted) is not int
        or type(queued) is not int
        or not 0 <= found <= len(distinct_ids)
        or deleted < 0
        or queued < 0
        or deleted + queued != (0 if keep_person else found)
        or result.get("deletion_errors") != []
        or (
            found
            and (
                (keep_person and result.get("events_queued_for_deletion") is not True)
                or result.get("recordings_queued_for_deletion") is not True
            )
        )
    ):
        raise UserAnalyticsDeletionFailed("incomplete_deletion")


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.LONG_RUNNING.value,
    autoretry_for=(UserAnalyticsDeletionFailed, ImproperlyConfigured),
    retry_backoff=60,
    retry_backoff_max=3600,
    max_retries=24,
    acks_late=True,
    reject_on_worker_lost=True,
)
@skip_team_scope_audit
def delete_user_analytics(distinct_id: str) -> None:
    if not settings.CLOUD_DEPLOYMENT:
        return
    url = _deletion_url()
    # The sync API removes profiles before queueing events, so preserve identity resolution first.
    _request_deletion(url, [distinct_id], keep_person=True)
    # Async workers can run out of order; this worker must queue replays before removing the profile too.
    _request_deletion(url, [distinct_id], keep_person=False)
