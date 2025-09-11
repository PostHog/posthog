from posthog.async_migrations.definition import (
    AsyncMigrationDefinition,
    AsyncMigrationOperation,
    AsyncMigrationOperationSQL,
)
from posthog.constants import AnalyticsDBMS

# For testing purposes


class SideEffects:
    def __init__(self):
        self.reset_count()

    def reset_count(self):
        self.side_effect_count = 0
        self.side_effect_rollback_count = 0

    def side_effect(self, _):
        self.side_effect_count += 1
        return

    def side_effect_rollback(self, _):
        self.side_effect_rollback_count += 1
        return


class Migration(AsyncMigrationDefinition):
    # For testing only!!
    fail = False
    error_message = "Healthcheck failed"

    description = "Another example async migration that's less realistic and used in tests."

    sec = SideEffects()

    operations = [
        AsyncMigrationOperationSQL(
            database=AnalyticsDBMS.POSTGRES,
            sql="CREATE TABLE test_async_migration ( key VARCHAR, value VARCHAR )",
            rollback="DROP TABLE test_async_migration",
        ),
        AsyncMigrationOperation(fn=sec.side_effect, rollback_fn=sec.side_effect_rollback),
        AsyncMigrationOperationSQL(
            database=AnalyticsDBMS.POSTGRES,
            sql="INSERT INTO test_async_migration (key, value) VALUES ('a', 'b')",
            rollback="TRUNCATE TABLE test_async_migration",
        ),
        AsyncMigrationOperationSQL(database=AnalyticsDBMS.POSTGRES, sql="SELECT pg_sleep(1)", rollback=None),
        AsyncMigrationOperation(fn=sec.side_effect, rollback_fn=sec.side_effect_rollback),
        AsyncMigrationOperationSQL(
            database=AnalyticsDBMS.POSTGRES,
            sql="UPDATE test_async_migration SET value='c' WHERE key='a'",
            rollback="UPDATE test_async_migration SET value='b' WHERE key='a'",
        ),
        AsyncMigrationOperation(fn=sec.side_effect, rollback_fn=sec.side_effect_rollback),
    ]

    def healthcheck(self):
        if self.fail:
            return (False, self.error_message)

        return (True, None)
