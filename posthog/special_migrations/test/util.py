from posthog.models.special_migration import MigrationStatus, SpecialMigration


def create_special_migration(
    name="test1",
    description="my desc",
    posthog_min_version="1.0.0",
    posthog_max_version="100000.0.0",
    status=MigrationStatus.NotStarted,
    last_error="",
):
    return SpecialMigration.objects.create(
        name=name,
        description=description,
        posthog_min_version=posthog_min_version,
        posthog_max_version=posthog_max_version,
        status=status,
        last_error=last_error,
    )
