from datetime import datetime

import pytest
from infi.clickhouse_orm import Database

from ee.clickhouse.client import sync_execute
from posthog.settings import (
    CLICKHOUSE_DATABASE,
    CLICKHOUSE_HTTP_URL,
    CLICKHOUSE_PASSWORD,
    CLICKHOUSE_USER,
    CLICKHOUSE_VERIFY,
)
from posthog.test.base import TestMixin


def reset_clickhouse_tables():
    # Reset clickhouse tables to default before running test
    # Mostly so that test runs locally work correctly
    from ee.clickhouse.sql.cohort import CREATE_COHORTPEOPLE_TABLE_SQL, DROP_COHORTPEOPLE_TABLE_SQL
    from ee.clickhouse.sql.events import DROP_EVENTS_TABLE_SQL, EVENTS_TABLE_SQL
    from ee.clickhouse.sql.person import (
        DROP_PERSON_DISTINCT_ID_TABLE_SQL,
        DROP_PERSON_STATIC_COHORT_TABLE_SQL,
        DROP_PERSON_TABLE_SQL,
        PERSON_STATIC_COHORT_TABLE_SQL,
        PERSONS_DISTINCT_ID_TABLE_SQL,
        PERSONS_TABLE_SQL,
    )
    from ee.clickhouse.sql.plugin_log_entries import DROP_PLUGIN_LOG_ENTRIES_TABLE_SQL, PLUGIN_LOG_ENTRIES_TABLE_SQL
    from ee.clickhouse.sql.session_recording_events import (
        DROP_SESSION_RECORDING_EVENTS_TABLE_SQL,
        SESSION_RECORDING_EVENTS_TABLE_SQL,
    )

    # REMEMBER TO ADD ANY NEW CLICKHOUSE TABLES TO THIS ARRAY!
    TABLES_TO_CREATE_DROP = [
        (DROP_EVENTS_TABLE_SQL, EVENTS_TABLE_SQL),
        (DROP_PERSON_TABLE_SQL, PERSONS_TABLE_SQL),
        (DROP_PERSON_DISTINCT_ID_TABLE_SQL, PERSONS_DISTINCT_ID_TABLE_SQL),
        (DROP_PERSON_STATIC_COHORT_TABLE_SQL, PERSON_STATIC_COHORT_TABLE_SQL),
        (DROP_SESSION_RECORDING_EVENTS_TABLE_SQL, SESSION_RECORDING_EVENTS_TABLE_SQL),
        (DROP_PLUGIN_LOG_ENTRIES_TABLE_SQL, PLUGIN_LOG_ENTRIES_TABLE_SQL),
        (DROP_COHORTPEOPLE_TABLE_SQL, CREATE_COHORTPEOPLE_TABLE_SQL),
    ]
    for item in TABLES_TO_CREATE_DROP:
        try:
            sync_execute(item[0])
        except Exception as e:
            pass
        try:
            sync_execute(item[1])
        except Exception as e:
            pass


@pytest.fixture(scope="package")
def django_db_setup(django_db_setup, django_db_keepdb):
    database = Database(
        CLICKHOUSE_DATABASE,
        db_url=CLICKHOUSE_HTTP_URL,
        username=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASSWORD,
        verify_ssl_cert=CLICKHOUSE_VERIFY,
    )

    if not django_db_keepdb:
        try:
            database.drop_database()
        except:
            pass

    if not django_db_keepdb or not database.db_exists:
        database.create_database()

    reset_clickhouse_tables()

    yield

    if not django_db_keepdb:
        try:
            database.drop_database()
        except:
            pass


@pytest.fixture(scope="session")
def django_db_modify_db_settings_xdist_suffix(request, worker_id):
    """This fixture will generate and add a unique suffix to the database name when tests are run via pytest-xdist."""
    # Put a suffix like _gw0, _gw1 on xdist processes + timestamp.
    if worker_id != "master":
        _add_suffix_to_test_databases(suffix=f'{worker_id}_{datetime.now().strftime("%M%S%f")}')


def _add_suffix_to_test_databases(suffix):
    """This function adds a unique suffix to the database name."""

    from django.conf import settings

    for db_settings in settings.DATABASES.values():
        test_name = db_settings.get("TEST", {}).get("NAME")

        # Nothing to do for in-memory database.
        if test_name == ":memory:":
            continue

        # If None, append 'test_' to the database name.
        if test_name is None:
            test_name = f'test_{db_settings["NAME"]}'

        # Append timestamp to the database name to prevent conflicts (multiple users running the tests).
        db_settings.setdefault("TEST", {})
        db_settings["TEST"]["NAME"] = f"{test_name}_{suffix}"


@pytest.fixture
def base_test_mixin_fixture():
    kls = TestMixin()
    kls.setUp()
    kls.setUpTestData()

    return kls


@pytest.fixture
def team(base_test_mixin_fixture):
    return base_test_mixin_fixture.team
