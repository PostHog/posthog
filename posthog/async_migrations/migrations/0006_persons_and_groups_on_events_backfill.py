from posthog.async_migrations.definition import AsyncMigrationDefinition, AsyncMigrationOperation

"""
Nooping this migration for future compatibility. Superseded by 0007_persons_and_groups_on_events_backfill.

If users ran the old version of this, they will be ok to run 0007, if not, they will also be ok to run it.
"""


class Migration(AsyncMigrationDefinition):
    description = "No-op migration"

    posthog_max_version = "1.41.99"

    depends_on = "0005_person_replacing_by_version"

    operations: list[AsyncMigrationOperation] = []

    def is_required(self):
        return False
