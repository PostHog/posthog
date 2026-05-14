from posthog.async_migrations.definition import AsyncMigrationDefinition, AsyncMigrationOperation

# For testing purposes


def raise_exception_fn(_):
    raise Exception("Test rollback Exception")


class Migration(AsyncMigrationDefinition):
    # For testing only!!
    description = "Another example async migration that's less realistic and used in tests."

    @property
    def operations(self) -> list[AsyncMigrationOperation]:
        return [
            AsyncMigrationOperation(fn=lambda _: None),
            AsyncMigrationOperation(fn=lambda _: None, rollback_fn=raise_exception_fn),
            AsyncMigrationOperation(fn=lambda _: None),
        ]
