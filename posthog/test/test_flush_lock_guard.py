import pytest

from django.core.management import call_command
from django.db import connections

import psycopg

import posthog.conftest as root_conftest


@pytest.mark.django_db(transaction=True)
def test_flush_terminates_idle_in_transaction_blocker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(root_conftest, "FLUSH_LOCK_TIMEOUT_SECONDS", 1)

    settings_dict = connections["default"].settings_dict
    connect_kwargs = {
        "dbname": settings_dict["NAME"],
        "user": settings_dict["USER"],
        "password": settings_dict["PASSWORD"],
        "host": settings_dict["HOST"],
        "port": settings_dict["PORT"],
    }
    blocker = psycopg.connect(**{key: value for key, value in connect_kwargs.items() if value})
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
