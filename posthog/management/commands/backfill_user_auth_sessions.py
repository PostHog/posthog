import time
from typing import Any

from django.contrib.auth import BACKEND_SESSION_KEY, SESSION_KEY
from django.core.management.base import BaseCommand
from django.utils import timezone

import structlog
from loginas import settings as la_settings

from posthog.constants import AUTH_BACKEND_KEYS
from posthog.models import User
from posthog.session.models import Session

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Backfill user_id (and metadata) onto existing django_session rows. Idempotent and batched."

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=2000, help="Sessions decoded per batch.")
        parser.add_argument("--sleep", type=float, default=0.1, help="Seconds to sleep between batches.")
        parser.add_argument("--dry-run", action="store_true", help="Report counts without writing rows.")

    def handle(self, *args: Any, **options: Any) -> None:
        batch_size: int = options["batch_size"]
        sleep_seconds: float = options["sleep"]
        dry_run: bool = options["dry_run"]

        scanned = 0
        updated = 0
        batch: list[Session] = []

        # Only live sessions still missing user_id: the store already attributes new/active sessions, so
        # this targets the pre-swap idle long-tail and makes re-runs no-ops instead of rewriting rows.
        # iterator() uses a server-side cursor so we never load the whole table.
        sessions = Session.objects.filter(expire_date__gt=timezone.now(), user_id__isnull=True).only(
            "session_key", "session_data"
        )
        for session in sessions.iterator(chunk_size=batch_size):
            scanned += 1
            if self._populate(session):
                batch.append(session)
            if len(batch) >= batch_size:
                updated += self._flush(batch, dry_run)
                batch = []
                if sleep_seconds:
                    time.sleep(sleep_seconds)

        if batch:
            updated += self._flush(batch, dry_run)

        logger.info("backfill_user_auth_sessions_done", scanned=scanned, updated=updated, dry_run=dry_run)
        self.stdout.write(f"Scanned {scanned} sessions, updated {updated}{' (dry run)' if dry_run else ''}.")

    def _populate(self, session: Session) -> bool:
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

    def _flush(self, batch: list[Session], dry_run: bool) -> int:
        # Drop sessions whose user no longer exists so we never attribute a row to a deleted account.
        valid_user_ids = set(User.objects.filter(id__in={s.user_id for s in batch}).values_list("id", flat=True))
        rows = [session for session in batch if session.user_id in valid_user_ids]
        if not rows or dry_run:
            return len(rows)
        # Only freshly-attributed rows reach here (the query excludes rows that already have a user_id).
        Session.objects.bulk_update(rows, ["user_id", "login_method"], batch_size=len(rows))
        return len(rows)
