from copy import deepcopy
from uuid import uuid4

import pytest

from django.conf import settings
from django.test import override_settings

from posthog.test.isolated_databases import IsolatedRunConflict, configure_isolated_product_databases, isolated_run


@pytest.mark.parametrize("worker", ["", "_gw0"])
def test_product_databases_follow_the_default_test_database(worker: str) -> None:
    databases = deepcopy(settings.DATABASES)
    database = f"test_posthog_iso_producttest{worker}"
    databases["default"]["TEST"]["NAME"] = database

    with override_settings(DATABASES=databases):
        configure_isolated_product_databases()

    assert databases["warehouse_sources_queue_db_writer"]["TEST"]["NAME"] == f"{database}_warehouse_sources_queue"


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
