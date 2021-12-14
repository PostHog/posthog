from posthog.async_migrations.definition import AsyncMigrationDefinition, AsyncMigrationOperation
from posthog.constants import AnalyticsDBMS


# For testing purposes
class Migration(AsyncMigrationDefinition):

    # For testing only!!
    fail = False
    error_message = "Healthcheck failed"

    description = "Another example async migration that's less realistic and used in tests."

    operations = [
        AsyncMigrationOperation(
            database=AnalyticsDBMS.POSTGRES,
            sql="CREATE TABLE test_async_migration ( key VARCHAR, value VARCHAR )",
            rollback="DROP TABLE test_async_migration",
        ),
        AsyncMigrationOperation(
            database=AnalyticsDBMS.POSTGRES,
            sql="INSERT INTO test_async_migration (key, value) VALUES ('a', 'b')",
            rollback="TRUNCATE TABLE test_async_migration",
        ),
        AsyncMigrationOperation(database=AnalyticsDBMS.POSTGRES, sql="SELECT pg_sleep(1)", rollback="", resumable=True),
        AsyncMigrationOperation(
            database=AnalyticsDBMS.POSTGRES,
            sql="UPDATE test_async_migration SET value='c' WHERE key='a'",
            rollback="UPDATE test_async_migration SET value='b' WHERE key='a'",
            resumable=True,  # why? because 'update where' queries can safely be re-run
        ),
    ]

    def healthcheck(self):
        if self.fail:
            return (False, self.error_message)

        return (True, None)
