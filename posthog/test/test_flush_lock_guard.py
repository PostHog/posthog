import pytest

from django.db import connections

import psycopg

from posthog.test import flush_lock_guard


@pytest.mark.django_db(transaction=True)
def test_flush_terminates_idle_in_transaction_blocker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(flush_lock_guard, "FLUSH_LOCK_TIMEOUT_SECONDS", 1)

    default = connections["default"]
    # Dedicated table so the guarded flush contends only with our blocker; Django's real flush
    # truncates every table and races unrelated transactions under the tight 1s timeout. (The
    # guard's wiring into Django's teardown flush is covered by conftest; here we isolate the retry.)
    with default.cursor() as cursor:
        cursor.execute("CREATE TABLE IF NOT EXISTS flush_lock_guard_probe (id integer)")

    blocker = psycopg.connect(**default.get_connection_params())
    try:
        # Open transaction holds ACCESS SHARE, blocking TRUNCATE — the state a leaked session leaves behind.
        blocker.execute("SELECT 1 FROM flush_lock_guard_probe")

        def flush() -> None:
            with default.cursor() as cursor:
                cursor.execute("TRUNCATE flush_lock_guard_probe")

        with pytest.warns(UserWarning, match="idle-in-transaction"):
            flush_lock_guard.flush_with_lock_guard("default", flush)

        with pytest.raises(psycopg.OperationalError):
            blocker.execute("SELECT 1")
    finally:
        blocker.close()
        with default.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS flush_lock_guard_probe")
