import os
from urllib.parse import quote_plus

from django.conf import settings


def _dsn_from_django_settings(alias: str) -> str | None:
    """Build a libpq connection string from a configured Django database alias.

    Returns None if the alias isn't configured. Reads the live settings dict so it
    picks up the test database NAME that pytest-django/conftest rewrites at runtime
    (the persons tables only exist in the test_<name>_persons database, reachable
    via the persons_db_reader / persons_db_writer aliases).
    """
    db = settings.DATABASES.get(alias)
    if not db:
        return None
    user = db.get("USER", "")
    password = db.get("PASSWORD", "")
    host = db.get("HOST", "localhost")
    port = db.get("PORT", "5432")
    name = db.get("NAME", "")
    if password:
        return f"postgres://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{name}"
    return f"postgres://{quote_plus(user)}@{host}:{port}/{name}"


def get_persons_database_url(*, writer: bool = False) -> str:
    """Raw psycopg connection string for the persons database.

    Not routed through Django DATABASES — for use in Temporal activities,
    Dagster ops, and management commands that need direct DB access.

    Resolution order:
    1. Explicit env URL (PERSONS_DB_WRITER_URL / PERSONS_DB_READER_URL).
    2. The matching Django database alias (persons_db_writer / persons_db_reader),
       which is configured for separate-persons-DB deployments and for tests.
    3. DATABASE_URL fallback for single-DB / hobby deployments.
    """
    if writer:
        url = os.getenv("PERSONS_DB_WRITER_URL") or _dsn_from_django_settings("persons_db_writer")
    else:
        url = (
            os.getenv("PERSONS_DB_READER_URL")
            or os.getenv("PERSONS_DB_WRITER_URL")
            or _dsn_from_django_settings("persons_db_reader")
            or _dsn_from_django_settings("persons_db_writer")
        )
    # Fall back to DATABASE_URL for single-DB / hobby deployments that don't
    # configure a separate persons database (mirrors the previous inline helper).
    url = url or os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "Persons database URL not configured. Set PERSONS_DB_WRITER_URL, PERSONS_DB_READER_URL, or DATABASE_URL."
        )
    return url
