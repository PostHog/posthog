def async_migrations_ok() -> bool:
    from posthog.models.async_migration import AsyncMigration, MigrationStatus

    from products.async_migrations.backend.runner import is_posthog_version_compatible

    for migration in AsyncMigration.objects.all():
        migration_completed_or_running = migration.status in [
            MigrationStatus.CompletedSuccessfully,
            MigrationStatus.Running,
        ]
        migration_in_range = is_posthog_version_compatible(migration.posthog_min_version, migration.posthog_max_version)

        if not migration_completed_or_running and migration_in_range:
            return False

    return True
