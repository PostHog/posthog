from posthog.constants import AnalyticsDBMS
from posthog.special_migrations.definition import SpecialMigrationDefinition, SpecialMigrationOperation


# For testing purposes
class Migration(SpecialMigrationDefinition):

    description = "Another example special migration that's less realistic and used in tests."

    posthog_min_version = "1.28.0"
    posthog_max_version = "1.35.0"

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
        SpecialMigrationOperation(database=AnalyticsDBMS.POSTGRES, sql="SELECT pg_sleep(10)", rollback="",),
        SpecialMigrationOperation(
            database=AnalyticsDBMS.POSTGRES,
            sql="UPDATE test_special_migration SET value='c' WHERE key='a'",
            rollback="UPDATE test_special_migration SET value='b' WHERE key='a'",
        ),
    ]

    def healthcheck(self):
        if self.fail:
            return (False, self.error_message)

        return (True, None)
