import os


def get_persons_database_url(*, writer: bool = False) -> str:
    """Raw psycopg connection string for the persons database.

    Not routed through Django DATABASES — for use in Temporal activities,
    Dagster ops, and management commands that need direct DB access.
    """
    if writer:
        url = os.getenv("PERSONS_DB_WRITER_URL")
    else:
        url = os.getenv("PERSONS_DB_READER_URL") or os.getenv("PERSONS_DB_WRITER_URL")
    if not url:
        raise RuntimeError(
            "Persons database URL not configured. Set PERSONS_DB_WRITER_URL and/or PERSONS_DB_READER_URL."
        )
    return url
