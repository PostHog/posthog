"""Readiness probe for the evaluation fleet's database role.

The platform records its own state in the shared alert tables, so a role that can read them but
not write them is not ready. A connectivity check alone reports such a role as healthy, and the
first sign of the missing grant is then every write failing.
"""

from posthog.models.utils import execute_with_timeout
from posthog.temporal.common.utils import close_db_connections

from products.alerts.backend.models import PlatformAlert, PlatformAlertConfiguration

# What `record_outcomes` needs on every table it touches: it creates runtime rows and updates
# both the alert state and the configuration's schedule.
REQUIRED_PRIVILEGES = ("INSERT", "UPDATE")

# One statement, so the probe still proves the connection works. `current_schemas(false)` keeps
# the answer to the tables the role's own search path resolves, which is what a write resolves.
PRIVILEGE_SQL = """
SELECT c.relname,
       has_table_privilege(c.oid, 'INSERT'),
       has_table_privilege(c.oid, 'UPDATE')
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relname = ANY(%s) AND n.nspname = ANY(current_schemas(false))
"""


class WriteReadinessError(Exception):
    """The role reaches the database but cannot write a table the platform owns."""


def required_tables() -> tuple[str, ...]:
    return (PlatformAlertConfiguration._meta.db_table, PlatformAlert._meta.db_table)


def _missing_privileges(granted: dict[str, tuple[bool, ...]]) -> list[str]:
    missing = []
    for table in required_tables():
        privileges = granted.get(table)
        if privileges is None:
            missing.append(f"{table} (not visible)")
            continue
        lacking = [name for name, held in zip(REQUIRED_PRIVILEGES, privileges, strict=True) if not held]
        if lacking:
            missing.append(f"{table} ({', '.join(lacking)})")
    return missing


# Force-close in the database thread to avoid a cleanup health-check query after failure.
@close_db_connections
def check_postgres_connection() -> None:
    with execute_with_timeout(1000, database="default") as cursor:
        cursor.execute(PRIVILEGE_SQL, [list(required_tables())])
        granted = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}
    missing = _missing_privileges(granted)
    if missing:
        raise WriteReadinessError(f"The database role cannot write: {'; '.join(missing)}")
