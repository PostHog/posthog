from django_linear_migrations.management.commands.makemigrations import Command as LinearMakeMigrationsCommand

from posthog.management.migration_autodetector import PostHogAutodetector


# posthog comes before django_linear_migrations in INSTALLED_APPS, so this command replaces
# linear-migrations' makemigrations. Subclassing it keeps max_migration.txt up to date.
class Command(LinearMakeMigrationsCommand):
    autodetector = PostHogAutodetector
