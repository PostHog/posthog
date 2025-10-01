import pytest

from django.db import connection


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    """
    Create PostgreSQL extensions for xdist worker databases.

    With --nomigrations and xdist, each worker creates its own test database
    (e.g., test_posthog_gw0), but extensions aren't created since migrations
    don't run. This fixture runs once per worker to create the extensions.
    """
    with django_db_blocker.unblock():
        with connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            cursor.execute("CREATE EXTENSION IF NOT EXISTS ltree")
