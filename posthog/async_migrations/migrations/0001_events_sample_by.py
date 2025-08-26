from posthog.async_migrations.definition import AsyncMigrationDefinition, AsyncMigrationOperation

"""
Nooping this migration for future compatibility. Superseded by 0002_events_sample_by.

If users ran the old version of this, they will be ok to run 0002, if not, they will also be ok to run it.
"""


class Migration(AsyncMigrationDefinition):
    description = "Test migration"

    posthog_max_version = "1.33.9"

    operations: list[AsyncMigrationOperation] = []

    def is_required(self):
        return False
