import logging
from functools import partial

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

import requests

from posthog.models.user import User

logger = logging.getLogger(__name__)


def delete_user_analytics(distinct_id: str, email: str) -> None:
    if not settings.POSTHOG_USER_DELETION_API_KEY:
        logger.error("User analytics deletion API key is not configured")
        return
    host = settings.POSTHOG_HOST.rstrip("/")
    if not host.startswith("https://"):
        logger.error("User analytics deletion requires an HTTPS POSTHOG_HOST")
        return
    project_url = f"{host}/api/projects/{settings.POSTHOG_PROJECT_ID}"
    headers = {"Authorization": f"Bearer {settings.POSTHOG_USER_DELETION_API_KEY}"}
    try:
        response = requests.post(
            f"{project_url}/messaging/preferences/",
            headers=headers,
            json={"identifier": email, "all_marketing": False},
            timeout=(3, 30),
            allow_redirects=False,
        )
        if response.status_code != 200:
            logger.error("User marketing opt-out failed with HTTP status %s", response.status_code)
    except requests.RequestException:
        logger.error("User marketing opt-out request failed")  # noqa: TRY400
    try:
        response = requests.post(
            f"{project_url}/persons/bulk_delete/",
            headers=headers,
            json={"distinct_ids": [distinct_id], "delete_events": True, "delete_recordings": True},
            timeout=(3, 30),
            allow_redirects=False,
        )
        if response.status_code != 202:
            logger.error("User analytics deletion failed with HTTP status %s", response.status_code)
        elif response.json().get("deletion_errors"):
            logger.error("User analytics deletion API reported partial failure")
    except (requests.RequestException, ValueError, AttributeError):
        # Request exceptions may contain credentials or identifying response data.
        logger.error("User analytics deletion request failed")  # noqa: TRY400


@receiver(post_delete, sender=User)
def queue_user_analytics_deletion(sender: type[User], instance: User, using: str, **kwargs: object) -> None:
    if not settings.CLOUD_DEPLOYMENT or not instance.distinct_id:
        return
    transaction.on_commit(
        partial(delete_user_analytics, instance.distinct_id, instance.email), using=using, robust=True
    )
