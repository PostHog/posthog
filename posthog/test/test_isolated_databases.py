import time
from copy import deepcopy
from uuid import uuid4

import pytest

from django.conf import settings
from django.test import override_settings

from posthog.test.isolated_databases import (
    IsolatedRunConflict,
    SharedDatabaseBusy,
    _clone_database,
    configure_product_test_databases,
    isolated_run,
)


@pytest.mark.parametrize(
    "database", [None, "test_posthog_gw0", "test_posthog_iso_producttest", "test_posthog_iso_producttest_gw0"]
)
def test_product_databases_follow_the_default_test_database(database: str | None) -> None:
    databases = deepcopy(settings.DATABASES)
    databases["default"]["NAME"] = "posthog"
    databases["default"]["TEST"]["NAME"] = database

    with override_settings(DATABASES=databases):
        configure_product_test_databases()

    expected = f"{database or 'test_posthog'}_warehouse_sources_queue"
    assert databases["warehouse_sources_queue_db_writer"]["TEST"]["NAME"] == expected


def test_isolated_run_refuses_a_second_run_and_releases_its_lock() -> None:
    name = uuid4().hex[:16]
    databases = deepcopy(settings.DATABASES)
    databases["default"]["TEST"]["NAME"] = f"test_posthog_iso_{name}"

    with override_settings(DATABASES=databases, TEST_ISOLATION_NAME=name):
        with isolated_run():
            with pytest.raises(IsolatedRunConflict):
                with isolated_run():
                    pytest.fail("A second run acquired the same databases")
        with isolated_run() as connection:
            assert connection.execute("SELECT 1").fetchone() == (1,)


def test_clone_stops_when_the_shared_database_stays_in_use() -> None:
    name = uuid4().hex[:16]
    database = f"test_posthog_iso_{name}"
    databases = deepcopy(settings.DATABASES)
    databases["default"]["TEST"]["NAME"] = database

    with override_settings(DATABASES=databases, TEST_ISOLATION_NAME=name), isolated_run() as connection:
        # The run's own connection keeps the postgres database in use, so the template never frees up.
        with pytest.raises(SharedDatabaseBusy):
            _clone_database(connection, database, "postgres", time.monotonic(), lambda _: None)
        created = connection.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,)).fetchone()
        assert created is None
