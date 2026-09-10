from posthog.models.utils import execute_with_timeout
from posthog.temporal.common.utils import close_db_connections


# Force-close in the database thread to avoid a cleanup health-check query after failure.
@close_db_connections
def check_postgres_connection() -> None:
    with execute_with_timeout(1000, database="default") as cursor:
        cursor.execute("SELECT 1")
        if cursor.fetchone() != (1,):
            raise ValueError("Unexpected Postgres probe result")
