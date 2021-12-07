def special_migrations_ok() -> bool:
    from posthog.models.special_migration import MigrationStatus, SpecialMigration
    from posthog.special_migrations.runner import is_migration_in_range

    for migration in SpecialMigration.objects.all():
        migration_completed_or_running = migration.status in [
            MigrationStatus.CompletedSuccessfully,
            MigrationStatus.Running,
        ]
        migration_in_range = is_migration_in_range(migration.posthog_min_version, migration.posthog_max_version)

        if not migration_completed_or_running and migration_in_range:
            return False

    return True
