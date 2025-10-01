def pytest_load_initial_conftests(early_config, parser, args):
    """
    Patch Django's migrate command to create PostgreSQL extensions.

    This runs very early in pytest startup, before any database setup.
    When --nomigrations is used with pytest-xdist, each worker creates its own
    test database (e.g., test_posthog_gw0), but migrations don't run, so
    extensions like ltree and pg_trgm aren't created.

    This matches the approach in posthog/management/commands/setup_test_environment.py
    """
    from django.core.management.commands import migrate

    class MigrateSilentCommand(migrate.Command):
        def handle(self, *args, **kwargs):
            from django.db import connection

            # Create extensions before table creation (matches setup_test_environment.py)
            with connection.cursor() as cursor:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
                cursor.execute("CREATE EXTENSION IF NOT EXISTS ltree")

            return super().handle(*args, **kwargs)

    migrate.Command = MigrateSilentCommand  # type: ignore
