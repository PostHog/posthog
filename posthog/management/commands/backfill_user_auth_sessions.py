import time
from datetime import UTC, datetime
from typing import Any

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand
from django.utils import timezone

import structlog
from loginas import settings as la_settings

from posthog.constants import AUTH_BACKEND_KEYS
from posthog.models import User, UserAuthSession

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Backfill the UserAuthSession index from existing django_session rows. Idempotent and batched."

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=2000, help="Sessions decoded per batch.")
        parser.add_argument("--sleep", type=float, default=0.1, help="Seconds to sleep between batches.")
        parser.add_argument("--dry-run", action="store_true", help="Report counts without writing rows.")

    def handle(self, *args: Any, **options: Any) -> None:
        batch_size: int = options["batch_size"]
        sleep_seconds: float = options["sleep"]
        dry_run: bool = options["dry_run"]

        scanned = 0
        indexed = 0
        batch: list[dict[str, Any]] = []

        # Only unexpired sessions; iterator() uses a server-side cursor so we never load the whole table.
        sessions = Session.objects.filter(expire_date__gt=timezone.now()).only("session_key", "session_data")
        for session in sessions.iterator(chunk_size=batch_size):
            scanned += 1
            candidate = self._candidate_from_session(session)
            if candidate is not None:
                batch.append(candidate)
            if len(batch) >= batch_size:
                indexed += self._flush(batch, dry_run)
                batch = []
                if sleep_seconds:
                    time.sleep(sleep_seconds)

        if batch:
            indexed += self._flush(batch, dry_run)

        logger.info("backfill_user_auth_sessions_done", scanned=scanned, indexed=indexed, dry_run=dry_run)
        self.stdout.write(f"Scanned {scanned} sessions, indexed {indexed} new{' (dry run)' if dry_run else ''}.")

    def _candidate_from_session(self, session: Session) -> dict[str, Any] | None:
        data = session.get_decoded()
        user_id = data.get("_auth_user_id")
        if not user_id:
            return None
        # Never index impersonation sessions — they must not appear in the impersonated user's own list.
        if la_settings.USER_SESSION_FLAG in data:
            return None

        created_epoch = data.get(settings.SESSION_COOKIE_CREATED_AT_KEY)
        created_at = datetime.fromtimestamp(created_epoch, tz=UTC) if created_epoch else timezone.now()
        backend = data.get(BACKEND_SESSION_KEY)
        return {
            "user_id": int(user_id),
            "session_key": session.session_key,
            "created_at": created_at,
            "login_method": AUTH_BACKEND_KEYS.get(backend) if backend else None,
        }

    def _flush(self, candidates: list[dict[str, Any]], dry_run: bool) -> int:
        # Filter to users that still exist so the FK insert can't fail on a deleted account.
        candidate_user_ids = {c["user_id"] for c in candidates}
        valid_user_ids = set(User.objects.filter(id__in=candidate_user_ids).values_list("id", flat=True))
        rows = [
            UserAuthSession(
                user_id=c["user_id"],
                session_key=c["session_key"],
                created_at=c["created_at"],
                last_activity=c["created_at"],
                login_method=c["login_method"],
            )
            for c in candidates
            if c["user_id"] in valid_user_ids
        ]
        if not rows:
            return 0
        # Count rows already present so we report rows actually inserted, not candidates attempted.
        # (bulk_create's return can't tell us this here: our UUID PK is set in Python, so every row
        # comes back with a PK whether or not ON CONFLICT skipped it.) Best-effort: a session indexed
        # concurrently between this count and the insert can inflate the number slightly — the written
        # data stays correct via ignore_conflicts; only the reported progress count is approximate.
        already_indexed = UserAuthSession.objects.filter(session_key__in=[row.session_key for row in rows]).count()
        newly_indexed = len(rows) - already_indexed
        if dry_run:
            return newly_indexed
        # ignore_conflicts makes this idempotent and lock-light: INSERT ... ON CONFLICT DO NOTHING.
        UserAuthSession.objects.bulk_create(rows, ignore_conflicts=True, batch_size=len(rows))
        return newly_indexed
