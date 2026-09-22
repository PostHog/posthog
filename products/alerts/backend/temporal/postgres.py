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

# One statement, so the probe still proves the connection works. `to_regclass` resolves a name
# the way an unqualified write resolves it, so the row reports the relation the ORM would reach
# rather than a same-named table in another schema. It returns null for a name the role cannot
# see, and the privilege functions are strict, so both privileges come back null with it.
PRIVILEGE_SQL = """
SELECT requested.table_name,
       pg_catalog.has_table_privilege(pg_catalog.to_regclass(requested.table_name), 'INSERT'),
       pg_catalog.has_table_privilege(pg_catalog.to_regclass(requested.table_name), 'UPDATE')
FROM pg_catalog.unnest(%s::text[]) AS requested(table_name)
"""


class WriteReadinessError(Exception):
    """The role reaches the database but cannot write a table the platform owns."""


def required_tables() -> tuple[str, ...]:
    return (PlatformAlertConfiguration._meta.db_table, PlatformAlert._meta.db_table)


def _missing_privileges(granted: dict[str, tuple[bool | None, ...]]) -> list[str]:
    missing = []
    for table in required_tables():
        privileges = granted.get(table)
        if privileges is None or None in privileges:
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
        granted = {row[0]: row[1:] for row in cursor.fetchall()}
    missing = _missing_privileges(granted)
    if missing:
        raise WriteReadinessError(f"The database role cannot write: {'; '.join(missing)}")
