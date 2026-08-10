import time
import hashlib

from django.db import connection

# Ticket numbering has no IntegrityError retry, so this lock must block until allocation is safe.
_TICKET_NUMBER_NAMESPACE = 0x0C0F_5E71

# Keep the idle-in-transaction window bounded on this public endpoint.
_SESSION_LOCK_ATTEMPTS = 5
_SESSION_LOCK_BACKOFF_SECONDS = 0.1


def _ensure_in_transaction() -> None:
    if not connection.in_atomic_block:
        raise RuntimeError("Conversation advisory locks require transaction.atomic()")


def lock_ticket_numbering(team_id: int) -> None:
    """Serialize ticket_number allocation for a team. Call inside transaction.atomic()."""
    _ensure_in_transaction()
    with connection.cursor() as cursor:
        # Ticket inserts take this lock for their team foreign key. Taking it before the
        # advisory lock prevents inversion with Team FOR UPDATE callers that create tickets.
        # Callers must not upgrade the Team row to FOR UPDATE later in this transaction,
        # because an earlier FOR UPDATE waiter can deadlock with that lock upgrade.
        cursor.execute("SELECT id FROM posthog_team WHERE id = %s FOR KEY SHARE", [team_id])
        cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [_TICKET_NUMBER_NAMESPACE, team_id])


def try_lock_widget_session(team_id: int, widget_session_id: str) -> bool:
    """
    Try to take the per-widget-session create lock, with a short retry.

    Callers must fail without writing when this returns False. Using lock_timeout
    would abort the transaction with 55P03 instead of allowing a controlled response.

    The single-bigint key space is separate from the two-int numbering lock above.
    Call inside transaction.atomic(); the lock releases on commit/rollback.
    """
    _ensure_in_transaction()
    key = f"conversations-widget-session:{team_id}:{widget_session_id}"
    lock_id = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], byteorder="big", signed=True)

    for attempt in range(_SESSION_LOCK_ATTEMPTS):
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_xact_lock(%s)", [lock_id])
            row = cursor.fetchone()
        if row is not None and row[0]:
            return True
        if attempt < _SESSION_LOCK_ATTEMPTS - 1:
            time.sleep(_SESSION_LOCK_BACKOFF_SECONDS)
    return False
