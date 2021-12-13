from posthog.constants import AnalyticsDBMS
from posthog.special_migrations.definition import SpecialMigrationDefinition, SpecialMigrationOperation


# For testing purposes
class Migration(SpecialMigrationDefinition):

    # For testing only!!
    fail = False
    error_message = "Healthcheck failed"

    description = "Another example special migration that's less realistic and used in tests."

    operations = [
        SpecialMigrationOperation(
            database=AnalyticsDBMS.POSTGRES,
            sql="CREATE TABLE test_special_migration ( key VARCHAR, value VARCHAR )",
            rollback="DROP TABLE test_special_migration",
        ),
        SpecialMigrationOperation(
            database=AnalyticsDBMS.POSTGRES,
            sql="INSERT INTO test_special_migration (key, value) VALUES ('a', 'b')",
            rollback="TRUNCATE TABLE test_special_migration",
        ),
        SpecialMigrationOperation(
            database=AnalyticsDBMS.POSTGRES, sql="SELECT pg_sleep(1)", rollback="", resumable=True
        ),
        SpecialMigrationOperation(
            database=AnalyticsDBMS.POSTGRES,
            sql="UPDATE test_special_migration SET value='c' WHERE key='a'",
            rollback="UPDATE test_special_migration SET value='b' WHERE key='a'",
            resumable=True,  # why? because 'update where' queries can safely be re-run
        ),
    ]

    def healthcheck(self):
        if self.fail:
            return (False, self.error_message)

        return (True, None)
