from django.core.management.commands import migrate


def pytest_configure(config):
    """
    Hook into Django's migrate command to create PostgreSQL extensions.

    When --nomigrations is used with pytest-xdist, each worker creates its own
    test database (e.g., test_posthog_gw0), but migrations don't run, so
    extensions like ltree and pg_trgm aren't created. This patches the migrate
    command to ensure extensions exist before creating tables.
    """

    class MigrateWithExtensions(migrate.Command):
        def handle(self, *args, **kwargs):
            from django.db import connection

            # Create extensions before migrations/table creation
            with connection.cursor() as cursor:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
                cursor.execute("CREATE EXTENSION IF NOT EXISTS ltree")

            return super().handle(*args, **kwargs)

    # Patch the migrate command globally for all test databases
    migrate.Command = MigrateWithExtensions  # type: ignore
