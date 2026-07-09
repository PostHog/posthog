import time
from dataclasses import dataclass

from django.contrib.auth import BACKEND_SESSION_KEY, SESSION_KEY
from django.utils import timezone

import structlog
from loginas import settings as la_settings

from posthog.constants import AUTH_BACKEND_KEYS
from posthog.models import User
from posthog.session.models import Session

logger = structlog.get_logger(__name__)


@dataclass
class BackfillStats:
    scanned: int = 0
    updated: int = 0


def _populate(session: Session) -> bool:
    """Set user_id (and metadata) on the session from its decoded data. Returns False to skip it."""
    data = session.get_decoded()
    user_id = data.get(SESSION_KEY)
    if not user_id:
        return False
    # Never attribute impersonation sessions — they must not appear in the impersonated user's list.
    if la_settings.USER_SESSION_FLAG in data:
        return False

    session.user_id = int(user_id)
    backend = data.get(BACKEND_SESSION_KEY)
    method = AUTH_BACKEND_KEYS.get(backend) if backend else None
    session.login_method = method if isinstance(method, str) else None
    return True


def _flush(batch: list[Session], dry_run: bool) -> int:
    # Drop sessions whose user no longer exists so we never attribute a row to a deleted account.
    valid_user_ids = set(User.objects.filter(id__in={s.user_id for s in batch}).values_list("id", flat=True))
    rows = [session for session in batch if session.user_id in valid_user_ids]
    if not rows or dry_run:
        return len(rows)
    # Only freshly-attributed rows reach here (the query excludes rows that already have a user_id).
    Session.objects.bulk_update(rows, ["user_id", "login_method"], batch_size=len(rows))
    return len(rows)


def backfill_session_user_ids(
    *, batch_size: int = 2000, sleep_seconds: float = 0.1, dry_run: bool = False
) -> BackfillStats:
    """Backfill user_id (and login_method) onto existing django_session rows. Idempotent and batched."""
    stats = BackfillStats()
    batch: list[Session] = []

    # Only live sessions still missing user_id: the store already attributes new/active sessions, so
    # this targets the pre-swap idle long-tail and makes re-runs no-ops instead of rewriting rows.
    # iterator() uses a server-side cursor so we never load the whole table.
    sessions = Session.objects.filter(expire_date__gt=timezone.now(), user_id__isnull=True).only(
        "session_key", "session_data"
    )
    for session in sessions.iterator(chunk_size=batch_size):
        stats.scanned += 1
        if _populate(session):
            batch.append(session)
        if len(batch) >= batch_size:
            stats.updated += _flush(batch, dry_run)
            batch = []
            if sleep_seconds:
                time.sleep(sleep_seconds)

    if batch:
        stats.updated += _flush(batch, dry_run)

    logger.info("backfill_user_auth_sessions_done", scanned=stats.scanned, updated=stats.updated, dry_run=dry_run)
    return stats
