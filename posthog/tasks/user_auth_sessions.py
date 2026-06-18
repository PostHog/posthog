from django.contrib.sessions.models import Session
from django.db.models import Exists, OuterRef
from django.utils import timezone

import structlog
from celery import shared_task

from posthog.models import UserAuthSession
from posthog.scoping_audit import skip_team_scope_audit

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, soft_time_limit=300, time_limit=360)
@skip_team_scope_audit
def cleanup_user_auth_sessions() -> int:
    """Delete UserAuthSession rows whose backing django_session is gone or expired.

    The activity middleware only ever creates rows; logout and natural expiry remove the django_session
    row but not the index row, so this periodic sweep keeps the index from accumulating dead entries.
    """
    # Anti-join (NOT EXISTS) rather than NOT IN against the whole session table — it stays indexed and
    # can short-circuit per row as django_session grows.
    live_session = Session.objects.filter(session_key=OuterRef("session_key"), expire_date__gt=timezone.now())
    deleted, _ = UserAuthSession.objects.exclude(Exists(live_session)).delete()
    if deleted:
        logger.info("cleanup_user_auth_sessions_done", deleted=deleted)
    return deleted
