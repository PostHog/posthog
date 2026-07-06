import pytest

from django.core.management import call_command
from django.db import connections

import psycopg

from posthog.test import flush_lock_guard


@pytest.mark.django_db(transaction=True)
def test_flush_terminates_idle_in_transaction_blocker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(flush_lock_guard, "FLUSH_LOCK_TIMEOUT_SECONDS", 1)

    blocker = psycopg.connect(**connections["default"].get_connection_params())
    try:
        # An open transaction holding ACCESS SHARE on a flushed table blocks TRUNCATE's
        # ACCESS EXCLUSIVE lock — the state a leaked background-thread session leaves behind.
        blocker.execute("SELECT 1 FROM posthog_organization")

        with pytest.warns(UserWarning, match="idle-in-transaction"):
            call_command(
                "flush",
                verbosity=0,
                interactive=False,
                database="default",
                reset_sequences=False,
                # pytest-django's own teardown flush re-runs post_migrate right after this
                # test; skipping it here avoids a duplicate contenttypes/permissions re-sync.
                inhibit_post_migrate=True,
            )

        with pytest.raises(psycopg.OperationalError):
            blocker.execute("SELECT 1")
    finally:
        blocker.close()
