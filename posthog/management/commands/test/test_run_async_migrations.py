import logging

import pytest

from django.core.management import call_command

from semantic_version.base import Version

from posthog.async_migrations.setup import ALL_ASYNC_MIGRATIONS
from posthog.constants import FROZEN_POSTHOG_VERSION

pytestmark = pytest.mark.django_db


def test_run_async_migrations_doesnt_raise():
    call_command("run_async_migrations")


def test_plan_includes_all_migrations_except_past_max_version(caplog):
    """
    Plan should give us all the migrations that haven't run. But it also should
    not return migrations that are still within the posthog_min_version,
    posthog_max_version range. This is to ensure that the application is able to
    boot within the version range and thus the administrator is able to trigger
    migrations via the UI.
    """
    call_command("run_async_migrations", "--plan")
    output = "\n".join([rec.message for rec in caplog.records])
    for migration_name, migration in ALL_ASYNC_MIGRATIONS.items():
        if FROZEN_POSTHOG_VERSION > Version(migration.posthog_max_version):
            assert migration_name in output
        else:
            assert migration_name not in output


def test_check_with_pending_migrations(caplog):
    # By default, no migrations are run, so this should raise
    with pytest.raises(SystemExit):
        call_command("run_async_migrations", "--check")

    # Ensure that it did not try to auto-complete migrations, using the first
    # migration as a test case
    call_command("run_async_migrations", "--plan")
    output = "\n".join([rec.message for rec in caplog.records])
    assert "0001" in output


def test_check_with_no_pending_migrations():
    # Running the migrations first, then checking should result in an exit
    # code of zero
    call_command("run_async_migrations")
    call_command("run_async_migrations", "--check")


def test_complete_noop_migrations(caplog):
    """
    Based on the status of `is_required` for each migration, it is possible that
    some incomplete migrations can be trivially applied by creating and marking
    the migration as complete.
    """
    # First validate the 0001 is present
    call_command("run_async_migrations", "--plan")
    output = "\n".join([rec.message for rec in caplog.records])
    assert "0001_events_sample_by" in output

    call_command("run_async_migrations", "--complete-noop-migrations")

    # And after running, it shouldn't be
    caplog.clear()
    call_command("run_async_migrations", "--plan")
    output = "\n".join([rec.message for rec in caplog.records])
    assert "0001_events_sample_by" not in output


@pytest.fixture(autouse=True)
def set_log_level(caplog):
    caplog.set_level(logging.INFO)
